"""Editable research slides with project-scoped evidence and bounded exports."""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import tempfile
from html import escape
from pathlib import Path

from workspace.store import WorkspaceError, ident, normalized

THEMES = [
    {"id": "atelier", "name": "暖纸与珊瑚", "background": "EFE7D2", "surface": "F6F0E3", "ink": "171710", "accent": "EF6F5C", "font": "Arial", "heading_font": "Georgia"},
    {"id": "formal", "name": "清晰学术", "background": "FFFFFF", "surface": "F3F4F5", "ink": "20242C", "accent": "365B7A", "font": "Arial", "heading_font": "Arial"},
]
PURPOSES = {"meeting": "研究组会", "proposal": "开题报告", "defense": "研究答辩", "explain": "论文讲解"}
SECTIONS = [
    ("研究问题", []), ("资料范围", []), ("研究方法", ["method", "population"]), ("数据来源与规模", ["dataset", "sample_size"]),
    ("评价指标", ["metrics"]), ("主要发现", ["finding", "question_answer"]), ("研究贡献", ["innovation"]),
    ("局限性与边界", ["limitations"]), ("方法比较", ["method", "metrics"]), ("讨论与下一步", ["limitations"]), ("参考文献", []),
]


def clean_theme(theme):
    out = {"id": "custom", "name": str(theme.get("name", "项目品牌"))[:100]}
    for k in ("background", "surface", "ink", "accent"):
        value = str(theme.get(k, THEMES[0][k])).lstrip("#")
        if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
            raise WorkspaceError("品牌颜色需为六位十六进制颜色")
        out[k] = value.upper()
    for k in ("font", "heading_font"):
        value = str(theme.get(k, THEMES[0][k]))
        if not re.fullmatch(r"[\w .-]{1,100}", value):
            raise WorkspaceError("字体名称格式无效")
        out[k] = value
    return out


def set_brand(store, pid, actor, data, revision):
    p = store.project(pid, actor)
    theme = clean_theme(data)
    store.update_project(pid, actor, {"settings": {**p["settings"], "presentation_brand": theme}}, revision)
    return theme


def bullet_refs(bullet):
    return bullet.get("evidence_refs") or ([bullet] if bullet.get("evidence_id") else [])


def clean_slides(store, pid, actor, slides):
    if not isinstance(slides, list) or not 1 <= len(slides) <= 80:
        raise WorkspaceError("演示文稿需为 1–80 页")
    evidence = {r["id"]: r for r in store.items(pid, actor, "evidence")}
    result, ids = [], set()
    for slide in slides:
        sid = str(slide.get("id") or ident())
        if sid in ids:
            raise WorkspaceError("页面标识不能重复")
        ids.add(sid)
        layout = slide.get("layout", "content")
        if layout not in ("title", "content", "two_column", "chart"):
            raise WorkspaceError("未知页面布局")
        bullets = []
        for bullet in slide.get("bullets", [])[:12]:
            text = str(bullet.get("text", ""))[:3000]
            if not text.strip(): continue
            eid = bullet.get("evidence_id")
            b = {"text": text}
            refs=bullet.get("evidence_refs",[])
            if not isinstance(refs,list) or len(refs)>6 or any(not isinstance(r,dict) for r in refs):
                raise WorkspaceError("每条要点最多引用六条项目证据")
            refs=list(refs)
            if eid and not any(r.get("evidence_id")==eid for r in refs):refs.insert(0,bullet)
            if len(refs)>6:raise WorkspaceError("每条要点最多引用六条项目证据")
            linked=[];seen=set()
            for ref in refs:
                rid=ref.get("evidence_id")
                if not isinstance(rid,str):raise WorkspaceError("演示引用需要有效的项目证据标识")
                e = evidence.get(rid)
                if not e:
                    raise WorkspaceError("演示页面引用了当前项目以外的证据")
                if rid in seen:continue
                seen.add(rid)
                try:revision=int(ref.get("evidence_revision") or e["revision"])
                except (ValueError,TypeError):raise WorkspaceError("演示引用版本格式无效") from None
                linked.append({"evidence_id":rid,"source_hash":str(ref.get("source_hash") or e["data"]["source_hash"]),
                    "evidence_revision":revision})
            if linked:
                b.update(linked[0],evidence_refs=linked,
                    value_status="extract" if any(normalized(text).rstrip("…") in normalized(evidence[r["evidence_id"]]["data"]["quote"]) for r in linked) else "researcher_interpretation")
            bullets.append(b)
        chart_id = slide.get("chart_id")
        chart_revision = None
        if chart_id:
            chart = store.item(pid, actor, chart_id, "chart")
            chart_revision = slide.get("chart_revision") or chart["revision"]
        result.append({"id": sid, "title": str(slide.get("title", "未命名页面"))[:500], "subtitle": str(slide.get("subtitle", ""))[:2000],
            "layout": layout, "bullets": bullets, "notes": str(slide.get("notes", ""))[:20000], "chart_id": chart_id, "chart_revision": chart_revision})
    return result


def deck_view(store, pid, actor, item):
    view = copy.deepcopy(item)
    evidence = {r["id"]: r for r in store.items(pid, actor, "evidence")}
    papers = {r["id"]: r for r in store.items(pid, actor, "paper")}
    citations, refs = {}, []
    invalid_charts = 0
    for slide in view["data"]["slides"]:
        slide["citations"] = []
        holders = [ref for b in slide["bullets"] for ref in bullet_refs(b)]
        if slide.get("chart_id"):
            chart = store.item(pid, actor, slide["chart_id"], "chart")
            slide["chart"] = chart["data"]
            invalid_charts += chart["revision"] != slide.get("chart_revision") or bool(chart["data"].get("stale"))
            for series in chart["data"].get("series", []):
                holders.extend(s for s in series.get("sources", []) if s)
        for b in holders:
            eid = b.get("evidence_id")
            if not eid: continue
            e = evidence.get(eid)
            if not e:
                c = {"evidence_id": eid, "valid": False, "confirmed": False, "quote": "证据已删除"}
                citations[eid] = c; slide["citations"].append(c); continue
            d = e["data"]; paper = papers[d["paper_id"]]
            ref = next((r for r in refs if r["paper_id"] == paper["id"]), None)
            if ref is None:
                ref = {"number": len(refs)+1, "paper_id": paper["id"], "title": paper["label"], "authors": paper["data"].get("authors", []), "year": paper["data"].get("year"), "doi": paper["data"].get("doi")}
                refs.append(ref)
            valid = store.verify_evidence(pid, actor, eid)["valid"] and b["source_hash"] == d["source_hash"] and b["evidence_revision"] == e["revision"]
            c = {"evidence_id": eid, "number": ref["number"], "title": paper["label"], "valid": valid, "confirmed": bool(d.get("confirmed_by")), **d}
            previous=citations.get(eid)
            citations[eid] = {**c,"valid":valid and (previous is None or previous["valid"])}
            slide["citations"].append(c)
    view["citations"] = list(citations.values()); view["references"] = refs
    view["validation"] = {"invalid_citations": sum(not c["valid"] for c in citations.values()), "invalid_charts": invalid_charts, "unconfirmed_citations": sum(not c["confirmed"] for c in citations.values()),
        "empty_slides": sum(not s["title"].strip() or not s["bullets"] and s["layout"] != "title" for s in view["data"]["slides"])}
    return view


def save_deck(store, pid, actor, data, did=None, revision=None):
    old = store.item(pid, actor, did, "presentation") if did else None
    if old and old["revision"] != revision:
        raise WorkspaceError("演示文稿已被其他成员更新，请导出本地副本后重新加载", 409)
    title = normalized(data.get("title") or (old["label"] if old else ""))
    if not title:
        raise WorkspaceError("演示文稿需有标题")
    slides = clean_slides(store, pid, actor, data.get("slides", old["data"]["slides"] if old else []))
    theme = clean_theme(data.get("theme", old["data"]["theme"] if old else THEMES[0]))
    ids = sorted({r["evidence_id"] for s in slides for b in s["bullets"] for r in bullet_refs(b)})
    # Chart evidence remains a dependency when reused in a deck.
    for s in slides:
        if s.get("chart_id"):
            ids.extend(store.item(pid, actor, s["chart_id"], "chart")["data"].get("evidence_ids", []))
    clean = {"title": title, "slides": slides, "theme": theme, "purpose": data.get("purpose", old["data"].get("purpose", "meeting") if old else "meeting"),
        "generation_coverage": data.get("generation_coverage",old["data"].get("generation_coverage",{}) if old else {}), "generation_status": data.get("generation_status", old["data"].get("generation_status", "") if old else ""), "evidence_ids": sorted(set(ids)), "chart_ids": sorted({s["chart_id"] for s in slides if s.get("chart_id")}), "edited_by": actor, "generation_mode": data.get("generation_mode", old["data"].get("generation_mode", "researcher_authored") if old else "researcher_authored")}
    view = deck_view(store, pid, actor, {"data": clean})
    clean["stale"] = bool(view["validation"]["invalid_citations"] or view["validation"]["invalid_charts"])
    return deck_view(store, pid, actor, store.put(pid, actor, "presentation", title, clean, did, revision))


def generate_deck(store, pid, actor, purpose="meeting", evidence_ids=None, *, model=None):
    p = store.project(pid, actor)
    if purpose not in PURPOSES:
        raise WorkspaceError("未知演示用途")
    with store.engine.connect() as conn:
        store._access(conn, pid, actor, edit=True)
    candidates = [e for e in store.items(pid, actor, "evidence") if e["data"].get("scope") != "title" and (not evidence_ids or e["id"] in evidence_ids) and store.verify_evidence(pid, actor, e["id"])["valid"]]
    if not candidates:
        raise WorkspaceError("先提取或保存项目原文证据，再生成演示文稿")
    papers = store.items(pid, actor, "paper")
    from workspace.synthesis import generate_sections
    content_sections=[s[0] for s in SECTIONS if s[1]]
    claims,generation,selected_sources=generate_sections(store,pid,actor,candidates,content_sections,p["query"] or p["title"],model=model,purpose="presentation")
    slides = [{"id": ident(), "title": p["title"], "subtitle": PURPOSES[purpose], "layout": "title", "bullets": [], "notes": "基于项目实际资料组织的证据草稿，请研究者核对后用于报告。"}]
    synthesized = False
    synthesized_sections = []
    section_modes={}
    for title, fields in SECTIONS:
        matches = [r["evidence"] for r in selected_sources.get(title,[])[:4]]
        bullets = [{"text": e["data"]["quote"][:320] + ("…" if len(e["data"]["quote"]) > 320 else ""), "evidence_id": e["id"], "source_hash": e["data"]["source_hash"], "evidence_revision": e["revision"]} for e in matches]
        generated = [c for c in claims if c.get("section") == title][:4]
        section_modes[title]="source_text" if bullets else "missing_evidence"
        if generated and title not in ("研究问题", "资料范围", "参考文献"):
            synthesized = True
            synthesized_sections.append(title)
            section_modes[title]="verified_model"
            bullets = []
            for c in generated:
                refs=[r["source"]["evidence"] for r in c["references"]]
                bullets.append({"text": c["text"][:600],"evidence_refs":[{"evidence_id":e["id"],"source_hash":e["data"]["source_hash"],"evidence_revision":e["revision"]} for e in refs]})
        if title == "研究问题": bullets = [{"text": p["query"] or p["title"]}]
        if title == "资料范围": bullets = [{"text": f"当前项目保存 {len(papers)} 篇文献、{len(candidates)} 条可核对证据。资料范围限于当前收集结果。"}, {"text": "摘要依据与全文依据分别标记；未获取全文时不推断正文结论。"}]
        if title == "参考文献": bullets = [{"text": r["label"] + (" · " + str(r["data"]["year"]) if r["data"].get("year") else "") + (" · DOI " + r["data"]["doi"] if r["data"].get("doi") else "")} for r in papers[:10]]
        if not fields:section_modes[title]="project_context"
        elif not generated and bullets:bullets.insert(0,{"text":"以下为原文依据，尚未形成通过核对的 AI 综合要点。"})
        if not bullets: bullets = [{"text": "当前资料缺少该章节的可核对依据，请补充原文证据或研究者论证。"}]
        slides.append({"id": ident(), "title": title, "layout": "two_column" if title == "方法比较" else "content", "bullets": bullets,
            "notes": "引用文字为项目原文摘录；概括、解释及下一步研究计划需人工确认。"})
    return save_deck(store, pid, actor, {"title": p["title"] + " · " + PURPOSES[purpose], "purpose": purpose, "slides": slides,
        "theme": p["settings"].get("presentation_brand", THEMES[0]), "generation_mode": "verified_model_synthesis" if synthesized else "verified_evidence_outline",
        "generation_status": generation["status"],"generation_coverage":{"supported_sections":synthesized_sections,"total_sections":len(SECTIONS),
            "synthesis_sections":content_sections,"structural_sections":[s[0] for s in SECTIONS if not s[1]],"section_modes":section_modes,
            "missing_sections":generation["missing_sections"],"attempts":generation["attempts"]}})


def export_deck(store, pid, actor, did, fmt):
    view = deck_view(store, pid, actor, store.item(pid, actor, did, "presentation"))
    if fmt == "pptx":
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="scholarscope-slides-") as tmp:
            source = Path(tmp) / "deck.json"; output = Path(tmp) / "research.pptx"
            source.write_text(json.dumps(view, ensure_ascii=False))
            try:
                process = subprocess.run([os.getenv("SCHOLARSCOPE_NODE", "node"), str(repo / "scripts" / "render_presentation.mjs"), str(source), str(output)],
                    cwd=repo, capture_output=True, timeout=40)
                if process.returncode or not output.exists(): raise WorkspaceError("可编辑 PPTX 生成失败，请检查本地构建依赖", 503)
                return output.read_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            except (subprocess.TimeoutExpired, OSError):
                raise WorkspaceError("演示文稿导出暂不可用，可先导出 Markdown", 503) from None
    if fmt == "md":
        blocks = []
        for i, s in enumerate(view["data"]["slides"], 1):
            blocks.append(f"# {i}. {s['title']}\n\n" + "\n".join("- " + b["text"] for b in s["bullets"]) + "\n\n" + s["notes"] + "\n" + "\n".join(f"[{c.get('number','?')}] {c.get('title','')} · " + (f"第 {c['page']} 页" if c.get("page") else "摘要依据") + f"\n{c.get('quote', '')}" for c in s["citations"]))
        return "\n\n---\n\n".join(blocks).encode(), "text/markdown;charset=utf-8"
    if fmt == "html":
        t = view["data"]["theme"]
        sections = []
        for i, s in enumerate(view["data"]["slides"]):
            sections.append(f'<section class="slide" data-page="{i}"><small>{i+1} / {len(view["data"]["slides"])}</small><h1>{escape(s["title"])}</h1><p>{escape(s["subtitle"])}</p><ul>' + "".join("<li>" + escape(b["text"]) + "</li>" for b in s["bullets"]) + "</ul><footer>" + " · ".join(f'[{c.get("number", "?")}] {escape(c.get("title", ""))}' for c in s["citations"]) + "</footer></section>")
        html = f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(view["label"])}</title><style>body{{margin:0;background:#{t["background"]};color:#{t["ink"]};font-family:"{t["font"]}",sans-serif}}.slide{{min-height:80vh;box-sizing:border-box;padding:6vw;display:none}}.slide.active{{display:block}}h1{{font-size:clamp(26px,4vw,54px)}}li{{font-size:clamp(18px,2vw,30px);line-height:1.8;margin:16px 0}}footer,small{{font-size:12px}}nav{{position:fixed;bottom:16px;right:16px;display:flex;gap:12px}}button{{padding:12px 20px;border:1px solid currentColor;background:#{t["surface"]};color:inherit}}@media print{{.slide{{display:block;break-after:page}}nav{{display:none}}}}</style><main>' + "".join(sections) + '</main><nav><button id="prev">上一页</button><button id="next">下一页</button></nav><script>let page=0;const slides=[...document.querySelectorAll(".slide")];function show(n){page=Math.max(0,Math.min(slides.length-1,n));slides.forEach((s,i)=>s.classList.toggle("active",i===page));document.querySelector("#prev").disabled=page===0;document.querySelector("#next").disabled=page===slides.length-1}document.querySelector("#prev").onclick=()=>show(page-1);document.querySelector("#next").onclick=()=>show(page+1);document.addEventListener("keydown",e=>{if(e.key==="ArrowRight")show(page+1);if(e.key==="ArrowLeft")show(page-1)});show(0)</script></html>'
        return html.encode(), "text/html;charset=utf-8"
    raise WorkspaceError("支持导出 PPTX、Markdown、离线网页幻灯片")
