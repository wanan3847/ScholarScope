"""Durable, leased research tasks with bounded whitelisted tool processes.

The interface is create/action/list plus one supervisor lifecycle. A task holds
the exact plan, source checks, human approvals and output IDs; process restart
never turns interrupted work into a fictitious success.
"""
from __future__ import annotations
import copy
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from sqlalchemy import select
from workspace.store import WorkspaceStore, WorkspaceError, digest, ident
from workspace import skills, review

ACTIVE = {"queued", "running"}
TERMINAL = {"completed", "cancelled", "failed", "interrupted"}


class OperationStore(WorkspaceStore):
    """Stable output creation identities make a resumed step idempotent."""
    def __init__(self, url, operation):
        super().__init__(url)
        self.operation, self.ordinal = operation, 0

    def put(self, pid, actor, kind, label, data, item_id=None, revision=None, **kw):
        if not item_id and kind in {"manuscript", "presentation", "answer", "review", "chart", "artifact", "search_report"}:
            self.ordinal += 1
            key = digest(self.operation + ":" + kind + ":" + str(self.ordinal))[:32]
            with self.engine.connect() as conn:
                self._access(conn, pid, actor, edit=True)
                old = self._row(conn.execute(select(self.item_table).where(self.item_table.c.id == key, self.item_table.c.project_id == pid)).first())
            if old: return old
            kw["creation_id"] = key
            data = {**data, "operation_id": self.operation}
        return super().put(pid, actor, kind, label, data, item_id, revision, **kw)


def _result(item, message=""):
    return {"output_id": item["id"], "kind": item["kind"], "title": item["label"], "message": message}


def execute_tool(store, pid, actor, tool, inputs):
    """The only executable tool dispatch; no prompt can extend this whitelist."""
    from workspace import research_tools, writing, presentations, charts, artifacts
    from workspace.documents import ObjectStore
    skills.clean_inputs(tool, inputs)
    store.project(pid, actor)
    if tool in ("research", "acquire"):
        from workspace import deep_research
        if tool == "research":
            row = deep_research.research(store,pid,actor,inputs.get("query") or store.project(pid,actor)["query"],
                limit=max(1,min(inputs.get("limit",30),50)),year_from=inputs.get("year_from",0),year_to=inputs.get("year_to",0))
            return {**_result(row,row["data"]["message"]),"paper_ids":row["data"]["paper_ids"],"rounds":row["data"]["rounds"]}
        result = deep_research.acquire(store,pid,actor,paper_ids=inputs.get("paper_ids"))
        row = store.put(pid,actor,"acquisition_report","开放全文获取记录",result)
        return {**_result(row,result["message"]),"records":result["records"],"downloaded":result["downloaded"]}
    if tool == "search":
        from agent.orchestrator import Orchestrator
        from web.app import _get_llm_router
        query = str(inputs.get("query", "")).strip()
        if not query: raise WorkspaceError("检索步骤需要研究问题")
        lower, upper = inputs.get("year_from", 0), inputs.get("year_to", 0)
        if lower and upper and lower > upper: raise WorkspaceError("检索年份范围无效")
        limit = max(1, min(int(inputs.get("limit", 30)), 50))
        engine = Orchestrator(llm_chat=_get_llm_router().get(), max_output=50, practical_limit=limit,
            deadline_seconds=50, max_rounds=2, max_judge=24, local_top_k=300, year_from=lower)
        result = engine.sync_run(query, str(upper) + "1231" if upper else "")
        rows = []
        for paper in result.get("papers", []):
            year = paper.get("year")
            if (lower or upper) and (not year or lower and int(year) < lower or upper and int(year) > upper): continue
            rows.append(store.add_paper(pid, actor, paper)["id"])
        report = store.put(pid, actor, "search_report", query, {"query": query, "paper_ids": rows,
            "requested_count": limit, "actual_count": len(rows), "year_from": lower, "year_to": upper,
            "message": f"已加入 {len(rows)} 篇真实检索文献。" + ("实际匹配数量不足目标，未补造文献。" if len(rows) < limit else ""),
            "ranking_mode": result.get("stats", {}).get("ranking_mode", "unknown")})
        return {**_result(report), "paper_ids": rows, "message": report["data"]["message"]}
    if tool == "matrix":
        result = research_tools.extract_matrix(store, pid, actor, inputs.get("paper_ids"), inputs.get("column_ids"))
        return {"kind": "matrix", "message": "已从项目原文提取矩阵候选；人工修改保留。", "paper_count": len(result["rows"])}
    if tool == "question":
        answer = research_tools.answer_question(store, pid, actor, inputs.get("question") or store.project(pid, actor)["query"], inputs.get("paper_ids"))
        data = answer.get("data", answer)
        return {"output_id": answer.get("id"), "kind": "answer", "message": data.get("answer", ""), "citations": data.get("citations", [])}
    if tool == "verify":
        return {"kind": "verification", "report": review.inspect_project(store, pid, actor), "message": "已核对当前原文与引用；需要研究者检查本阶段后继续。"}
    if tool == "review": return _result(review.save_review(store, pid, actor, critical=inputs.get("critical", False)))
    if tool == "manuscript": return _result(writing.generate_manuscript(store, pid, actor, inputs.get("template", "review"), inputs.get("evidence_ids")))
    if tool == "presentation": return _result(presentations.generate_deck(store, pid, actor, inputs.get("purpose", "meeting"), inputs.get("evidence_ids")))
    if tool == "chart": return _result(charts.save_chart(store, pid, actor, inputs.get("data", {})))
    if tool == "export": return _result(artifacts.export_artifact(store, ObjectStore(), pid, actor, inputs.get("target_id"), inputs.get("format", "md")))
    if tool == "venue":
        item = store.item(pid, actor, inputs.get("manuscript_id"), "manuscript")
        view = writing.manuscript_view(store, pid, actor, item)
        return {"kind": "template_check", "output_id": item["id"], "validation": view["validation"], "message": "依据文稿保存的模板检查章节、摘要、关键词与引用。"}
    if tool == "zotero":
        from workspace.zotero import sync
        result = sync(store, pid, actor, attachments=inputs.get("attachments", False))
        if not result["last_report"]["complete"]: raise WorkspaceError("Zotero 本轮未完成；可在文献同步中查看进度与错误", 503)
        return {"kind": "zotero_report", "output_id": result["output_id"], "message": "已完成 Zotero 增量导入；冲突和附件错误保留在同步记录。"}
    if tool == "monitor":
        from workspace.monitoring import check_monitor
        return _result(check_monitor(store, pid, actor, inputs.get("monitor_id"), inputs.get("run_key", "")))
    raise WorkspaceError("工具未注册")


class TaskRuntime:
    def __init__(self, store, *, executor=None, poll_seconds=2):
        self.store, self.executor, self.poll_seconds = store, executor, poll_seconds
        self.stopping = threading.Event()
        self.thread = None
        self.workers = {}

    def create(self, pid, actor, spec):
        with self.store.engine.connect() as conn: self.store._access(conn, pid, actor, edit=True)
        steps = skills.plan(self.store, pid, actor, spec)
        title = str(spec.get("title") or "研究资料整理与报告")[:200]
        data = {"created_by": actor, "executor_actor": actor, "status": "queued", "steps": steps,
            "approvals": [], "outputs": [], "elapsed_seconds": 0, "budget_seconds": min(1800, sum(s["budget_seconds"] for s in steps) * 2),
            "lease": None, "lease_until": 0, "message": "计划已保存，等待执行。"}
        return self.store.put(pid, actor, "task", title, data)

    def _save(self, task, data):
        return self.store.put(task["project_id"], data["executor_actor"], "task", task["label"], data, task["id"], task["revision"])

    def action(self, pid, actor, tid, action):
        with self.store.engine.connect() as conn: self.store._access(conn, pid, actor, edit=True)
        task = self.store.item(pid, actor, tid, "task")
        d = copy.deepcopy(task["data"])
        if action == "cancel":
            if d["status"] not in ACTIVE | {"awaiting_confirmation"}: raise WorkspaceError("当前任务不能取消", 409)
            d.update(status="cancelled", message="任务已取消，已完成的真实结果保留。", cancelled_by=actor)
        elif action in ("resume", "retry"):
            if d["status"] not in {"failed", "interrupted", "cancelled"} and not (d["status"] == "running" and d.get("lease_until", 0) < time.time()): raise WorkspaceError("当前任务无需恢复或重试", 409)
            if d.get("lease_until", 0) > time.time() and d.get("lease"): raise WorkspaceError("执行进程正在停止，请稍后恢复", 409)
            d.update(status="queued", executor_actor=actor, lease=None, lease_until=0, message="保留已完成步骤，从未完成步骤继续。")
            for step in d["steps"]:
                if step["status"] in ("running", "failed", "cancelled"): step.update(status="pending", error=None)
        elif action == "approve":
            if d["status"] != "awaiting_confirmation": raise WorkspaceError("当前任务没有待确认阶段", 409)
            step = next(s for s in d["steps"] if s["status"] == "awaiting_confirmation")
            if step["tool"] == "verify":
                current = review.inspect_project(self.store, pid, actor)
                old = step["result"]["report"]
                if not current["valid"] or digest(json.dumps(current["checks"], sort_keys=True)) != digest(json.dumps(old["checks"], sort_keys=True)):
                    raise WorkspaceError("证据不足或来源已变化；请处理后重新核验本阶段", 409)
            d["approvals"].append({"step_id": step["id"], "actor": actor, "at": time.time(), "result_hash": digest(json.dumps(step["result"], sort_keys=True))})
            step["status"] = "completed"
            d.update(status="queued", executor_actor=actor, message="研究者已确认本阶段，继续执行。", lease=None, lease_until=0)
        elif action == "recheck":
            if d["status"] != "awaiting_confirmation": raise WorkspaceError("当前任务无需重新核验", 409)
            step = next(s for s in d["steps"] if s["status"] == "awaiting_confirmation")
            step.update(status="pending", result=None)
            d.update(status="queued", executor_actor=actor, lease=None, lease_until=0, message="重新核验当前来源。")
        else: raise WorkspaceError("未知任务操作")
        # Updating executor_actor must not be used to skip the requesting actor's ACL.
        return self.store.put(pid, actor, "task", task["label"], d, tid, task["revision"])

    def _all_tasks(self):
        with self.store.engine.connect() as conn:
            return [self.store._row(r) for r in conn.execute(select(self.store.item_table).where(self.store.item_table.c.kind == "task"))]

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stopping.clear()
        self.thread = threading.Thread(target=self._supervise, daemon=True, name="research-task-supervisor")
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread: self.thread.join(timeout=5)
        for t in list(self.workers.values()): t.join(timeout=5)

    def _supervise(self):
        next_monitor_check = 0
        while not self.stopping.is_set():
            try:
                if time.time() >= next_monitor_check:
                    from workspace.monitoring import enqueue_due
                    enqueue_due(self)
                    next_monitor_check = time.time() + 30
                self.workers = {tid: t for tid, t in self.workers.items() if t.is_alive()}
                for task in self._all_tasks():
                    d = task["data"]
                    if d["status"] == "running" and d.get("lease_until", 0) < time.time():
                        try: self._save(task, {**d, "status": "interrupted", "lease": None, "lease_until": 0, "message": "执行进程中断；已完成步骤保留，可恢复任务。"})
                        except WorkspaceError: pass
                    elif d["status"] == "cancelled" and d.get("lease") and d.get("lease_until", 0) < time.time():
                        try: self._save(task, {**d, "lease": None, "lease_until": 0})
                        except WorkspaceError: pass
                    elif d["status"] == "queued" and len(self.workers) < 2:
                        token = ident()
                        try: claimed = self._save(task, {**d, "status": "running", "lease": token, "lease_until": time.time() + 30})
                        except WorkspaceError: continue
                        t = threading.Thread(target=self._run, args=(claimed, token), daemon=True, name="research-task-worker")
                        self.workers[task["id"]] = t
                        t.start()
            except Exception:
                # Connection recovery is retried; no credential-bearing exception is logged.
                pass
            self.stopping.wait(self.poll_seconds)

    def _fresh(self, task, token):
        row = self.store.item(task["project_id"], task["data"]["executor_actor"], task["id"], "task")
        if row["data"].get("lease") != token: raise WorkspaceError("任务执行权已变化", 409)
        return row

    def _run(self, task, token):
        try:
            while True:
                task = self._fresh(task, token)
                d = copy.deepcopy(task["data"])
                if d["status"] != "running": return
                step = next((s for s in d["steps"] if s["status"] != "completed"), None)
                if step is None:
                    self._save(task, {**d, "status": "completed", "message": "计划全部步骤已执行；产物保留真实来源。", "lease": None, "lease_until": 0}); return
                if d["elapsed_seconds"] >= d["budget_seconds"]:
                    raise WorkspaceError("任务累计执行预算已用尽；请查看已完成结果")
                if step["tool"] in ("manuscript", "presentation"):
                    checkpoint = next(s for s in reversed(d["steps"][:d["steps"].index(step)]) if s["tool"] == "verify")
                    current = review.inspect_project(self.store, task["project_id"], d["executor_actor"])
                    if digest(json.dumps(current["checks"], sort_keys=True)) != digest(json.dumps(checkpoint["result"]["report"]["checks"], sort_keys=True)):
                        checkpoint.update(status="pending", result=None)
                        self._save(task, {**d, "message": "确认后的证据已变化，重新核验后再生成。"})
                        continue
                step.update(status="running", attempts=step["attempts"] + 1, started_at=time.time(), error=None)
                d["message"] = "正在执行：" + step["label"]
                task = self._save(task, d)
                inputs = copy.deepcopy(step["inputs"])
                for key, value in inputs.items():
                    if isinstance(value, dict) and set(value) == {"from_step"}:
                        previous = next(s for s in d["steps"] if s["id"] == value["from_step"])
                        output_id = previous.get("result", {}).get("output_id")
                        if not output_id: raise WorkspaceError("前置步骤没有可引用产物")
                        inputs[key] = output_id
                begin = time.monotonic()
                try:
                    result = self._execute(task, token, step, inputs)
                    task = self._fresh(task, token)
                    d = copy.deepcopy(task["data"])
                    target = next(s for s in d["steps"] if s["id"] == step["id"])
                    d["elapsed_seconds"] += time.monotonic() - begin
                    if d["status"] != "running":
                        d.update(lease=None, lease_until=0)
                        target["status"] = "cancelled"
                        self._save(task, d); return
                    target.update(result=result, finished_at=time.time(), status="awaiting_confirmation" if step["confirm"] else "completed")
                    if result.get("output_id") and result["output_id"] not in d["outputs"]: d["outputs"].append(result["output_id"])
                    if step["confirm"]:
                        d.update(status="awaiting_confirmation", message="本阶段已完成，请核对实际来源并确认后继续。", lease=None, lease_until=0)
                        self._save(task, d); return
                    self._save(task, d)
                except WorkspaceError as e:
                    task = self._fresh(task, token)
                    d = copy.deepcopy(task["data"])
                    current = next(s for s in d["steps"] if s["id"] == step["id"])
                    current.update(status="cancelled" if d["status"] == "cancelled" else "failed", error=str(e), finished_at=time.time())
                    d.update(elapsed_seconds=d["elapsed_seconds"] + time.monotonic() - begin, lease=None, lease_until=0,
                        status=d["status"] if d["status"] == "cancelled" else "interrupted" if self.stopping.is_set() else "failed", message=str(e))
                    self._save(task, d); return
        except Exception:
            # Unexpected failure is persisted without exposing model/DB credentials.
            try:
                task = self._fresh(task, token)
                self._save(task, {**task["data"], "status": "failed", "lease": None, "lease_until": 0, "message": "执行失败；已完成结果保留，可查看资料后重试。"})
            except Exception: pass
        finally:
            try:
                task = self._fresh(task, token)
                if task["data"]["status"] == "cancelled": self._save(task, {**task["data"], "lease": None, "lease_until": 0})
            except Exception: pass

    def _execute(self, task, token, step, inputs):
        if self.executor: return self.executor(task, step, inputs)
        with tempfile.TemporaryDirectory(prefix="research-step-") as directory:
            input_file, output_file = Path(directory) / "input.json", Path(directory) / "output.json"
            payload = {"pid": task["project_id"], "actor": task["data"]["executor_actor"], "operation": task["id"] + ":" + step["id"], "tool": step["tool"], "inputs": inputs}
            input_file.write_text(json.dumps(payload)); input_file.chmod(0o600)
            env = {**os.environ, "SCHOLARSCOPE_DATABASE_URL": self.store.engine.url.render_as_string(hide_password=False), "PYTHONUNBUFFERED": "1"}
            process = subprocess.Popen([sys.executable, "-m", "workspace.runtime", str(input_file), str(output_file)],
                cwd=str(Path(__file__).resolve().parents[1]), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            started, heartbeat = time.monotonic(), time.monotonic()
            try:
                while process.poll() is None:
                    current = self._fresh(task, token)
                    if current["data"]["status"] != "running": raise WorkspaceError("任务已取消；已完成结果保留")
                    if self.stopping.is_set(): raise WorkspaceError("服务停止，任务可从未完成步骤恢复")
                    if time.monotonic() - started > step["budget_seconds"]: raise WorkspaceError("本步骤超过执行预算，请检查资料或服务后重试")
                    if time.monotonic() - heartbeat > 5:
                        try: self._save(current, {**current["data"], "lease_until": time.time() + 30})
                        except WorkspaceError as e:
                            if e.status != 409: raise
                        heartbeat = time.monotonic()
                    remaining = max(0, step["budget_seconds"] - (time.monotonic() - started))
                    self.stopping.wait(min(0.25, remaining))
                if time.monotonic() - started > step["budget_seconds"]:
                    raise WorkspaceError("本步骤超过执行预算，请检查资料或服务后重试")
                if not output_file.exists() or output_file.stat().st_size > 4_000_000: raise WorkspaceError("工具没有返回可核对结果")
                result = json.loads(output_file.read_text())
                if result.get("error"): raise WorkspaceError(result["error"])
                return result["result"]
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=2)


_instance = None
_lock = threading.Lock()


def get_runtime(store=None):
    from workspace.store import get_store
    global _instance
    store = store or get_store()
    with _lock:
        if _instance is None or _instance.store is not store:
            if _instance: _instance.stop()
            _instance = TaskRuntime(store)
        return _instance


if __name__ == "__main__":
    request = json.loads(Path(sys.argv[1]).read_text())
    try:
        store = OperationStore(os.environ["SCHOLARSCOPE_DATABASE_URL"], request["operation"])
        result = {"result": execute_tool(store, request["pid"], request["actor"], request["tool"], request["inputs"])}
    except WorkspaceError as e: result = {"error": str(e)}
    except Exception: result = {"error": "工具执行失败；请检查输入和已配置服务。"}
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False)); Path(sys.argv[2]).chmod(0o600)
