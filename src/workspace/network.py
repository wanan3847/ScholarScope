"""Bounded public HTTPS downloads pin the validated DNS address at connect time."""
import http.client
import base64
import os
import certifi
import ipaddress
import socket
import ssl
import time
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from urllib.parse import urlsplit, urljoin
from urllib.parse import unquote
from urllib.request import getproxies, proxy_bypass
from workspace.store import WorkspaceError

_dns = ThreadPoolExecutor(max_workers=4, thread_name_prefix="public-source-dns")


def public_target(url, *, remaining=3):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
        host = parsed.hostname.rstrip(".").encode("idna").decode()
        if len(host) > 253 or any(c.isspace() for c in host): raise ValueError()
    except (ValueError, UnicodeError): raise WorkspaceError("全文地址需为公开 HTTPS 链接，不能含登录信息或非标准端口") from None
    job = _dns.submit(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    try: addresses = job.result(timeout=max(.1, min(3, remaining)))
    except Exception:
        job.cancel(); raise WorkspaceError("全文地址暂时无法解析", 503) from None
    # Some administrator-managed DNS proxies use benchmarking addresses. Resolve
    # independently, then still connect to a validated public IP with TLS SNI.
    synthetic = ipaddress.ip_network("198.18.0.0/15")
    if addresses and all(ipaddress.ip_address(a[4][0]) in synthetic for a in addresses):
        try:
            ipaddress.ip_address(host)
            raise WorkspaceError("保留网络地址不能用于远程下载")
        except ValueError: pass
        try:
            answer = requests.get("https://cloudflare-dns.com/dns-query", params={"name": host, "type": "A"},
                headers={"Accept": "application/dns-json"}, timeout=max(.1, min(3, remaining)), allow_redirects=False).json()
            addresses = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (r["data"], 443)) for r in answer.get("Answer", []) if r.get("type") == 1]
        except Exception: raise WorkspaceError("全文地址无法通过独立公共 DNS 核验", 503) from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global or ipaddress.ip_address(a[4][0]).is_multicast for a in addresses):
        raise WorkspaceError("全文地址指向内部或保留网络，不能用于远程下载")
    addresses.sort(key=lambda a: a[0] != socket.AF_INET)
    return parsed, host, addresses[0][4][0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, timeout):
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=os.getenv("SCHOLARSCOPE_CA_BUNDLE") or os.getenv("REQUESTS_CA_BUNDLE") or certifi.where())
        super().__init__(host, timeout=timeout, context=context)
        self.pinned_ip = ip

    def connect(self):
        # Respect an operator-configured system/environment HTTP proxy while
        # tunnelling to the pinned IP, so the proxy never re-resolves user hosts.
        proxy = getproxies().get("https") if not proxy_bypass(self.host) else None
        if proxy:
            endpoint = urlsplit(proxy if "://" in proxy else "http://" + proxy)
            if endpoint.scheme != "http" or not endpoint.hostname:
                raise WorkspaceError("当前全文代理不支持安全 IP 隧道，请配置 HTTP CONNECT 代理", 503)
            sock = socket.create_connection((endpoint.hostname, endpoint.port or 80), timeout=self.timeout)
            headers = {}
            if endpoint.username:
                auth = unquote(endpoint.username) + ":" + unquote(endpoint.password or "")
                headers["Proxy-Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
            self.set_tunnel(self.pinned_ip, 443, headers=headers)
            self.sock = sock
            try: self._tunnel()
            except Exception: sock.close(); raise
        else:
            sock = socket.create_connection((self.pinned_ip, 443), timeout=self.timeout)
        try: self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception: sock.close(); raise


def fetch_public(url, *, max_bytes=25 * 1024 * 1024, budget_seconds=30):
    deadline = time.monotonic() + budget_seconds
    current = str(url)
    for _ in range(5):
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise WorkspaceError("全文下载超过执行预算", 504)
        parsed, host, ip = public_target(current, remaining=remaining)
        connection = PinnedHTTPS(host, ip, max(.1, min(6, deadline - time.monotonic())))
        try:
            path = parsed.path or "/"
            if parsed.query: path += "?" + parsed.query
            connection.request("GET", path, headers={"Host": host, "User-Agent": "ScholarScope/1.0 research workspace", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location: raise WorkspaceError("全文服务没有提供有效跳转", 503)
                current = urljoin(current, location)
                continue
            if response.status != 200: raise WorkspaceError("全文服务暂不可用，或该文件需要其他授权", 503)
            size = response.getheader("Content-Length")
            if size and int(size) > max_bytes: raise WorkspaceError("远程全文超过允许大小", 413)
            chunks, length = [], 0
            while True:
                if time.monotonic() > deadline: raise WorkspaceError("全文下载超过执行预算", 504)
                block = response.read(min(65536, max_bytes + 1 - length))
                if not block: break
                length += len(block)
                if length > max_bytes: raise WorkspaceError("远程全文超过允许大小", 413)
                chunks.append(block)
            return {"bytes": b"".join(chunks), "url": current, "content_type": response.getheader("Content-Type", "")}
        except WorkspaceError: raise
        except Exception: raise WorkspaceError("全文连接失败，请使用开放链接或上传可读取的 PDF", 503) from None
        finally: connection.close()
    raise WorkspaceError("全文服务跳转过多", 503)
