"""Zotero v3 adapter: incremental pulls, versioned pushes and explicit conflicts.

Only the fixed official API receives credentials. Signed attachment redirects
use the public downloader without the Zotero header. Sync state is encrypted
per account; project reports contain counts and bibliographic provenance only.
"""
import json
import re
import secrets
import time
from urllib.parse import urljoin
import requests
from workspace.store import WorkspaceError, digest, normalized
from workspace.vault import IntegrationVault
from workspace.documents import ObjectStore, attach_pdf, MAX_UPLOAD
from workspace.network import fetch_public
from workspace.library import create_collection

FIELDS = ("title", "abstract", "doi", "authors", "year", "venue", "url", "tags")
KEY = re.compile(r"[A-Z0-9]{8}")


def _access(store, pid, actor):
    if actor == "web-anonymous": raise WorkspaceError("Zotero 配置和同步需要登录", 401)
    with store.engine.connect() as conn: store._access(conn, pid, actor, edit=True)


def _hash(data):
    return digest(json.dumps({k: data.get(k) for k in FIELDS}, ensure_ascii=False, sort_keys=True))


def _public(record):
    if not record: return {"configured": False, "conflicts": []}
    return {"configured": True, "library_type": record["library_type"], "library_id": record["library_id"],
        "collection_key": record.get("collection_key", ""), "allow_write": record.get("allow_write", False),
        "version": record.get("since", 0), "pending": bool(record.get("cursor")), "last_sync": record.get("last_sync"),
        "mapped_count": len(record.get("mappings", {})), "conflicts": list(record.get("conflicts", {}).values()),
        "last_report": record.get("last_report", {}), "connection_check": record.get("connection_check")}


def status(store, pid, actor, vault=None):
    _access(store, pid, actor)
    return _public((vault or IntegrationVault()).get(actor, pid))


def configure(store, pid, actor, data, vault=None):
    _access(store, pid, actor); vault = vault or IntegrationVault()
    with vault.connection_lock(actor, pid):
        old = vault.get(actor, pid) or {}
        typ, number, collection = data.get("library_type"), str(data.get("library_id", "")).strip(), str(data.get("collection_key", "")).strip().upper()
        if typ not in ("users", "groups") or not re.fullmatch(r"[1-9]\d{0,14}", number) or collection and not KEY.fullmatch(collection):
            raise WorkspaceError("Zotero 库类型、数字库 ID 或集合键无效")
        token = str(data.get("api_key") or old.get("api_key", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9]{16,128}", token): raise WorkspaceError("请输入有效 Zotero API Key")
        same = (typ, number, collection) == (old.get("library_type"), old.get("library_id"), old.get("collection_key", ""))
        record = {**(old if same else {}), "library_type": typ, "library_id": number, "collection_key": collection,
            "api_key": token, "allow_write": data.get("allow_write") is True}
        if not same or token != old.get("api_key"):
            record.pop("connection_check", None)
        vault.put(actor, pid, record)
        return _public(record)


def disconnect(store, pid, actor, vault=None):
    _access(store, pid, actor); vault = vault or IntegrationVault()
    with vault.connection_lock(actor, pid): vault.put(actor, pid, None)
    return {"configured": False}


class ZoteroClient:
    def __init__(self, record, *, session=None, budget=105):
        self.record, self.session = record, session or requests.Session()
        self.prefix = "https://api.zotero.org/" + record["library_type"] + "/" + record["library_id"]
        self.deadline = time.monotonic() + budget

    def request(self, method, path, **kwargs):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise WorkspaceError("Zotero 本轮同步预算已到，进度已保存，可继续同步", 504)
        headers = {"Zotero-API-Version": "3", "Zotero-API-Key": self.record["api_key"], **kwargs.pop("headers", {})}
        try:
            response = self.session.request(method, self.prefix + path, headers=headers, timeout=min(8, remaining), allow_redirects=False, **kwargs)
        except requests.RequestException: raise WorkspaceError("Zotero 连接暂不可用；已完成的同步进度已保存", 503) from None
        if response.status_code == 412: raise WorkspaceError("Zotero 条目版本已变化，需重新导入或处理冲突", 409)
        if response.status_code in (401, 403): raise WorkspaceError("Zotero 密钥无效或缺少该库的访问权限", 403)
        if response.status_code == 404: raise WorkspaceError("Zotero 库、集合或条目不存在，或当前账号无法访问", 404)
        if response.status_code in (429, 503) or response.headers.get("Backoff"):
            raise WorkspaceError("Zotero 要求暂缓请求；本轮已停止，请稍后继续同步", 503)
        if response.status_code not in (200, 204, 302, 303, 307): raise WorkspaceError("Zotero 暂未返回可用数据", 503)
        return response

    def file(self, key):
        if not KEY.fullmatch(key): raise WorkspaceError("附件键无效")
        response = self.request("GET", "/items/" + key + "/file", stream=True)
        try:
            if response.status_code != 200:
                target = urljoin(self.prefix, response.headers.get("Location", ""))
                return fetch_public(target, budget_seconds=max(.1, min(25, self.deadline - time.monotonic())))["bytes"]
            if int(response.headers.get("Content-Length", 0)) > MAX_UPLOAD: raise WorkspaceError("Zotero 附件超过上传限制")
            chunks, size = [], 0
            for block in response.iter_content(65536):
                if time.monotonic() >= self.deadline: raise WorkspaceError("附件下载超过同步预算", 504)
                size += len(block)
                if size > MAX_UPLOAD: raise WorkspaceError("Zotero 附件超过上传限制")
                chunks.append(block)
            return b"".join(chunks)
        finally: response.close()


def check_connection(store, pid, actor, *, vault=None, client_factory=ZoteroClient):
    """Read-only verification of the saved account's library and selected collection."""
    _access(store, pid, actor); vault = vault or IntegrationVault()
    with vault.connection_lock(actor, pid):
        record = vault.get(actor, pid)
        if not record: raise WorkspaceError("请先保存当前账号的 Zotero 配置")
        client = client_factory(record)
        try:
            if record.get("collection_key"):
                data = client.request("GET", "/collections/" + record["collection_key"]).json()
                if not isinstance(data, dict) or data.get("key") != record["collection_key"]:
                    raise WorkspaceError("Zotero 集合响应格式无效", 503)
            rows = client.request("GET", "/items", params={"format": "json", "limit": 1}).json()
            if not isinstance(rows, list): raise WorkspaceError("Zotero 条目响应格式无效", 503)
            result = {"ok": True, "message": "文献库读取权限已验证；导出和附件权限由对应操作核验"}
        except WorkspaceError as error:
            result = {"ok": False, "message": str(error)}
        result["checked_at"] = time.time()
        record["connection_check"] = result; vault.put(actor, pid, record)
        return _public(record)


def _metadata(raw, record):
    d = raw.get("data", {}); title = normalized(d.get("title", ""))
    if not title: raise WorkspaceError("Zotero 条目没有可用标题")
    year = re.search(r"\b(?:19|20)\d{2}\b", str(d.get("date", "")))
    return {"title": title, "abstract": str(d.get("abstractNote", "")), "doi": str(d.get("DOI", "")).strip().lower(),
        "authors": [normalized(c.get("name") or c.get("firstName", "") + " " + c.get("lastName", "")) for c in d.get("creators", []) if c.get("creatorType") == "author"],
        "year": int(year[0]) if year else None, "venue": d.get("publicationTitle") or d.get("proceedingsTitle") or d.get("bookTitle", ""),
        "url": d.get("url", ""), "tags": [str(t["tag"])[:60] for t in d.get("tags", []) if t.get("tag")][:40],
        "paper_id": "zotero:" + record["library_type"] + ":" + record["library_id"] + ":" + raw["key"], "source": "zotero"}


def _payload(data):
    result = {"title": data.get("title", ""), "abstractNote": data.get("abstract", ""), "DOI": data.get("doi", ""),
        "creators": [{"creatorType": "author", "name": a} for a in data.get("authors", [])],
        "date": str(data.get("year") or ""), "url": data.get("url", ""), "tags": [{"tag": t} for t in data.get("tags", [])]}
    return result


class Sync:
    def __init__(self, store, pid, actor, vault, record, client, objects):
        self.store, self.pid, self.actor, self.vault, self.record, self.client, self.objects = store, pid, actor, vault, record, client, objects
        for key in ("mappings", "collections", "conflicts", "attachments", "pending_push"): record.setdefault(key, {})
        self.report = {"imported": 0, "exported": 0, "attachments": 0, "unchanged": 0, "errors": [], "conflicts": [], "complete": False}

    def save(self): self.vault.put(self.actor, self.pid, self.record)

    def import_item(self, raw, force=False):
        key = raw.get("key", "")
        if not KEY.fullmatch(key): raise WorkspaceError("Zotero 返回的条目键无效")
        metadata = _metadata(raw, self.record); mapping = self.record["mappings"].get(key)
        old = self.store.item(self.pid, self.actor, mapping["paper_id"], "paper") if mapping else None
        remote_hash = _hash(metadata)
        if not force and old and _hash(old["data"]) != mapping["local_hash"]:
            if remote_hash != mapping["remote_hash"]:
                self.record["conflicts"][key] = {"key": key, "paper_id": old["id"], "title": metadata["title"], "remote": metadata,
                    "remote_version": raw.get("version", 0), "reason": "本地和 Zotero 元数据均已修改"}
                self.report["conflicts"].append(key); self.save()
            else:
                mapping["version"] = raw.get("version", mapping["version"])
                self.report["unchanged"] += 1; self.save()
            return old
        collection_ids = [self.record["collections"][c] for c in raw.get("data", {}).get("collections", []) if c in self.record["collections"]]
        if old:
            # Explicit remote choice may clear metadata; preserve local organization.
            data = {**old["data"], **metadata, "collection_ids": sorted(set(old["data"].get("collection_ids", []) + collection_ids))}
            data["abstract_hash"] = digest(data.get("abstract", ""))
            paper = old if _hash(old["data"]) == remote_hash and data["collection_ids"] == old["data"].get("collection_ids", []) else self.store.put(self.pid, self.actor, "paper", metadata["title"], data, old["id"], old["revision"])
        else:
            paper = self.store.add_paper(self.pid, self.actor, {**metadata, "collection_ids": collection_ids})
        self.record["mappings"][key] = {"paper_id": paper["id"], "version": raw.get("version", 0), "local_hash": _hash(paper["data"]), "remote_hash": remote_hash}
        self.record["conflicts"].pop(key, None); self.report["imported"] += 1; self.save()
        return paper

    def attachment(self, raw):
        d = raw.get("data", {}); key = raw.get("key", ""); parent = self.record["mappings"].get(d.get("parentItem"))
        if not parent or d.get("contentType") != "application/pdf" or not KEY.fullmatch(key): return
        if self.record["attachments"].get(key, {}).get("version") == raw.get("version", 0): return
        if d.get("linkMode") not in ("imported_file", "imported_url", "linked_url"):
            self.report["errors"].append({"key": key, "message": "附件只在本地或链接模式不可下载；未创建文件"}); return
        try:
            blob = fetch_public(d.get("url", ""), budget_seconds=max(.1, min(25, self.client.deadline - time.monotonic())))["bytes"] if d.get("linkMode") == "linked_url" else self.client.file(key)
            document = attach_pdf(self.store, self.objects, self.pid, self.actor, parent["paper_id"], d.get("filename", "zotero.pdf"), blob)
            self.record["attachments"][key] = {"version": raw.get("version", 0), "document_id": document["id"]}
            self.report["attachments"] += 1; self.save()
        except WorkspaceError as error:
            self.record.setdefault("retry_attachments", {})[key] = raw
            self.report["errors"].append({"key": key, "message": str(error)}); self.save()

    def pull(self, attachments):
        if attachments:
            for key, raw in list(self.record.get("retry_attachments", {}).items())[:100]:
                self.attachment(raw)
                if self.record["attachments"].get(key, {}).get("version") == raw.get("version", 0):
                    self.record["retry_attachments"].pop(key, None); self.save()
        for key, raw in list(self.record.get("retry_items", {}).items())[:100]:
            try:
                self.import_item(raw); self.record["retry_items"].pop(key, None); self.save()
            except WorkspaceError: pass
        # Collection mapping names remain project-local. No delete propagation.
        start = 0
        for _ in range(10):
            response = self.client.request("GET", "/collections", params={"format": "json", "limit": 100, "start": start})
            rows = response.json()
            if not isinstance(rows, list): raise WorkspaceError("Zotero 集合响应格式无效", 503)
            for row in rows:
                key = row.get("key", "")
                if KEY.fullmatch(key) and key not in self.record["collections"]:
                    self.record["collections"][key] = create_collection(self.store, self.pid, self.actor, row.get("data", {}).get("name", "Zotero collection"))["id"]
            self.save()
            if len(rows) < 100: break
            start += len(rows)
        cursor = self.record.get("cursor") or {"since": self.record.get("since", 0), "start": 0}
        path = "/collections/" + self.record["collection_key"] + "/items" if self.record.get("collection_key") else "/items"
        for _ in range(10):
            response = self.client.request("GET", path, params={"format": "json", "limit": 100, "start": cursor["start"], "since": cursor["since"], "sort": "dateAdded", "direction": "asc"})
            rows = response.json()
            if not isinstance(rows, list): raise WorkspaceError("Zotero 条目响应格式无效", 503)
            cursor.setdefault("version", int(response.headers.get("Last-Modified-Version", cursor["since"])))
            for raw in rows:
                if raw.get("data", {}).get("itemType") in ("attachment", "note", "annotation") or raw.get("data", {}).get("deleted"): continue
                try: self.import_item(raw)
                except WorkspaceError as error:
                    self.record.setdefault("retry_items", {})[raw.get("key", "")] = raw
                    self.report["errors"].append({"key": raw.get("key"), "message": str(error)}); self.save()
            if attachments:
                for raw in rows:
                    if raw.get("data", {}).get("itemType") == "attachment": self.attachment(raw)
                    elif raw.get("key") in self.record["mappings"]:
                        children = self.client.request("GET", "/items/" + raw["key"] + "/children", params={"format": "json", "limit": 100}).json()
                        for child in children: self.attachment(child)
            cursor["start"] += len(rows); self.record["cursor"] = cursor; self.save()
            if len(rows) < 100:
                self.record["since"] = cursor["version"]; self.record.pop("cursor", None)
                self.report["complete"] = True; break

    def push_item(self, paper, key=None):
        if key:
            mapping = self.record["mappings"][key]
            remote = self.client.request("GET", "/items/" + key).json()
            if int(remote.get("version", 0)) != mapping["version"]:
                self.record["conflicts"][key] = {"key": key, "paper_id": paper["id"], "title": paper["label"], "remote": _metadata(remote, self.record),
                    "remote_version": remote.get("version", 0), "reason": "Zotero 版本已变化，导出未覆盖远端"}
                self.report["conflicts"].append(key); self.save(); return
            payload = _payload(paper["data"])
            venue_field = next((f for f in ("publicationTitle", "proceedingsTitle", "bookTitle") if f in remote["data"]), None)
            if venue_field: payload[venue_field] = paper["data"].get("venue", "")
            # Avoid sending DOI/abstract fields unsupported by a remote item type.
            payload = {k: v for k, v in payload.items() if k in remote["data"]}
            self.client.request("PATCH", "/items/" + key, json=payload, headers={"If-Unmodified-Since-Version": str(mapping["version"])})
            saved = self.client.request("GET", "/items/" + key).json()
        else:
            pending = self.record["pending_push"].setdefault(paper["id"], {"key": "".join(secrets.choice("23456789ABCDEFGHIJKLMNPQRSTUVWXYZ") for _ in range(8)), "token": secrets.token_hex(16), "submitted": False})
            self.save(); key = pending["key"]
            # Recover a completed request after a connection/process interruption.
            saved = None
            if pending["submitted"]:
                try: saved = self.client.request("GET", "/items/" + key).json()
                except WorkspaceError as error:
                    if error.status != 404: raise
            if not saved:
                pending["submitted"] = True; self.save()
                payload = {"key": key, "itemType": "journalArticle", **_payload(paper["data"]), "publicationTitle": paper["data"].get("venue", ""),
                    "collections": [self.record["collection_key"]] if self.record.get("collection_key") else [], "relations": {}}
                response = self.client.request("POST", "/items", json=[payload], headers={"Zotero-Write-Token": pending["token"]})
                data = response.json(); saved = data.get("successful", {}).get("0")
                failed = data.get("failed", {}).get("0")
                if failed:
                    # Remote error text may echo credentials or arbitrary request data.
                    # Persist only its code and recognized field names in shared reports.
                    code = str(failed.get("code", "unknown"))
                    code = code if code.isdigit() else "unknown"
                    fields = [f for f in ("itemType", "title", "creators", "DOI", "tags", "collections", "relations", "version") if re.search(r"\b" + f + r"\b", str(failed.get("message", "")), re.I)]
                    hint = "；检查字段 " + "、".join(fields) if fields else "；请检查条目元数据、集合和写入权限"
                    raise WorkspaceError("Zotero 拒绝导出条目（" + code + "）" + hint, int(code) if code.isdigit() else 503)
                if not saved and (data.get("success", {}).get("0") == key or data.get("unchanged", {}).get("0") == key):
                    saved = self.client.request("GET", "/items/" + key).json()
                if not saved: raise WorkspaceError("Zotero 未确认条目导出成功；保留重试标识", 503)
            if not isinstance(saved, dict) or saved.get("key") != key or not isinstance(saved.get("version"), int):
                raise WorkspaceError("Zotero 返回的保存结果无法核对；保留重试标识", 503)
        remote_metadata = _metadata(saved, self.record)
        self.record["mappings"][key] = {"paper_id": paper["id"], "version": saved["version"], "local_hash": _hash(paper["data"]), "remote_hash": _hash(remote_metadata)}
        self.record["pending_push"].pop(paper["id"], None); self.record["conflicts"].pop(key, None)
        self.report["exported"] += 1; self.save()

    def push(self):
        if not self.record.get("allow_write"): raise WorkspaceError("请先在该账号的 Zotero 配置中启用导出权限", 403)
        inverse = {v["paper_id"]: k for k, v in self.record["mappings"].items()}
        for paper in self.store.items(self.pid, self.actor, "paper"):
            key = inverse.get(paper["id"])
            if key in self.record["conflicts"]: self.report["conflicts"].append(key); continue
            if key and _hash(paper["data"]) == self.record["mappings"][key]["local_hash"]: self.report["unchanged"] += 1; continue
            try: self.push_item(paper, key)
            except WorkspaceError as error:
                if error.status not in (400, 404, 409, 422): raise
                self.report["errors"].append({"paper_id": paper["id"], "message": str(error)}); self.save()
        self.report["complete"] = not self.report["errors"]


def sync(store, pid, actor, direction="pull", attachments=False, *, vault=None, client_factory=ZoteroClient, objects=None):
    _access(store, pid, actor)
    if direction not in ("pull", "push"): raise WorkspaceError("同步方向无效")
    vault = vault or IntegrationVault()
    with vault.connection_lock(actor, pid):
        record = vault.get(actor, pid)
        if not record: raise WorkspaceError("请先配置当前账号的 Zotero 库")
        operation = Sync(store, pid, actor, vault, record, client_factory(record), objects or ObjectStore())
        try:
            if direction == "pull": operation.pull(attachments)
            else: operation.push()
        except WorkspaceError as error:
            operation.report["errors"].append({"message": str(error)})
        record["last_sync"] = time.time(); record["last_report"] = operation.report; operation.save()
        report = store.put(pid, actor, "zotero_report", "Zotero " + ("导入" if direction == "pull" else "导出"), {"direction": direction, **operation.report})
        return {**_public(record), "output_id": report["id"], "kind": "zotero_report"}


def resolve(store, pid, actor, key, choice, *, vault=None, client_factory=ZoteroClient):
    _access(store, pid, actor)
    if not KEY.fullmatch(key) or choice not in ("local", "remote"): raise WorkspaceError("冲突处理选项无效")
    vault = vault or IntegrationVault()
    with vault.connection_lock(actor, pid):
        record = vault.get(actor, pid)
        if not record or key not in record.get("conflicts", {}): raise WorkspaceError("同步冲突不存在", 404)
        operation = Sync(store, pid, actor, vault, record, client_factory(record), ObjectStore())
        raw = operation.client.request("GET", "/items/" + key).json()
        if choice == "remote": operation.import_item(raw, force=True)
        else:
            if not record.get("allow_write"): raise WorkspaceError("未启用 Zotero 导出权限", 403)
            record["mappings"][key]["version"] = raw["version"]
            paper = store.item(pid, actor, record["mappings"][key]["paper_id"], "paper")
            operation.push_item(paper, key)
        operation.save()
        return _public(record)
