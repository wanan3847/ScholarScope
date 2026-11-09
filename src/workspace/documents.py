"""Bounded PDF parsing and content-addressed local/S3 object storage."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from workspace.store import WorkspaceError, digest, ident, normalized

MAX_UPLOAD = 25 * 1024 * 1024
MAX_PAGES = 300


class ObjectStore:
    def __init__(self, root=None, bucket=None, client=None):
        self.root = Path(root or os.getenv("SCHOLARSCOPE_WORKSPACE_DIR", Path(__file__).resolve().parents[1] / "data" / "workspace")) / "objects"
        self.bucket = bucket or os.getenv("SCHOLARSCOPE_S3_BUCKET")
        self.client = client
        if self.bucket and not client:
            import boto3
            from botocore.config import Config
            self.client = boto3.client("s3", endpoint_url=os.getenv("SCHOLARSCOPE_S3_ENDPOINT") or None,
                config=Config(connect_timeout=3, read_timeout=8, retries={"total_max_attempts": 2, "mode": "standard"}))

    def put(self, blob: bytes, extension="pdf"):
        if not re.fullmatch(r"[a-z0-9]{1,10}", extension):
            raise WorkspaceError("文件扩展名无效")
        sha = digest(blob)
        key = sha[:2] + "/" + sha + "." + extension
        if self.bucket:
            try:
                self.client.put_object(Bucket=self.bucket, Key=key, Body=blob,
                    ContentType="application/pdf" if extension == "pdf" else "application/octet-stream")
            except Exception:
                raise WorkspaceError("文件存储暂时不可用，请稍后重试", 503) from None
        else:
            path = self.root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                # Atomic content-addressed write; partial uploads cannot be read.
                fd, name = tempfile.mkstemp(dir=path.parent)
                with os.fdopen(fd, "wb") as f:
                    f.write(blob)
                os.replace(name, path)
        return {"object_key": key, "sha256": sha, "bytes": len(blob)}

    def get(self, key):
        if not re.fullmatch(r"[a-f0-9]{2}/[a-f0-9]{64}\.[a-z0-9]+", key):
            raise WorkspaceError("文件标识无效")
        if self.bucket:
            try:
                blob = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except Exception:
                raise WorkspaceError("文件暂时不可用", 503) from None
        else:
            path = self.root / key
            if not path.exists():
                raise WorkspaceError("文件不存在", 404)
            blob = path.read_bytes()
        if digest(blob) != key.split("/")[1].split(".")[0]:
            raise WorkspaceError("文件完整性校验失败，请重新上传原始文件", 503)
        return blob


def parse_pdf(blob: bytes) -> dict:
    """Actual structured extraction; never invent text for scans or missing data."""
    import pdfplumber
    from pypdf import PdfReader
    if not blob[:1024].lstrip().startswith(b"%PDF-"):
        raise WorkspaceError("文件不是有效 PDF")
    if len(blob) > MAX_UPLOAD:
        raise WorkspaceError("PDF 不得超过 25 MB", 413)
    try:
        reader = PdfReader(io.BytesIO(blob), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise WorkspaceError("该 PDF 已加密，请上传可读取的文件")
        if not 0 < len(reader.pages) <= MAX_PAGES:
            raise WorkspaceError("PDF 需为 1–300 页")
        metadata = dict(reader.metadata or {})
        outlines = []
        def visit(items, depth=0):
            for item in items:
                if isinstance(item, list):
                    visit(item, depth + 1)
                else:
                    try:
                        outlines.append({"title": str(item.title), "page": reader.get_destination_page_number(item) + 1, "depth": depth})
                    except Exception:
                        continue
        try:
            visit(reader.outline)
        except Exception:
            pass
        pages, headings = [], []
        with pdfplumber.open(io.BytesIO(blob)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or reader.pages[i].extract_text() or ""
                text = text[:500000]
                spans = []
                for j, line in enumerate(page.extract_text_lines()[:10000]):
                    line_text = str(line.get("text", ""))
                    bbox = [round(float(line.get(k, 0)), 2) for k in ("x0", "top", "x1", "bottom")]
                    spans.append({"id": f"p{i+1}-s{j+1}", "text": line_text, "bbox": bbox})
                    if re.match(r"^(?:\d{1,2}(?:\.\d+)*[ .]|Abstract\b|Introduction\b|Methods?\b|Results?\b|Discussion\b|Conclusions?\b|References\b|摘要|引言|方法|结果|讨论|结论)", line_text, re.I) and len(line_text) < 160:
                        headings.append({"title": line_text, "page": i + 1, "span_id": spans[-1]["id"]})
                tables = []
                try:
                    for j, table in enumerate(page.find_tables()[:30]):
                        rows = table.extract()[:500]
                        tables.append({"id": f"p{i+1}-t{j+1}", "bbox": list(table.bbox), "rows": rows})
                except Exception:
                    pass
                images = [{"id": f"p{i+1}-f{j+1}", "bbox": [float(image.get(k, 0)) for k in ("x0", "top", "x1", "bottom")],
                           "width": image.get("width"), "height": image.get("height")}
                          for j, image in enumerate(page.images[:100])]
                equations = [s["id"] for s in spans if re.search(r"[=∑∫√≤≥±]", s["text"])]
                pages.append({"number": i + 1, "width": float(page.width), "height": float(page.height),
                              "text": text, "text_hash": digest(text), "spans": spans,
                              "tables": tables, "figures": images, "equations": equations,
                              "status": "text" if text.strip() else "no_text"})
        from workspace.ocr import recognize
        ocr_pages = recognize(blob, pages)
        warnings = ["部分页面没有可提取文字，OCR 未取得结果或超过预算，请人工阅读"] if any(not p["text"].strip() for p in pages) else []
        if ocr_pages: warnings.append("OCR 文字可能存在识别错误，引用和数值需对照原始页面人工核对")
        return {"pages": pages, "outline": outlines or headings,
                "metadata": {str(k): str(v)[:5000] for k, v in metadata.items()},
                "page_count": len(pages), "parser": "pdfplumber+pypdf" + ("+tesseract" if ocr_pages else ""), "ocr_pages": ocr_pages,
                "status": "parsed" if any(p["text"].strip() for p in pages) else "scan_no_text",
                "warnings": warnings}
    except WorkspaceError:
        raise
    except Exception:
        raise WorkspaceError("PDF 无法解析，请检查文件是否损坏") from None


def bounded_parse(blob):
    """Parse in a process with a wall-clock deadline, off the API worker."""
    if len(blob) > MAX_UPLOAD:
        raise WorkspaceError("PDF 不得超过 25 MB", 413)
    with tempfile.TemporaryDirectory(prefix="scholarscope-pdf-") as tmp:
        path = Path(tmp) / "source.pdf"
        path.write_bytes(blob)
        try:
            result = subprocess.run([sys.executable, "-m", "workspace.documents", str(path)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=75)
        except subprocess.TimeoutExpired:
            raise WorkspaceError("PDF 解析超过时间预算，请拆分文件后重试", 408) from None
        try:
            data = json.loads(result.stdout)
        except Exception:
            raise WorkspaceError("PDF 解析未完成，请检查文件") from None
        if result.returncode or data.get("error"):
            raise WorkspaceError(data.get("error", "PDF 解析失败"), data.get("status", 400))
        return data


def attach_pdf(store, objects, pid, actor, paper_id, filename, blob, provenance=None):
    paper = store.item(pid, actor, paper_id, "paper")
    store.project(pid, actor)  # Access before any parser or object operation.
    # Check editing permission before spending parser resources or storing files.
    with store.engine.connect() as conn:
        store._access(conn, pid, actor, edit=True)
    parsed = bounded_parse(blob)
    file = objects.put(blob)
    old = next((r for r in store.items(pid, actor, "document") if r["data"].get("sha256") == file["sha256"] and r["data"].get("paper_id") == paper_id), None)
    if old:
        return old
    filename = Path(filename.replace("\\", "/")).name[:250] or "paper.pdf"
    data = {"paper_id": paper["id"], "filename": filename, **file, **parsed,
            "provenance": provenance or {"type": "user_upload"}}
    return store.put(pid, actor, "document", filename, data)


if __name__ == "__main__":
    try:
        result = parse_pdf(Path(sys.argv[1]).read_bytes())
        print(json.dumps(result, ensure_ascii=False))
    except WorkspaceError as e:
        print(json.dumps({"error": str(e), "status": e.status}, ensure_ascii=False))
        sys.exit(1)
