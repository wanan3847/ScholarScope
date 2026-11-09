"""Source-bound checks, without invented experimental assessments."""
from workspace.store import WorkspaceError
from workspace.research_tools import matrix
from workspace.research_tools import source_sentences
import re
from workspace import writing, presentations


def inspect_project(store, pid, actor, *, critical=False):
    papers = store.items(pid, actor, "paper")
    evidence = store.items(pid, actor, "evidence")
    findings = []
    for p in papers:
        related = [e for e in evidence if e["data"]["paper_id"] == p["id"]]
        fields = {e["data"].get("field") for e in related}
        missing = [f for f in ("method", "dataset", "metrics", "limitations") if f not in fields]
        if missing:
            findings.append({"kind": "coverage", "paper_id": p["id"], "title": p["label"],
                "message": "当前证据尚未覆盖：" + "、".join(missing) + "。这不代表论文未报告，需回查原文。", "evidence_ids": [e["id"] for e in related]})
        if not any(e["data"].get("scope") == "fulltext" for e in related):
            findings.append({"kind": "source_scope", "paper_id": p["id"], "title": p["label"],
                "message": "尚无全文证据，不能仅凭标题或摘要评估实验可复现性。", "evidence_ids": [e["id"] for e in related]})
        if "finding" in fields and not {"method", "dataset", "metrics"}.issubset(fields):
            findings.append({"kind": "method_conclusion_context", "paper_id": p["id"], "title": p["label"],
                "message": "已有结论摘录，但对应方法、数据或评价指标尚未完整关联。请核对结论是否限于原文的研究条件。", "evidence_ids": [e["id"] for e in related if e["data"].get("field") == "finding"]})
        if critical:
            passages = source_sentences(store, pid, actor, p["id"])
            for label, pattern in (("独立验证与数据拆分", r"\b(?:test set|hold.out|cross.validation|external validation|train.test split)\b|交叉验证|独立测试|外部验证"),
                                   ("不确定性与统计范围", r"confidence interval|standard deviation|uncertainty|置信区间|标准差|不确定性"),
                                   ("代码与复现资料", r"github\.com|source code|code availability|代码公开|代码可用|复现资料")):
                matches = [(quote, location) for quote, location in passages if re.search(pattern, quote, re.I)]
                findings.append({"kind": "reproducibility_context", "paper_id": p["id"], "title": p["label"], "topic": label,
                    "message": ("已找到相关原文，请核对其适用范围：" if matches else "当前可读取资料尚未定位相关描述；需回查全文，不能据此判定论文缺失：") + label,
                    "evidence_ids": [], "source_passages": [{"quote": q, "paper_id": p["id"], **src} for q, src in matches[:3]]})
    checks = []
    for e in evidence:
        valid = store.verify_evidence(pid, actor, e["id"])["valid"]
        checks.append({"evidence_id": e["id"], "revision": e["revision"], "source_hash": e["data"]["source_hash"], "valid": valid, "confirmed": bool(e["data"].get("confirmed_by")),
            "scope": e["data"].get("scope"), "quote": e["data"]["quote"], "paper_id": e["data"]["paper_id"],
            "document_id": e["data"].get("document_id"), "page": e["data"].get("page")})
        if not valid:
            findings.append({"kind": "invalid_source", "message": "该片段与当前来源不再一致，请重新核对。", "evidence_ids": [e["id"]]})
        if critical and e["data"].get("value_status") == "interpretation":
            findings.append({"kind": "interpretation", "message": "该值含研究者解释，需检查其是否超出所引原文。", "evidence_ids": [e["id"]]})
    outputs = []
    for kind, view in (("manuscript", writing.manuscript_view), ("presentation", presentations.deck_view)):
        for item in store.items(pid, actor, kind):
            result = view(store, pid, actor, item)
            outputs.append({"id": item["id"], "kind": kind, "title": item["label"], "validation": result["validation"], "stale": bool(item["data"].get("stale"))})
    return {"mode": "source_and_coverage_checks", "paper_count": len(papers), "evidence_count": len(evidence),
        "valid": bool(evidence) and all(c["valid"] for c in checks), "checks": checks, "findings": findings, "outputs": outputs,
        "boundary": "仅检查已收集资料、引文和覆盖范围；未实施独立实验，不推断未报告结果，也不替研究者判断因果关系。"}


def save_review(store, pid, actor, *, critical=False, model=None):
    result = inspect_project(store, pid, actor, critical=critical)
    if critical:
        from workspace.intelligence import ResearchModel, evidence_sources
        evidence = [e for e in store.items(pid, actor, "evidence") if store.verify_evidence(pid, actor, e["id"])["valid"]]
        intelligence = ResearchModel(model)
        claims = intelligence.claims("Critically assess methods versus conclusions, validation split, leakage, "
            "comparability, uncertainty and reproducibility. Form actionable review observations from cited evidence. "
            "Do not declare a study deficient solely because the available abstract omits a detail.",
            evidence_sources(store, pid, actor, evidence), context=store.project(pid, actor)["query"], limit=12) if intelligence.model else []
        for c in claims:
            refs = c["references"]
            result["findings"].append({"kind": "supported_critical_analysis", "message": c["text"],
                "evidence_ids": [r["source"]["evidence"]["id"] for r in refs],
                "source_passages": [{"quote": r["quote"], **{k: r["source"].get(k) for k in ("paper_id", "document_id", "page", "scope")}} for r in refs]})
        result["generation_status"] = intelligence.status
    result["evidence_ids"] = [c["evidence_id"] for c in result["checks"]]
    result["stale"] = False
    return store.put(pid, actor, "review", "批判性资料检查" if critical else "来源与稿件审查", result)
