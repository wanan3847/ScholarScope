"""Evidence-first extraction, question answering, and screening decisions."""
from __future__ import annotations

import re
from collections import Counter

from workspace.knowledge import ProjectIndex, sources, terms
from workspace.store import WorkspaceError, normalized

DEFAULT_COLUMNS = [
    {"id": "method", "label": "研究方法", "description": "model method algorithm 模型 方法 算法"},
    {"id": "population", "label": "研究对象", "description": "population participants well logs molecules 研究对象 测井曲线"},
    {"id": "dataset", "label": "数据集", "description": "dataset training data benchmark 数据集 数据来源"},
    {"id": "sample_size", "label": "样本规模", "description": "samples participants wells observations 样本 规模 数量"},
    {"id": "metrics", "label": "评价指标", "description": "accuracy RMSE MAE MSE R2 F1 指标 误差"},
    {"id": "finding", "label": "主要结论", "description": "results findings demonstrate show 结果 结论"},
    {"id": "innovation", "label": "创新点", "description": "propose introduce novel contribution 创新 提出"},
    {"id": "limitations", "label": "局限性", "description": "limitations limited however future work 局限 不足"},
]
PATTERNS = {
    "method": r"neural network|deep learning|transformer|\bLSTM\b|\bCNN\b|random forest|support vector|\bmodel\b|\balgorithm\b|神经网络|深度学习|模型|算法",
    "population": r"well logs?|permeability|porosity|molecul|patients?|participants?|测井|孔隙|渗透|分子|患者|研究对象",
    "dataset": r"dataset|data set|benchmark|training data|数据库|数据集|数据来源",
    "sample_size": r"\d[\d,.]*\s*(?:samples?|participants?|patients?|wells?|observations?|例|人|个样本|口井)|样本(?:数|规模|量)",
    "metrics": r"\b(?:RMSE|MAE|MSE|R2|R²|F1|AUC|accuracy|precision|recall)\b|准确率|误差|召回|评价指标",
    "finding": r"results?|findings?|demonstrate|\bshow\b|achiev|结果|表明|发现|结论",
    "innovation": r"propose|introduce|novel|contribution|创新|首次|提出",
    "limitations": r"limitation|limited|however|future work|局限|不足|未来工作|尚未",
}


def sentences(value):
    return [s.strip() for s in re.split(r"(?<=[.!?。；;])\s+|\n+", str(value)) if 5 <= len(s.strip()) <= 3000]


def source_sentences(store, pid, actor, paper_id):
    paper = store.item(pid, actor, paper_id, "paper")
    rows = []
    # Preserve real paragraph/line boundaries: chapter headings are not findings.
    for doc in store.items(pid, actor, "document"):
        if doc["data"].get("paper_id") != paper_id: continue
        for page in doc["data"].get("pages", []):
            rows.append({"text": page.get("text", ""), "source": {"paper_id": paper_id, "document_id": doc["id"], "page": page["number"], "scope": "fulltext", "title": paper["label"]}})
    rows.append({"text": paper["data"].get("abstract", ""), "source": {"paper_id": paper_id, "scope": "abstract", "title": paper["label"]}})
    found = []
    seen = set()
    for r in rows:
        if r["source"]["paper_id"] != paper_id or r["source"]["scope"] == "title":
            continue
        for sentence in sentences(r["text"]):
            if re.fullmatch(r"(?:\d+[.\s]*)?(?:methods?|results?|discussion|conclusions?|introduction|references|方法|结果|讨论|结论|引言|参考文献)[.\s]*", sentence, re.I):
                continue
            if sentence not in seen:
                found.append((sentence, r["source"]))
                seen.add(sentence)
    return found


def ensure_evidence(store, pid, actor, paper_id, field, quote, source, value=None):
    old = next((e for e in store.items(pid, actor, "evidence") if e["data"].get("paper_id") == paper_id
        and e["data"].get("field") == field and normalized(e["data"].get("quote")) == normalized(quote)
        and (value is None or e["data"].get("value") == value)
        and e["data"].get("document_id") == source.get("document_id") and e["data"].get("page") == source.get("page")), None)
    if old and store.verify_evidence(pid, actor, old["id"])["valid"]:
        return old
    data = {"paper_id": paper_id, "field": field, "quote": quote, "value": value or quote,
            **{k: source[k] for k in ("document_id", "page", "scope") if k in source}}
    return store.add_evidence(pid, actor, data, old["id"] if old else None, old["revision"] if old else None)


def matrix(store, pid, actor):
    p = store.project(pid, actor)
    columns = p["settings"].get("matrix_columns", DEFAULT_COLUMNS)
    cells = store.items(pid, actor, "matrix_cell")
    evidence = {e["id"]: e for e in store.items(pid, actor, "evidence")}
    rows = []
    for paper in store.items(pid, actor, "paper"):
        selected = {}
        for col in columns:
            cell = next((c for c in cells if c["data"].get("paper_id") == paper["id"] and c["data"].get("column_id") == col["id"]), None)
            data = cell["data"] if cell else {"value": None, "status": "not_extracted"}
            e = evidence.get(data.get("evidence_id"))
            selected[col["id"]] = {**data, "id": cell["id"] if cell else None, "revision": cell["revision"] if cell else None,
                "evidence": e, "source_valid": store.verify_evidence(pid, actor, e["id"])["valid"] if e else None}
        rows.append({"paper": paper, "cells": selected})
    return {"columns": columns, "rows": rows, "project_revision": p["revision"]}


def set_columns(store, pid, actor, columns, revision):
    if not 1 <= len(columns) <= 24:
        raise WorkspaceError("矩阵需为 1–24 个字段")
    clean, keys = [], set()
    for c in columns:
        key = c.get("id", "")
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", key) or key in keys:
            raise WorkspaceError("字段标识需唯一，只能包含字母、数字、下划线和短横线")
        if not c.get("label", "").strip():
            raise WorkspaceError("请填写字段名称")
        keys.add(key)
        clean.append({"id": key, "label": c["label"][:100], "description": c.get("description", c["label"])[:500]})
    p = store.project(pid, actor)
    store.update_project(pid, actor, {"settings": {**p["settings"], "matrix_columns": clean}}, revision)
    return matrix(store, pid, actor)


def extract_matrix(store, pid, actor, paper_ids=None, column_ids=None, *, model=None):
    # All writes are protected before doing any expensive extraction.
    with store.engine.connect() as conn:
        store._access(conn, pid, actor, edit=True)
    p = store.project(pid, actor)
    columns = [c for c in p["settings"].get("matrix_columns", DEFAULT_COLUMNS) if not column_ids or c["id"] in column_ids]
    papers = [r for r in store.items(pid, actor, "paper") if not paper_ids or r["id"] in paper_ids]
    if len(papers) > 100:
        raise WorkspaceError("本次批量提取限 100 篇，请分批选择")
    existing = store.items(pid, actor, "matrix_cell")
    from workspace.intelligence import ResearchModel
    intelligence = ResearchModel(model, budget=180)
    for paper in papers:
        candidates = source_sentences(store, pid, actor, paper["id"])
        # Samples come from actual paragraphs/pages, distributed across requested
        # fields; this avoids a first-page-only or first-keyword-only model view.
        ranked = sorted(candidates, key=lambda pair: sum(bool(re.search(PATTERNS.get(c['id'], re.escape(c['label'])), pair[0], re.I)) for c in columns), reverse=True)
        source_rows = [{"text": quote, "title": paper["label"], "paper_id": paper["id"], **location} for quote, location in ranked[:40]]
        claims = intelligence.claims("Extract these fields from this paper, with a concise Chinese value per field. "
            "Return field equal to its exact id. Keep experimental units, population, split and conditions. "
            "Do not substitute vague related text for a missing value. Return at most ONE claim per field. "
            "Method means the actual algorithm/design; findings mean reported outcomes, not study objectives. "
            "Dataset means actual input data or dataset name, not a list of baseline algorithms. "
            "Limitations must be acknowledged limitations of this specific study, not unrelated prior work.",
            source_rows, context={"fields": columns,"field_definitions": {
                "method":"Actual algorithm and study design","finding":"Reported outcomes, not objectives or proposals",
                "dataset":"Actual dataset name/type, not baseline methods","limitations":"This study's acknowledged limits, not prior work or missing project material"}}, limit=len(columns)) if intelligence.model else []
        for col in columns:
            key = col["id"]
            pattern = PATTERNS.get(key)
            matching = [(s, src) for s, src in candidates if pattern and re.search(pattern, s, re.I)]
            if not pattern:
                wanted = set(terms(col["description"] + " " + col["label"]))
                matching = [(s, src) for s, src in candidates if len(wanted & set(terms(s))) >= max(1, min(2, len(wanted)))]
            e = None
            claim = next((c for c in claims if c.get("field") == key), None)
            if claim:
                ref = claim["references"][0]
                e = ensure_evidence(store, pid, actor, paper["id"], key, ref["quote"], ref["source"], claim["text"])
            elif matching:
                quote, source = matching[0]
                value = quote
                if key == "sample_size":
                    n = re.search(PATTERNS[key], quote, re.I)
                    value = n.group() if n else quote
                e = ensure_evidence(store, pid, actor, paper["id"], key, quote, source, value)
            data = {"paper_id": paper["id"], "column_id": key, "value": e["data"]["value"] if e else None,
                    "evidence_id": e["id"] if e else None, "status": "extracted" if e else "not_reported",
                    "extraction_mode": "verified_model" if claim else "source_text", "comment": "",
                    "generation_status": "verified_synthesis" if claim else intelligence.status}
            old = next((c for c in existing if c["data"].get("paper_id") == paper["id"] and c["data"].get("column_id") == key), None)
            # A batch rerun does not erase a researcher's manually reviewed cell.
            if old and old["data"].get("manual"):
                continue
            store.put(pid, actor, "matrix_cell", col["label"], data, old["id"] if old else None, old["revision"] if old else None)
    return matrix(store, pid, actor)


def edit_cell(store, pid, actor, cell_id, data, revision):
    old = store.item(pid, actor, cell_id, "matrix_cell")
    if revision != old["revision"]:
        raise WorkspaceError("内容已被其他成员更新，请重新加载后编辑", 409)
    if not data.get("quote"):
        raise WorkspaceError("修改提取值时必须提供可核对的原文片段")
    e = ensure_evidence(store, pid, actor, old["data"]["paper_id"], old["data"]["column_id"], data["quote"], data,
                        data.get("value") or data["quote"])
    # Update the evidence value even when reusing an existing source quote.
    if e["data"]["value"] != (data.get("value") or data["quote"]) or bool(e["data"].get("confirmed_by")) != bool(data.get("confirmed")):
        e = store.add_evidence(pid, actor, {**e["data"], **data, "paper_id": old["data"]["paper_id"],
            "field": old["data"]["column_id"]}, e["id"], e["revision"])
    return store.put(pid, actor, "matrix_cell", old["label"], {**old["data"], "value": e["data"]["value"],
        "evidence_id": e["id"], "status": "reviewed" if data.get("confirmed") else "extracted",
        "comment": str(data.get("comment", ""))[:5000], "manual": True}, cell_id, revision)


def answer_question(store, pid, actor, question, paper_ids=None, *, model=None):
    editable = store.project(pid, actor)["role"] != "viewer"
    passages = ProjectIndex(store).retrieve(pid, actor, question, limit=12, paper_ids=paper_ids)
    if not passages["passages"]:
        return {"question": question, "mode": passages["mode"], "answer": "项目资料中没有找到足够依据。请补充相关原文或换一个更具体的问题。", "citations": [], "evidence_ids": []}
    query_terms = set(terms(question))
    chosen, seen = [], set()
    for passage in passages["passages"]:
        if passage["scope"] == "title":
            continue
        if passage["scope"] == "fulltext":
            candidates = [s for s, src in source_sentences(store, pid, actor, passage["paper_id"]) if src.get("document_id") == passage.get("document_id") and src.get("page") == passage.get("page") and normalized(s) in passage["text"]]
        else:
            # Retrieval chunks may begin mid-sentence; quote complete source sentences.
            candidates = [s for s, src in source_sentences(store, pid, actor, passage["paper_id"]) if src.get("scope") == passage["scope"]]
        candidates = [s for s in candidates if len(s.strip()) >= 25]
        candidates.sort(key=lambda s: len(query_terms & set(terms(s))) +
            (2 if re.search(r"we (?:propose|evaluate|train|use)|this study|results? (?:show|reveal)|was evaluated|validation|blind well|本研究|本文|结果表明",s,re.I) else 0), reverse=True)
        for quote in candidates[:4]:
            key = (passage["paper_id"], quote)
            if key not in seen:
                chosen.append((quote, passage))
                seen.add(key)
    chosen = chosen[:8]
    if not chosen:
        return {"question": question, "mode": "title_only", "answer": "仅检索到标题，无法据此回答研究结论。请补充摘要或全文。", "citations": [], "evidence_ids": []}
    citations, blocks = [], []
    for i, (quote, source) in enumerate(chosen, 1):
        e = ensure_evidence(store, pid, actor, source["paper_id"], "question_answer", quote, source) if editable else None
        citations.append({"number": i, "evidence_id": e["id"] if e else None, "quote": quote, **source})
        where = f"原文第 {source['page']} 页" if source.get("page") else "摘要依据"
        blocks.append(f"[{i}] {quote}\n来源：{source['title']}，{where}。")
    result = {"question": question, "mode": "evidence_excerpts_" + passages["mode"],
              "answer": "以下是与问题相关的可核对原文；原文未报告的信息不能推断：\n\n" + "\n\n".join(blocks),
              "citations": citations, "evidence_ids": [c["evidence_id"] for c in citations if c["evidence_id"]], "stale": False}
    from workspace.intelligence import ResearchModel
    intelligence = ResearchModel(model)
    source_rows = [{**source, "text": quote} for quote, source in chosen]
    claims = intelligence.claims("Answer the research question in 2-3 specific statements when supported, covering the supplied studies. "
        "Use study-specific language, never generalize one paper to an entire field. Compare methods, "
        "conditions and conflicting findings across studies when supported. Do not merely list quotes. "
        "State uncertainty and distinguish proposed research from reported findings. Question: " + question,
        source_rows, context={"question":question}, limit=3) if intelligence.model else []
    if claims:
        citations, lines, evidence_ids = [], [], []
        for claim in claims:
            refs = []
            for ref in claim["references"]:
                source = ref["source"]
                e = ensure_evidence(store, pid, actor, source["paper_id"], "question_answer", ref["quote"], source) if editable else None
                n = len(citations)+1
                citations.append({"number": n, "evidence_id": e["id"] if e else None, "quote": ref["quote"], **source})
                if e: evidence_ids.append(e["id"])
                refs.append(f"[{n}]")
            lines.append(claim["text"] + " " + "".join(refs))
        result.update(answer="\n\n".join(lines), mode="verified_synthesis_" + passages["mode"], citations=citations, evidence_ids=list(set(evidence_ids)))
    result["generation_status"] = intelligence.status
    return store.put(pid, actor, "answer", question[:500], result) if editable else result


def set_screening_criteria(store, pid, actor, data, revision):
    p = store.project(pid, actor)
    reviewers = data.get("reviewers", 2)
    if reviewers not in (1, 2):
        raise WorkspaceError("筛选需设置一位或两位审阅者")
    criteria = {"include": str(data.get("include", ""))[:10000], "exclude": str(data.get("exclude", ""))[:10000], "reviewers": reviewers}
    store.update_project(pid, actor, {"settings": {**p["settings"], "screening_criteria": criteria}}, revision)
    return screening(store, pid, actor)


def suggest_screening(store,pid,actor,*,model=None):
    with store.engine.connect() as conn:store._access(conn,pid,actor,edit=True)
    p=store.project(pid,actor)
    criteria=p["settings"].get("screening_criteria",{})
    if not criteria.get("include"):raise WorkspaceError("先填写纳入标准，再生成筛选建议")
    from workspace.intelligence import ResearchModel
    engine=ResearchModel(model,budget=180)
    suggestions=[]
    for paper in store.items(pid,actor,"paper")[:100]:
        rows=[{"text":q,"title":paper["label"],"paper_id":paper["id"],**s} for q,s in source_sentences(store,pid,actor,paper["id"])[:20]]
        claims=engine.claims('Assess eligibility against the criteria. Return a single claim, with decision '
            'include, exclude or uncertain. Use uncertain when a criterion cannot be established; absence from '
            'an abstract is not grounds for exclusion. Cite the exact eligibility evidence.',rows,context=criteria,limit=1) if engine.model else []
        c=claims[0] if claims else None
        suggestions.append({"paper_id":paper["id"],"decision":c["decision"] if c and c.get("decision") in ("include","exclude","uncertain") else "uncertain",
            "reason":c["text"] if c else "未取得经校验的模型建议，请人工对照筛选标准与原文。",
            "sources":[{"quote":r["quote"],**{k:r["source"].get(k) for k in ("paper_id","document_id","page","scope")}} for r in c["references"]] if c else []})
    return store.put(pid,actor,"screening_suggestions","筛选辅助建议",{"suggestions":suggestions,"criteria":criteria,
        "message":"这些是辅助建议，未替任何成员提交筛选决定。","generation_status":engine.status})


def screening(store, pid, actor):
    p = store.project(pid, actor)
    decisions = store.items(pid, actor, "screening")
    papers = store.items(pid, actor, "paper")
    criteria = p["settings"].get("screening_criteria", {"include": "", "exclude": "", "reviewers": 2})
    rows, stats = [], Counter()
    for paper in papers:
        votes = [d for d in decisions if d["data"]["paper_id"] == paper["id"]]
        stage = "fulltext" if any(d["data"]["stage"] == "fulltext" for d in votes) else "title_abstract"
        active = [d for d in votes if d["data"]["stage"] == stage]
        reviewers = {d["data"]["reviewer"] for d in active}
        conclusions = {d["data"]["decision"] for d in active}
        state = "conflict" if len(conclusions) > 1 else "pending" if len(reviewers) < criteria.get("reviewers", 2) else next(iter(conclusions), "pending")
        stats[state] += 1
        rows.append({"paper": paper, "decisions": votes, "status": state, "stage": stage, "reviewer_count": len(reviewers)})
    return {"criteria": criteria, "rows": rows, "project_revision": p["revision"],
            "flow": {"identified": len(papers), "included": stats["include"], "excluded": stats["exclude"], "uncertain": stats["uncertain"], "pending": stats["pending"], "conflicts": stats["conflict"]}}


def record_screening(store, pid, actor, paper_id, decision, stage, reason, revision=None):
    store.item(pid, actor, paper_id, "paper")
    if decision not in ("include", "exclude", "uncertain") or stage not in ("title_abstract", "fulltext"):
        raise WorkspaceError("请选择有效的筛选阶段和结论")
    if decision == "exclude" and not reason.strip():
        raise WorkspaceError("排除文献时必须记录原因")
    if stage == "fulltext" and not any(d["data"].get("paper_id") == paper_id for d in store.items(pid, actor, "document")):
        raise WorkspaceError("该文献尚无项目全文，不能标记已完成全文筛选")
    old = next((r for r in store.items(pid, actor, "screening") if r["data"]["paper_id"] == paper_id and r["data"]["reviewer"] == actor and r["data"]["stage"] == stage), None)
    if old and revision != old["revision"]:
        raise WorkspaceError("筛选记录已有新版本，请重新加载", 409)
    store.put(pid, actor, "screening", "文献筛选", {"paper_id": paper_id, "reviewer": actor,
        "decision": decision, "stage": stage, "reason": reason[:5000]}, old["id"] if old else None, old["revision"] if old else None)
    return screening(store, pid, actor)
