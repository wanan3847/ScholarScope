"""Project library organization and real, offline bibliographic exports."""
import csv
import io
import json
import re
from workspace.store import WorkspaceError, normalized
from workspace.research_tools import matrix


def organize_paper(store, pid, actor, paper_id, data, revision):
    paper = store.item(pid, actor, paper_id, "paper")
    if paper["revision"] != revision: raise WorkspaceError("文献已被更新，请重新加载", 409)
    tags = sorted(set(normalized(t) for t in data.get("tags", paper["data"].get("tags", [])) if normalized(t)))
    if len(tags) > 40 or any(len(t) > 60 for t in tags): raise WorkspaceError("标签最多 40 个，每个不超过 60 字")
    collections = data.get("collection_ids", paper["data"].get("collection_ids", []))
    if not isinstance(collections, list) or len(collections) > 40: raise WorkspaceError("资料集合格式无效")
    for cid in collections: store.item(pid, actor, cid, "collection")
    fields = {k: bool(data[k]) for k in ("bookmarked", "read") if k in data}
    return store.put(pid, actor, "paper", paper["label"], {**paper["data"], **fields, "tags": tags, "collection_ids": sorted(set(collections))}, paper_id, revision)


def create_collection(store, pid, actor, title):
    title = normalized(title)
    if not title or len(title) > 100: raise WorkspaceError("集合名称需为 1–100 个字符")
    old = next((r for r in store.items(pid, actor, "collection") if r["label"] == title), None)
    return old or store.put(pid, actor, "collection", title, {})


def import_papers(store, pid, actor, papers):
    with store.engine.connect() as conn: store._access(conn, pid, actor, edit=True)
    if not isinstance(papers, list) or not 1 <= len(papers) <= 500: raise WorkspaceError("每次导入需为 1–500 篇文献")
    imported, failures = [], []
    for i, paper in enumerate(papers):
        try:
            if not isinstance(paper, dict): raise WorkspaceError("文献资料格式无效")
            if not isinstance(paper.get("authors", []), list): raise WorkspaceError("作者需为列表")
            clean = {k: paper[k] for k in ("id", "paper_id", "title", "authors", "abstract", "year", "doi", "arxiv_id", "venue", "url", "tags") if k in paper}
            clean["source"] = "user_import"
            imported.append(store.add_paper(pid, actor, clean)["id"])
        except WorkspaceError as error: failures.append({"row": i + 1, "reason": str(error)})
    return {"imported": len(set(imported)), "paper_ids": list(dict.fromkeys(imported)), "failures": failures}


def text_cell(value):
    text = str(value if value is not None else "")
    return "'" + text if text[:1] in "=+@-" and text else text


def export_references(store, pid, actor, fmt, collection_id=None):
    papers = [r["data"] for r in store.items(pid, actor, "paper") if collection_id is None or collection_id in r["data"].get("collection_ids", [])]
    if collection_id: store.item(pid, actor, collection_id, "collection")
    if fmt == "json": return json.dumps(papers, ensure_ascii=False, indent=2).encode(), "application/json"
    if fmt == "csv":
        out = io.StringIO(); writer = csv.writer(out); fields = ["title", "authors", "year", "venue", "doi", "url", "abstract", "tags"]
        writer.writerow(fields)
        for p in papers: writer.writerow([text_cell("; ".join(p.get(k, [])) if isinstance(p.get(k), list) else p.get(k)) for k in fields])
        return ("\ufeff" + out.getvalue()).encode(), "text/csv;charset=utf-8"
    if fmt == "ris":
        def one_line(value): return normalized(value)
        rows = []
        for p in papers:
            row = ["TY  - JOUR", "TI  - " + one_line(p["title"])] + ["AU  - " + one_line(a) for a in p.get("authors", [])]
            for tag, key in (("PY", "year"), ("JO", "venue"), ("DO", "doi"), ("UR", "url"), ("AB", "abstract")):
                if p.get(key): row.append(tag + "  - " + one_line(p[key]))
            row += ["KW  - " + one_line(t) for t in p.get("tags", [])] + ["ER  - "]
            rows.append("\n".join(row))
        return "\n\n".join(rows).encode(), "application/x-research-info-systems"
    if fmt == "bib":
        def escape(value):
            replacements = {"\\": "\\textbackslash{}", "{": "\\{", "}": "\\}", "&": "\\&", "%": "\\%", "_": "\\_", "#": "\\#", "$": "\\$"}
            return "".join(replacements.get(c, c) for c in normalized(value))
        rows = []
        for i, p in enumerate(papers):
            fields = {"title": p["title"], "author": " and ".join(p.get("authors", [])), "year": p.get("year"), "journal": p.get("venue"), "doi": p.get("doi"), "url": p.get("url"), "abstract": p.get("abstract")}
            rows.append("@article{scholarscope" + str(i + 1) + ",\n" + ",\n".join("  " + k + " = {" + escape(v) + "}" for k, v in fields.items() if v) + "\n}")
        return "\n\n".join(rows).encode(), "application/x-bibtex"
    raise WorkspaceError("支持 BibTeX、RIS、JSON、CSV 导出")


def export_matrix(store, pid, actor, fmt):
    data = matrix(store, pid, actor)
    headers = ["文献", "DOI"] + [c["label"] for c in data["columns"]]
    rows, sources = [], []
    for r in data["rows"]:
        rows.append([r["paper"]["label"], r["paper"]["data"].get("doi", "")] + [r["cells"][c["id"]].get("value") or "尚未提取或未报告" for c in data["columns"]])
        for c in data["columns"]:
            cell = r["cells"][c["id"]]; e = cell.get("evidence")
            if e: sources.append([r["paper"]["label"], c["label"], e["id"], e["data"]["quote"], e["data"].get("page"), e["data"].get("document_id"), e["data"]["source_hash"], e["revision"], "原文匹配" if cell["source_valid"] else "来源已变化", "已确认" if e["data"].get("confirmed_by") else "待确认"])
    source_headers = ["文献", "字段", "证据ID", "原文", "页码", "文档ID", "来源哈希", "证据版本", "核验", "人工确认"]
    if fmt == "csv":
        out = io.StringIO(); writer = csv.writer(out); writer.writerow(headers)
        writer.writerows([[text_cell(v) for v in row] for row in rows]); writer.writerow([]); writer.writerow(source_headers)
        writer.writerows([[text_cell(v) for v in row] for row in sources])
        return ("\ufeff" + out.getvalue()).encode(), "text/csv;charset=utf-8"
    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook(); main = wb.active; main.title = "证据矩阵"; audit = wb.create_sheet("原文出处")
        for sheet, head, values in ((main, headers, rows), (audit, source_headers, sources)):
            sheet.append(head)
            for row in values: sheet.append([text_cell(v) if isinstance(v, str) else v for v in row])
            sheet.freeze_panes = "C2"; sheet.auto_filter.ref = sheet.dimensions
            for col in sheet.columns: sheet.column_dimensions[col[0].column_letter].width = 28
        out = io.BytesIO(); wb.save(out)
        return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    raise WorkspaceError("支持 CSV、Excel 矩阵导出")
