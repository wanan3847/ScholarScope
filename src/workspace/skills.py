"""Versioned instruction discovery; executable behavior is a fixed tool whitelist."""
import json
import re
from pathlib import Path
from workspace.store import WorkspaceError

ROOT = Path(__file__).with_name("skills")
# Contracts are validated again in the executor; instructions cannot add code.
TOOLS = {
    "research": {"label":"规划并补检索真实文献","budget":240,"inputs":{"query":"text","limit":"integer","year_from":"integer","year_to":"integer"}},
    "acquire": {"label":"获取可用开放全文","budget":160,"inputs":{"paper_ids":"ids"}},
    "search": {"label": "检索并加入真实文献", "budget": 110, "inputs": {"query": "text", "limit": "integer", "year_from": "integer", "year_to": "integer"}},
    "matrix": {"label": "提取证据矩阵", "budget": 200, "inputs": {"paper_ids": "ids", "column_ids": "ids"}},
    "question": {"label": "项目原文问答", "budget": 135, "inputs": {"question": "text", "paper_ids": "ids"}},
    "verify": {"label": "检查证据与引用", "budget": 45, "inputs": {}},
    "review": {"label": "来源与覆盖范围审查", "budget": 130, "inputs": {"critical": "boolean"}},
    "manuscript": {"label": "生成综述草稿", "budget": 130, "inputs": {"template": "text", "evidence_ids": "ids"}},
    "presentation": {"label": "生成 12 页报告", "budget": 130, "inputs": {"purpose": "text", "evidence_ids": "ids"}},
    "chart": {"label": "保存有来源的数据图表", "budget": 45, "inputs": {"data": "object"}},
    "export": {"label": "生成可下载产物", "budget": 70, "inputs": {"target_id": "text", "format": "text"}},
    "venue": {"label": "检查写作模板", "budget": 45, "inputs": {"manuscript_id": "text"}},
    "zotero": {"label": "从已配置 Zotero 库增量导入", "budget": 120, "inputs": {"attachments": "boolean"}},
    "monitor": {"label": "检查保存问题的新文献", "budget": 110, "inputs": {"monitor_id": "text", "run_key": "text"}},
}


def registry():
    result = []
    for folder in sorted(ROOT.iterdir()):
        if not folder.is_dir() or folder.is_symlink(): continue
        path = folder / "manifest.json"
        if not path.is_file() or path.is_symlink(): continue
        d = json.loads(path.read_text())
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,60}", d.get("id", "")) or d.get("license") != "MIT":
            raise WorkspaceError("项目技能元数据无效")
        skill = folder / "SKILL.md"
        if not skill.is_file() or skill.is_symlink(): raise WorkspaceError("技能缺少本地说明")
        allowed = d.get("tools", [])
        d["available"] = all(t in TOOLS for t in allowed)
        d["instructions"] = skill.read_text()[:30000]
        d["contracts"] = {t: TOOLS[t] for t in allowed if t in TOOLS}
        result.append(d)
    return result


def clean_inputs(tool, data, previous=()):
    if tool not in TOOLS or not isinstance(data, dict): raise WorkspaceError("工作流工具或输入无效")
    if set(data) - set(TOOLS[tool]["inputs"]): raise WorkspaceError("工具输入包含未支持字段")
    for key, value in data.items():
        if isinstance(value, dict) and set(value) == {"from_step"}:
            if value["from_step"] not in previous: raise WorkspaceError("输入只能引用已在前面的步骤输出")
            continue
        typ = TOOLS[tool]["inputs"][key]
        valid = (typ == "text" and isinstance(value, str) and len(value) <= 4000
            or typ == "integer" and type(value) is int and 0 <= value <= 9999
            or typ == "boolean" and type(value) is bool
            or typ == "object" and isinstance(value, dict) and len(json.dumps(value)) < 200000
            or typ == "ids" and isinstance(value, list) and len(value) <= 100 and all(isinstance(v, str) and len(v) <= 200 for v in value))
        if not valid: raise WorkspaceError("工具输入格式不符合约束：" + key)
    return data


def plan(store, pid, actor, spec):
    project = store.project(pid, actor)
    custom = spec.get("steps")
    if custom is None:
        custom = []
        if spec.get("search", False):
            query = str(spec.get("query") or project["query"] or project["title"]).strip()
            custom.append({"id": "search", "tool": "research" if spec.get("deep", False) else "search", "inputs": {"query": query, "limit": 30}})
            if spec.get("deep",False):custom.append({"id":"acquire","tool":"acquire"})
        custom += [
            {"id": "matrix", "tool": "matrix"},
            {"id": "question", "tool": "question", "inputs": {"question": spec.get("query") or project["query"] or project["title"]}},
            {"id": "review", "tool": "review", "inputs": {"critical": True}},
            {"id": "verify", "tool": "verify", "confirm": True},
            {"id": "manuscript", "tool": "manuscript"},
            {"id": "presentation", "tool": "presentation"},
            {"id": "word", "tool": "export", "inputs": {"target_id": {"from_step": "manuscript"}, "format": "docx"}},
            {"id": "slides", "tool": "export", "inputs": {"target_id": {"from_step": "presentation"}, "format": "pptx"}},
        ]
    if not isinstance(custom, list) or not 1 <= len(custom) <= 30: raise WorkspaceError("工作流需要 1–30 个步骤")
    steps, seen = [], set()
    for s in custom:
        if not isinstance(s, dict): raise WorkspaceError("步骤格式无效")
        sid = s.get("id", "")
        tool = s.get("tool")
        if not isinstance(sid, str) or not re.fullmatch(r"[a-zA-Z][\w-]{0,50}", sid) or sid in seen: raise WorkspaceError("步骤标识需唯一且有效")
        inputs = clean_inputs(tool, s.get("inputs", {}), seen)
        if tool in ("manuscript", "presentation") and not any(p["tool"] == "verify" for p in steps):
            raise WorkspaceError("生成文稿或演示前需有核验与人工确认步骤")
        # Confirmation is compulsory at evidence verification, including custom workflows.
        steps.append({"id": sid, "tool": tool, "label": TOOLS[tool]["label"], "inputs": inputs,
            "budget_seconds": TOOLS[tool]["budget"], "confirm": tool == "verify" or bool(s.get("confirm")), "status": "pending", "attempts": 0})
        seen.add(sid)
    return steps
