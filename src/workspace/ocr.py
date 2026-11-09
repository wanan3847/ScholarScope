"""Local OCR through bounded Poppler/Tesseract processes, without cloud upload."""
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def available():
    return bool(shutil.which("pdftoppm") and shutil.which("tesseract"))


def recognize(blob, pages, *, budget=30):
    if not available() or os.getenv("SCHOLARSCOPE_DISABLE_OCR") == "1": return 0
    deadline = time.monotonic() + budget
    languages = os.getenv("SCHOLARSCOPE_OCR_LANG", "eng")
    if not all(c.isalnum() or c in "_+" for c in languages): languages = "eng"
    changed = 0
    with tempfile.TemporaryDirectory(prefix="research-ocr-") as folder:
        source = Path(folder) / "source.pdf"; source.write_bytes(blob)
        for page in [p for p in pages if not p["text"].strip()][:20]:
            if deadline - time.monotonic() < 2: break
            target = Path(folder) / "page"
            try:
                rendered = subprocess.run(["pdftoppm", "-f", str(page["number"]), "-l", str(page["number"]),
                    "-scale-to", "2400", "-singlefile", "-png", str(source), str(target)], capture_output=True,
                    timeout=min(8, max(.1, deadline-time.monotonic())))
                if rendered.returncode: continue
                result = subprocess.run(["tesseract", str(target)+".png", "stdout", "-l", languages, "--psm", "3", "tsv"],
                    capture_output=True, timeout=min(12, max(.1, deadline-time.monotonic())))
                if result.returncode: continue
                rows = list(csv.DictReader(io.StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t"))
                root = next((r for r in rows if r["level"] == "1"), None)
                if not root: continue
                sx, sy = page["width"]/max(1,float(root["width"])), page["height"]/max(1,float(root["height"]))
                lines, scores = {}, []
                for row in rows[:20000]:
                    value = row.get("text", "").strip(); confidence = float(row.get("conf", -1))
                    if row["level"] != "5" or not value or confidence < 20: continue
                    key = (row["block_num"], row["par_num"], row["line_num"])
                    bbox = [float(row["left"])*sx, float(row["top"])*sy,
                        (float(row["left"])+float(row["width"]))*sx, (float(row["top"])+float(row["height"]))*sy]
                    lines.setdefault(key, []).append((value,bbox)); scores.append(confidence)
                spans = []
                for words in lines.values():
                    spans.append({"id": f"p{page['number']}-ocr{len(spans)+1}", "text": " ".join(w[0] for w in words),
                        "bbox": [min(w[1][0] for w in words),min(w[1][1] for w in words),max(w[1][2] for w in words),max(w[1][3] for w in words)], "method": "ocr"})
                value = "\n".join(s["text"] for s in spans)
                if len(value.strip()) >= 15:
                    from workspace.store import digest
                    page.update(text=value, text_hash=digest(value), spans=spans, status="ocr", ocr_confidence=round(sum(scores)/len(scores),1),
                        ocr_engine="tesseract", ocr_language=languages)
                    changed += 1
            except (OSError, subprocess.TimeoutExpired, ValueError, KeyError): continue
    return changed
