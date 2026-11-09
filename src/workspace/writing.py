"""Versioned manuscripts with typed citations, source checks, and real exports."""
from __future__ import annotations

import copy
import io
import re
from html import escape

from workspace.store import WorkspaceError, normalized, ident

TEMPLATES = [
    {"id": "review", "name": "研究综述", "sections": ["摘要", "研究背景与范围", "研究方法比较", "数据与评价指标", "主要发现", "局限性与研究空白", "结论"], "citation_style": "numeric"},
    {"id": "imrad", "name": "通用研究论文（IMRaD）", "sections": ["摘要", "引言", "方法", "结果", "讨论", "结论"], "citation_style": "author_year"},
    {"id": "proposal", "name": "研究计划 / 开题", "sections": ["摘要", "研究问题", "相关研究", "研究方案", "评价与验证计划", "预期贡献与风险"], "citation_style": "numeric"},
]


def templates(store, pid, actor):
    return copy.deepcopy(TEMPLATES + store.project(pid, actor)["settings"].get("writing_templates", []))


def resolve_template(store, pid, actor, template_id):
    template = next((t for t in templates(store, pid, actor) if t["id"] == template_id), None)
    if not template: raise WorkspaceError("未知写作模板")
    return template


def set_template(store, pid, actor, data, revision):
    project = store.project(pid, actor)
    name = normalized(data.get("name", ""))
    sections = [normalized(s) for s in data.get("sections", [])]
    if not name or len(name) > 150 or not 1 <= len(sections) <= 30 or any(not s or len(s) > 150 for s in sections) or len(set(sections)) != len(sections):
        raise WorkspaceError("模板需要名称及 1–30 个不重复章节")
    style = data.get("citation_style", "numeric")
    if style not in ("numeric", "author_year"): raise WorkspaceError("未知引用格式")
    source_url = str(data.get("source_url", ""))[:2000]
    if source_url and not re.match(r"^https?://[^\s]+$", source_url): raise WorkspaceError("模板来源需为完整网页链接")
    font = str(data.get("font", "Arial"))
    if not re.fullmatch(r"[\w .-]{1,100}", font): raise WorkspaceError("字体名称无效")
    try:
        size, margin = float(data.get("font_size", 11)), float(data.get("margin_mm", 25.4))
        abstract_limit, keyword_limit = int(data.get("abstract_limit", 0)), int(data.get("keyword_limit", 10))
    except (ValueError, TypeError): raise WorkspaceError("模板数值格式无效") from None
    if not 8 <= size <= 20 or not 10 <= margin <= 50 or not 0 <= abstract_limit <= 20000 or not 1 <= keyword_limit <= 20:
        raise WorkspaceError("字号、页边距或摘要/关键词限制超出范围")
    paper_size = data.get("paper_size", "A4")
    unit = data.get("abstract_unit", "characters")
    if paper_size not in ("A4", "Letter") or unit not in ("characters", "words"): raise WorkspaceError("纸张或摘要计数单位无效")
    template_id = data.get("id") or "custom_" + ident()
    custom = project["settings"].get("writing_templates", [])
    if data.get("id") and not any(t["id"] == template_id for t in custom): raise WorkspaceError("仅能更新当前项目自定义模板")
    template = {"id": template_id, "name": name, "sections": sections, "citation_style": style, "source_url": source_url,
        "font": font, "font_size": size, "margin_mm": margin, "paper_size": paper_size, "abstract_limit": abstract_limit,
        "abstract_unit": unit, "keyword_limit": keyword_limit, "origin": "researcher_configured", "configured_by": actor}
    custom = [t for t in custom if t["id"] != template_id] + [template]
    if len(custom) > 30: raise WorkspaceError("项目最多保存 30 个写作模板")
    store.update_project(pid, actor, {"settings": {**project["settings"], "writing_templates": custom}}, revision)
    return template


def text_node(value):
    return {"type": "text", "text": str(value)}


def paragraph(value):
    return {"type": "paragraph", "content": [text_node(value)]} if value else {"type": "paragraph"}


def heading(value, level=2):
    return {"type": "heading", "attrs": {"level": level}, "content": [text_node(value)]}


def citation_node(evidence):
    return {"type": "citation", "attrs": {"evidenceId": evidence["id"], "sourceHash": evidence["data"]["source_hash"],
        "evidenceRevision": evidence["revision"], "label": evidence["data"].get("field", "证据")}}


def walk(node):
    yield node
    for child in node.get("content", []):
        yield from walk(child)


def plain_text(node):
    if node.get("type") == "text":
        return node.get("text", "")
    return "".join(plain_text(c) for c in node.get("content", []))


def clean_content(store, pid, actor, content):
    evidence = {r["id"]: r for r in store.items(pid, actor, "evidence")}
    count, chars = 0, 0
    allowed = {"doc", "heading", "paragraph", "text", "citation", "blockquote", "bulletList", "orderedList", "listItem", "hardBreak", "horizontalRule", "codeBlock"}
    def clean(node, depth=0):
        nonlocal count, chars
        count += 1
        if count > 20000 or depth > 32 or not isinstance(node, dict) or node.get("type") not in allowed:
            raise WorkspaceError("文稿格式或长度超出限制")
        kind = node["type"]
        out = {"type": kind}
        if kind == "text":
            value = str(node.get("text", ""))
            chars += len(value)
            if chars > 300000:
                raise WorkspaceError("文稿文字超出本次保存限制")
            if not value:
                return None
            out["text"] = value
            marks = []
            for mark in node.get("marks", []):
                if mark.get("type") in ("bold", "italic", "strike", "code", "underline"):
                    marks.append({"type": mark["type"]})
                if mark.get("type") == "link" and re.match(r"^https?://", str(mark.get("attrs", {}).get("href", "")), re.I):
                    marks.append({"type": "link", "attrs": {"href": mark["attrs"]["href"], "target": "_blank", "rel": "noreferrer noopener"}})
            if marks:
                out["marks"] = marks
        if kind == "heading":
            out["attrs"] = {"level": max(1, min(4, int(node.get("attrs", {}).get("level", 2))))}
        if kind == "citation":
            attrs = node.get("attrs", {})
            e = evidence.get(attrs.get("evidenceId"))
            if not e:
                raise WorkspaceError("文稿引用了项目中不存在的证据")
            out["attrs"] = {"evidenceId": e["id"], "sourceHash": str(attrs.get("sourceHash") or e["data"]["source_hash"]),
                "evidenceRevision": int(attrs.get("evidenceRevision") or e["revision"]), "label": e["data"].get("field", "证据")}
        if "content" in node:
            out["content"] = [c for child in node["content"] if (c := clean(child, depth + 1)) is not None]
        return out
    if not isinstance(content, dict) or content.get("type") != "doc":
        raise WorkspaceError("请提交有效的富文本文稿")
    result = clean(content)
    result.setdefault("content", [paragraph("")])
    return result


def references(store, pid, actor, content, style="numeric"):
    evidence = {r["id"]: r for r in store.items(pid, actor, "evidence")}
    papers = {r["id"]: r for r in store.items(pid, actor, "paper")}
    refs, citations = [], []
    for node in walk(content):
        if node.get("type") != "citation":
            continue
        attrs = node["attrs"]
        e = evidence.get(attrs.get("evidenceId"))
        if not e:
            citations.append({"evidence_id": attrs.get("evidenceId"), "valid": False, "reason": "证据已删除"})
            continue
        paper = papers[e["data"]["paper_id"]]
        ref = next((r for r in refs if r["paper_id"] == paper["id"]), None)
        if ref is None:
            d = paper["data"]
            author = "; ".join(d.get("authors", [])) or "作者未提供"
            year = str(d.get("year") or "年份未提供")
            ref = {"number": len(refs) + 1, "paper_id": paper["id"], "paper": d,
                "text": f"{author}. {paper['label']}. {year}." + (" " + d["venue"] + "." if d.get("venue") else "") + (" DOI: " + d["doi"] if d.get("doi") else ""),
                "label": f"({(d.get('authors') or ['作者未提供'])[0]}, {year})" if style == "author_year" else f"[{len(refs)+1}]"}
            refs.append(ref)
        valid = store.verify_evidence(pid, actor, e["id"])["valid"] and attrs.get("sourceHash") == e["data"]["source_hash"] and attrs.get("evidenceRevision") == e["revision"]
        citations.append({"evidence_id": e["id"], "number": ref["number"], "label": ref["label"], "valid": valid,
            "confirmed": bool(e["data"].get("confirmed_by")), "quote": e["data"]["quote"], "title": paper["label"], **e["data"]})
    return {"references": refs, "citations": citations}


def manuscript_view(store, pid, actor, item):
    result = copy.deepcopy(item)
    data = result["data"]
    template = data.get("template_snapshot") or resolve_template(store, pid, actor, data.get("template", "review"))
    refs = references(store, pid, actor, data["content"], data.get("citation_style", template["citation_style"]))
    labels = {c["evidence_id"]: c.get("label", "[引用失效]") for c in refs["citations"]}
    for n in walk(data["content"]):
        if n.get("type") == "citation":
            n["attrs"]["label"] = labels.get(n["attrs"]["evidenceId"], "[引用失效]")
    headers = [plain_text(n) for n in walk(data["content"]) if n.get("type") == "heading"]
    result["validation"] = {"missing_sections": [s for s in template["sections"] if s not in headers],
        "invalid_citations": sum(not c["valid"] for c in refs["citations"]), "unconfirmed_citations": sum(not c.get("confirmed") for c in refs["citations"]),
        "abstract_missing": not bool(data.get("abstract", "").strip()), "keywords_missing": not bool(data.get("keywords"))}
    abstract_count = len(data.get("abstract", "").split()) if template.get("abstract_unit") == "words" else len(data.get("abstract", ""))
    result["validation"].update(abstract_count=abstract_count, abstract_limit=template.get("abstract_limit", 0),
        abstract_over_limit=bool(template.get("abstract_limit") and abstract_count > template["abstract_limit"]),
        keywords_over_limit=len(data.get("keywords", [])) > template.get("keyword_limit", 20),
        citation_style_matches=data.get("citation_style", template["citation_style"]) == template["citation_style"])
    result["template"] = template
    result.update(refs)
    return result


def save_manuscript(store, pid, actor, data, mid=None, revision=None):
    old = store.item(pid, actor, mid, "manuscript") if mid else None
    if old and old["revision"] != revision:
        raise WorkspaceError("文稿已被其他成员更新，请保存本地副本后重新加载", 409)
    title = normalized(data.get("title") or (old["label"] if old else ""))
    if not title:
        raise WorkspaceError("请填写文稿标题")
    template_id = data.get("template", old["data"].get("template", "review") if old else "review")
    template = resolve_template(store, pid, actor, template_id)
    if data.get("citation_style", template["citation_style"]) not in ("numeric", "author_year"):
        raise WorkspaceError("未知引用格式")
    content = clean_content(store, pid, actor, data.get("content", old["data"]["content"] if old else {"type": "doc", "content": [paragraph("")]}))
    ids = sorted({n["attrs"]["evidenceId"] for n in walk(content) if n.get("type") == "citation"})
    clean = {**(old["data"] if old else {}), "title": title, "template": template_id, "template_snapshot": template, "citation_style": data.get("citation_style", template["citation_style"]),
        "content": content, "abstract": str(data.get("abstract", old["data"].get("abstract", "") if old else ""))[:20000],
        "keywords": [str(k)[:100] for k in data.get("keywords", old["data"].get("keywords", []) if old else [])][:20],
        "evidence_ids": ids, "generation_coverage": data.get("generation_coverage",old["data"].get("generation_coverage",{}) if old else {}), "generation_status": data.get("generation_status", old["data"].get("generation_status", "") if old else ""), "edited_by": actor, "generation_mode": data.get("generation_mode", old["data"].get("generation_mode", "researcher_authored") if old else "researcher_authored")}
    citations = references(store, pid, actor, content)["citations"]
    clean["stale"] = any(not c["valid"] for c in citations)
    saved = store.put(pid, actor, "manuscript", title, clean, mid, revision)
    return manuscript_view(store, pid, actor, saved)


def generate_manuscript(store, pid, actor, template_id="review", evidence_ids=None, *, model=None):
    p = store.project(pid, actor)
    with store.engine.connect() as conn:
        store._access(conn, pid, actor, edit=True)
    template = resolve_template(store, pid, actor, template_id)
    candidates = [e for e in store.items(pid, actor, "evidence") if e["data"].get("scope") != "title" and (not evidence_ids or e["id"] in evidence_ids) and store.verify_evidence(pid, actor, e["id"])["valid"]]
    candidates.sort(key=lambda e: 0 if e["data"].get("scope") == "fulltext" else 1)
    if not candidates:
        raise WorkspaceError("先在矩阵或原文中建立可核对的证据，再生成综述")
    from workspace.synthesis import generate_sections
    fields = {
        "研究方法比较": {"method", "population", "innovation"}, "相关研究": {"method", "finding", "innovation"},
        "方法": {"method", "population", "dataset", "sample_size"}, "数据与评价指标": {"dataset", "sample_size", "metrics"},
        "主要发现": {"finding", "metrics", "question_answer"}, "结果": {"finding", "metrics", "question_answer"},
        "局限性与研究空白": {"limitations"}, "讨论": {"limitations", "innovation"},
    }
    sections=[s for s in template["sections"] if s not in ("摘要","结论")]
    claims,generation,selected_sources=generate_sections(store,pid,actor,candidates,sections,p["query"] or p["title"],model=model)
    original_sections=sorted({c["section"] for c in claims})
    section_modes={};reused_sections=[]
    if claims:
        # Abstract/conclusion reuse verified analysis rather than spend another
        # request inventing a stronger conclusion from the same limited sources.
        for section in ("摘要","结论"):
            if section in template["sections"] and not any(c.get("section")==section for c in claims):
                originals=[c for c in claims if c.get("section") not in ("摘要","结论")][:3]
                claims.extend({**c,"section":section} for c in originals)
                reused_sections.append(section)
        nodes = [heading(p["title"] + "：研究综述", 1), paragraph("基于当前项目证据综合生成的初稿；摘要依据与全文依据分别保留，仍需研究者审阅。")]
        for section in template["sections"]:
            nodes.append(heading(section))
            selected = [c for c in claims if c.get("section") == section]
            section_modes[section]="reused_analysis" if section in reused_sections else "verified_model" if selected else "missing_evidence"
            if section in ("研究背景与范围","研究问题","引言") and not selected:
                nodes.append(paragraph("本稿研究问题："+(p["query"] or p["title"])+"。资料仅覆盖当前项目收集的文献，不能据此声称穷尽检索。"))
                section_modes[section]="project_context"
            elif not selected:
                nodes.append(paragraph("当前证据未形成经校验的该章节论述，以下原文依据供核对与补充，不能视为已完成综合分析。"))
                for source in selected_sources.get(section,[])[:3]:
                    e=source["evidence"]
                    nodes.append({"type":"paragraph","content":[text_node(source["text"]+" "),citation_node(e)]})
                    section_modes[section]="source_text"
            for claim in selected:
                content = [text_node(claim["text"] + " ")]
                for ref in claim["references"]:
                    content.append(citation_node(ref["source"]["evidence"]))
                nodes.append({"type": "paragraph", "content": content})
        if any(c.get("section") in template["sections"] for c in claims):
            return save_manuscript(store, pid, actor, {"title": p["title"] + "：研究综述", "template": template_id,
                "content": {"type": "doc", "content": nodes}, "generation_mode": "verified_model_synthesis", "generation_status": generation["status"],
                "generation_coverage":{"supported_sections":sorted({c["section"] for c in claims if c.get("section") in template["sections"]}),
                    "total_sections":len(template["sections"]),"original_sections":original_sections,"reused_sections":reused_sections,
                    "section_modes":section_modes,"missing_sections":generation["missing_sections"],"attempts":generation["attempts"]}})
    nodes = [heading(p["title"] + "：研究资料综述", 1), paragraph("证据整理草稿：引用内容来自项目原文。摘要依据、未核对片段与未覆盖章节需由研究者补充；不能据此推断未报告的实验。")]
    used = set()
    for section in template["sections"]:
        nodes.append(heading(section))
        chosen = [e for e in candidates if e["data"].get("field") in fields.get(section, set())][:30]
        if section in ("研究背景与范围", "研究问题", "引言"):
            nodes.append(paragraph("本稿研究问题：" + (p["query"] or p["title"]) + "。以下资料范围限于当前项目收集的文献，不代表穷尽检索。"))
        if section == "结论":
            chosen = [e for e in candidates if e["data"].get("field") == "finding"][:5]
        distinct, seen_quotes = [], set()
        for e in chosen:
            key = (e["data"]["paper_id"], normalized(e["data"]["quote"]))
            if key not in seen_quotes:
                distinct.append(e); seen_quotes.add(key)
        chosen = distinct
        if not chosen and section not in ("研究背景与范围", "研究问题", "引言"):
            nodes.append(paragraph("该章节尚缺可核对依据，请补充原文、提取证据或自行撰写并插入引用。"))
        for e in chosen:
            scope = f"全文第 {e['data']['page']} 页" if e["data"].get("scope") == "fulltext" else "摘要依据"
            nodes.append({"type": "paragraph", "content": [text_node(e["data"]["quote"] + " "), citation_node(e), text_node("（" + scope + "）")]})
            used.add(e["id"])
    # Custom evidence remains usable even if it did not match a default section.
    used_quotes = {(e["data"]["paper_id"], normalized(e["data"]["quote"])) for e in candidates if e["id"] in used}
    leftover = []
    for e in candidates:
        key = (e["data"]["paper_id"], normalized(e["data"]["quote"]))
        if key not in used_quotes:
            leftover.append(e); used_quotes.add(key)
    leftover = leftover[:20]
    if leftover:
        nodes.append(heading("补充研究证据"))
        for e in leftover:
            nodes.append({"type": "paragraph", "content": [text_node(e["data"]["quote"] + " "), citation_node(e)]})
    return save_manuscript(store, pid, actor, {"title": p["title"] + "：研究资料综述", "template": template_id, "content": {"type": "doc", "content": nodes}, "generation_mode": "verified_evidence_draft", "generation_status": generation["status"],
        "generation_coverage":{"supported_sections":[],"total_sections":len(template["sections"]),"original_sections":[],
            "reused_sections":[],"missing_sections":list(template["sections"]),"attempts":generation["attempts"]}})


def versions(store, pid, actor, mid):
    store.item(pid, actor, mid, "manuscript")
    return sorted([r for r in store.items(pid, actor, "manuscript_version") if r["data"]["manuscript_id"] == mid], key=lambda r: r["data"]["version"], reverse=True)


def restore_version(store, pid, actor, mid, vid, revision):
    v = store.item(pid, actor, vid, "manuscript_version")
    if v["data"]["manuscript_id"] != mid:
        raise WorkspaceError("版本不属于当前文稿")
    return save_manuscript(store, pid, actor, v["data"]["snapshot"], mid, revision)


def add_comment(store, pid, actor, mid, text, anchor=""):
    m = store.item(pid, actor, mid, "manuscript")
    if not text.strip() or len(text) > 5000:
        raise WorkspaceError("评论需为 1–5000 个字符")
    if anchor and anchor not in plain_text(m["data"]["content"]):
        raise WorkspaceError("评论选区已变化，请重新选择")
    return store.put(pid, actor, "comment", "文稿评论", {"manuscript_id": mid, "text": text, "anchor": anchor[:2000], "author": actor, "manuscript_revision": m["revision"]})


def export_blocks(view):
    labels = {c["evidence_id"]: c.get("label", "[引用失效]") for c in view["citations"]}
    papers = {c["evidence_id"]: c.get("paper_id",c["evidence_id"]) for c in view["citations"]}
    def inline(node, adjacent=None):
        if adjacent is None:adjacent=set()
        if node["type"] == "citation":
            # Several passages may support one statement from the same paper.
            # Keep every evidence dependency/record, display its citation once.
            paper=papers.get(node["attrs"]["evidenceId"])
            if paper in adjacent:return ""
            adjacent.add(paper)
            return labels.get(node["attrs"]["evidenceId"], "[引用失效]")
        if node["type"] == "hardBreak":
            adjacent.clear()
            return "\n"
        if node.get("text","").strip():adjacent.clear()
        return node.get("text", "") + "".join(inline(c,adjacent) for c in node.get("content", []))
    blocks = []
    def collect(node):
        kind = node["type"]
        if kind in ("paragraph", "heading", "codeBlock"):
            blocks.append({"kind": kind, "level": node.get("attrs", {}).get("level", 0), "text": inline(node)})
        else:
            for c in node.get("content", []): collect(c)
    collect(view["data"]["content"])
    blocks.append({"kind": "heading", "level": 2, "text": "参考文献"})
    blocks.extend({"kind": "paragraph", "text": f"[{r['number']}] {r['text']}"} for r in view["references"])
    blocks.append({"kind": "heading", "level": 2, "text": "证据核对记录"})
    blocks.append({"kind": "paragraph", "text": "导出版本仍需研究者审阅。" + ("存在已变化的来源引用，请重新核对。" if view["validation"]["invalid_citations"] else "")})
    seen = set()
    for c in view["citations"]:
        if c["evidence_id"] in seen: continue
        seen.add(c["evidence_id"])
        blocks.append({"kind": "paragraph", "text": f"{c.get('label', '')} {c.get('title', '')} · " + (f"原文第 {c['page']} 页" if c.get("page") else "摘要依据") + f" · {'已核对' if c.get('confirmed') else '待人工核对'}\n{c.get('quote', '')}"})
    return blocks


def export_manuscript(store, pid, actor, mid, fmt):
    view = manuscript_view(store, pid, actor, store.item(pid, actor, mid, "manuscript"))
    blocks = export_blocks(view)
    template = view["template"]
    if fmt == "md":
        value = "\n\n".join(("#" * b["level"] + " " if b["kind"] == "heading" else "") + b["text"] for b in blocks)
        return value.encode(), "text/markdown;charset=utf-8"
    if fmt == "docx":
        from docx import Document
        from docx.shared import Pt, Mm
        from docx.oxml.ns import qn
        doc = Document()
        style = doc.styles["Normal"]
        style.font.name = template.get("font", "Arial")
        style.font.size = Pt(template.get("font_size", 11))
        section = doc.sections[0]
        section.page_width, section.page_height = (Mm(210), Mm(297)) if template.get("paper_size", "A4") == "A4" else (Mm(215.9), Mm(279.4))
        section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = Mm(template.get("margin_mm", 25.4))
        fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        fonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        for b in blocks:
            if b["kind"] == "heading": doc.add_heading(b["text"], level=min(4, b["level"]))
            else: doc.add_paragraph(b["text"])
        output = io.BytesIO(); doc.save(output)
        return output.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if fmt == "pdf":
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4, letter
        from reportlab.lib.units import mm
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_size = template.get("font_size", 11)
        normal = ParagraphStyle("Research", fontName="STSong-Light", fontSize=font_size, leading=font_size * 1.8, wordWrap="CJK", alignment=TA_LEFT)
        title = ParagraphStyle("ResearchHeading", parent=normal, fontSize=15, leading=24, spaceBefore=12, spaceAfter=8)
        output = io.BytesIO()
        flow = []
        for b in blocks:
            flow.append(Paragraph(escape(b["text"]).replace("\n", "<br/>"), title if b["kind"] == "heading" else normal)); flow.append(Spacer(1, 6))
        margin = template.get("margin_mm", 25.4) * mm
        SimpleDocTemplate(output, title=view["label"], pagesize=A4 if template.get("paper_size", "A4") == "A4" else letter,
            leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin).build(flow)
        return output.getvalue(), "application/pdf"
    raise WorkspaceError("支持导出 Markdown、DOCX、PDF")
