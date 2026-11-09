"""Saved research queries, durable scheduled checks, and sourced exploration."""
import time
import re
from urllib.parse import quote
import requests
from sqlalchemy import select
from workspace.store import WorkspaceError, paper_aliases, ident
from agent.api_settings import get_api_setting


def save_monitor(store, pid, actor, data, item_id=None, revision=None):
    query = str(data.get("query", "")).strip()
    lower, upper, interval = data.get("year_from", 0), data.get("year_to", 0), data.get("interval_hours", 0)
    if not 3 <= len(query) <= 4000: raise WorkspaceError("保存的检索问题需为 3–4000 个字符")
    if any(type(v) is not int for v in (lower, upper, interval)) or lower and not 1900 <= lower <= 2200 or upper and not 1900 <= upper <= 2200 or lower and upper and lower > upper:
        raise WorkspaceError("检索年份范围无效")
    if interval != 0 and not 6 <= interval <= 720: raise WorkspaceError("自动检查间隔需为 6–720 小时，0 表示手动")
    old = store.item(pid, actor, item_id, "monitor") if item_id else None
    spec = {**(old["data"] if old else {}), "query": query, "year_from": lower, "year_to": upper,
        "interval_hours": interval, "add_new": data.get("add_new") is True, "created_by": old["data"]["created_by"] if old else actor}
    if old and any(old["data"].get(k) != spec[k] for k in ("query", "year_from", "year_to")):
        spec.update(seen=[], last_report=None, queue_token=None, task_id=None)
    spec["next_due"] = time.time() + interval * 3600 if interval else None
    return store.put(pid, actor, "monitor", query, spec, item_id, revision)


def online_search(query, limit, upper):
    from agent.orchestrator import Orchestrator
    from web.app import _get_llm_router
    return Orchestrator(llm_chat=_get_llm_router().get(), max_output=50, practical_limit=limit,
        deadline_seconds=45, max_rounds=1, max_judge=20).sync_run(query, str(upper) + "1231" if upper else "")


def check_monitor(store, pid, actor, monitor_id, run_key="", *, search=online_search):
    monitor = store.item(pid, actor, monitor_id, "monitor")
    with store.engine.connect() as conn: store._access(conn, pid, actor, edit=True)
    old_report = next((r for r in store.items(pid, actor, "monitor_report") if run_key and r["data"].get("run_key") == run_key), None)
    if old_report: return old_report
    spec = monitor["data"]; result = search(spec["query"], 30, spec.get("year_to", 0))
    known = set(spec.get("seen", []))
    known.update(a for p in store.items(pid, actor, "paper") for a in paper_aliases(p["data"]))
    discovered, aliases_seen = [], set()
    for paper in result.get("papers", [])[:50]:
        year = paper.get("year"); lo, hi = spec.get("year_from", 0), spec.get("year_to", 0)
        if lo or hi:
            try: number = int(year)
            except (TypeError, ValueError): continue
            if lo and number < lo or hi and number > hi: continue
        aliases = set(paper_aliases(paper))
        if aliases & aliases_seen: continue
        new = not bool(aliases & known)
        # Keep source metadata and exact recommendation evidence, never scores.
        metadata = {k: v for k, v in paper.items() if k not in ("score", "citations", "citation_count", "normalized_score")}
        project_id = store.add_paper(pid, actor, metadata)["id"] if new and spec.get("add_new") else None
        discovered.append({"paper": metadata, "new": new, "project_paper_id": project_id})
        aliases_seen.update(aliases)
    report = store.put(pid, actor, "monitor_report", spec["query"], {"monitor_id": monitor_id, "run_key": run_key, "checked_at": time.time(),
        "papers": discovered, "new_count": sum(p["new"] for p in discovered), "actual_count": len(discovered),
        "message": "新发现相对于本检索及项目已见记录，不能当作论文发表时间。" if discovered else "本轮未取得可用结果；可能未匹配或来源暂不可用，未补造文献。"})
    current = store.item(pid, actor, monitor_id, "monitor")
    # A concurrent edit must not attach an old-query report to a new query.
    if all(current["data"].get(k) == spec.get(k) for k in ("query", "year_from", "year_to")):
        data = {**current["data"], "seen": sorted(known | aliases_seen), "last_report": report["id"], "last_checked": time.time()}
        store.put(pid, actor, "monitor", current["label"], data, monitor_id, current["revision"])
    return report


def enqueue(runtime, pid, actor, monitor_id, *, automatic=False):
    store = runtime.store; monitor = store.item(pid, actor, monitor_id, "monitor")
    with store.engine.connect() as conn: store._access(conn, pid, actor, edit=True)
    data = monitor["data"]
    if data.get("task_id"):
        task = store.item(pid, actor, data["task_id"], "task")
        if task["data"]["status"] in ("queued", "running", "awaiting_confirmation"): return task
    token = data.get("queue_token") if data.get("queue_pending") else ident()
    if not data.get("queue_pending"):
        data = {**data, "queue_token": token, "queue_pending": True, "queued_at": time.time(),
            "next_due": time.time() + data.get("interval_hours", 0) * 3600 if data.get("interval_hours") else None}
        monitor = store.put(pid, actor, "monitor", monitor["label"], data, monitor_id, monitor["revision"])
    task = next((t for t in store.items(pid, actor, "task") if any(s.get("inputs", {}).get("run_key") == token for s in t["data"]["steps"])), None)
    if task is None:
        task = runtime.create(pid, actor, {"title": ("自动检查：" if automatic else "检查动态：") + monitor["label"],
            "steps": [{"id": "monitor", "tool": "monitor", "inputs": {"monitor_id": monitor_id, "run_key": token}}]})
    fresh = store.item(pid, actor, monitor_id, "monitor")
    store.put(pid, actor, "monitor", fresh["label"], {**fresh["data"], "task_id": task["id"], "queue_pending": False}, monitor_id, fresh["revision"])
    return task


def enqueue_due(runtime):
    store = runtime.store
    with store.engine.connect() as conn:
        monitors = [store._row(r) for r in conn.execute(select(store.item_table).where(store.item_table.c.kind == "monitor"))]
    for monitor in monitors[:1000]:
        data = monitor["data"]
        due = data.get("next_due") and data["next_due"] <= time.time()
        recover = data.get("queue_pending") and data.get("queued_at", 0) < time.time() - 60
        if due or recover:
            try:
                project = store.project(monitor["project_id"], data["created_by"])
                if not project["archived"]: enqueue(runtime, monitor["project_id"], data["created_by"], monitor["id"], automatic=True)
            except WorkspaceError: pass


def related(store, pid, actor, paper_id):
    paper = store.item(pid, actor, paper_id, "paper")["data"]; doi = paper.get("doi")
    from workspace.knowledge import terms
    target_terms = set(terms(paper.get("title", "") + " " + paper.get("abstract", "")))
    neighbors = []
    for row in store.items(pid, actor, "paper"):
        if row["id"] == paper_id: continue
        data = row["data"]; shared = target_terms & set(terms(data.get("title", "") + " " + data.get("abstract", "")))
        if len(shared) >= 2:
            neighbors.append((len(shared), {"paper": data, "project_paper_id": row["id"], "shared_terms": sorted(shared)[:10],
                "quote": data.get("abstract") or data["title"], "relation": "shared_project_terms", "source": "project_title_abstract"}))
    neighbors.sort(key=lambda pair: -pair[0]); similar = [row for _, row in neighbors[:8]]
    def output(rows, message): return {"papers": rows, "similar": similar, "message": message, "similar_basis": "项目标题/摘要共享词，用于探索阅读；不能当作引文关系。"}
    if not doi: return output([], "该文献没有 DOI，暂未取得数据库引文关系。")
    params = {}; key = get_api_setting("openalex_key", "OPENALEX_API_KEY")
    if key: params["api_key"] = key
    try:
        response = requests.get("https://api.openalex.org/works/" + quote("https://doi.org/" + doi, safe=""), params=params, timeout=6)
        if response.status_code != 200: raise ValueError()
        work = response.json(); refs = [r.rsplit("/", 1)[-1] for r in work.get("referenced_works", []) if re.fullmatch(r"https://openalex.org/W\d+", r)][:10]
        if not refs: return output([], "OpenAlex 尚未提供该文献的参考文献关系。")
        response = requests.get("https://api.openalex.org/works", params={**params, "filter": "openalex_id:" + "|".join(refs), "per-page": 10}, timeout=6)
        if response.status_code != 200: raise ValueError()
        from agent.spar2.retrievers import _parse_openalex_work
        rows = []
        for raw in response.json().get("results", []):
            if raw.get("id", "").rsplit("/", 1)[-1] not in refs: continue
            p = _parse_openalex_work(raw)
            if p and p.get("title"): rows.append({"paper": {k: v for k, v in p.items() if k not in ("score", "citation_count", "citations")}, "relation": "referenced_by_selected", "source": "openalex"})
        return output(rows, "这些文献来自 OpenAlex 的参考文献关系；顺序不依据引用量。")
    except Exception: return output([], "引文关系源暂不可用，请稍后重试。")
