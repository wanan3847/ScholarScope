"""Transactional project/evidence storage shared by all research tools.

SQLite is the local adapter; the same SQLAlchemy schema runs on PostgreSQL.
Every read and write crosses a project membership check. Credentials are never
accepted as project owners: the caller supplies an already authenticated actor.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
import time
import uuid
import threading
from urllib.parse import quote as urlquote
from pathlib import Path
from typing import Any

from sqlalchemy import (JSON, Column, Float, ForeignKey, Integer, MetaData,
                        String, Table, Text, create_engine, delete, insert,
                        select, update)
from sqlalchemy import event
from sqlalchemy.pool import StaticPool


class WorkspaceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def ident() -> str:
    return uuid.uuid4().hex


def digest(text: str | bytes) -> str:
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def paper_aliases(paper: dict) -> list[str]:
    aliases = []
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/|^doi:\s*", "", str(paper.get("doi") or ""), flags=re.I).strip().lower()
    if doi:
        if not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
            raise WorkspaceError("DOI 格式无效")
        aliases.append("doi:" + doi)
    arxiv = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", str(paper.get("arxiv_id") or ""), flags=re.I)
    arxiv = re.sub(r"(?:v\d+)?(?:\.pdf)?$", "", arxiv.strip())
    if arxiv:
        aliases.append("arxiv:" + arxiv)
    for key in ("paper_id", "id"):
        if paper.get(key):
            aliases.append("id:" + str(paper[key]))
    if not aliases:
        aliases.append("title:" + digest(normalized(paper.get("title", "")).casefold() + "|" + normalized(str(paper.get("authors", [])))))
    return sorted(set(aliases))


class WorkspaceStore:
    def __init__(self, url: str | None = None):
        root = Path(os.getenv("SCHOLARSCOPE_WORKSPACE_DIR", Path(__file__).resolve().parents[1] / "data" / "workspace"))
        url = url or os.getenv("SCHOLARSCOPE_DATABASE_URL")
        if not url and os.getenv("SCHOLARSCOPE_PG_HOST"):
            # Shared by server, subprocess tools and administration commands.
            url = "postgresql+psycopg://" + urlquote(os.environ["SCHOLARSCOPE_PG_USER"], safe="") + ":" + urlquote(os.environ["SCHOLARSCOPE_PG_PASSWORD"], safe="") + "@" + os.environ["SCHOLARSCOPE_PG_HOST"] + ":" + os.getenv("SCHOLARSCOPE_PG_PORT", "5432") + "/" + urlquote(os.environ["SCHOLARSCOPE_PG_DATABASE"], safe="")
        if not url:
            root.mkdir(parents=True, exist_ok=True)
            url = "sqlite:///" + str(root / "research.sqlite3")
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        kw: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if url in ("sqlite://", "sqlite:///:memory:"):
                kw["poolclass"] = StaticPool
        self.engine = create_engine(url, **kw)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def sqlite_integrity(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        self.meta = MetaData()
        self.project_table = Table("research_projects", self.meta,
            Column("id", String(40), primary_key=True),
            Column("owner", String(200), nullable=False, index=True),
            Column("title", String(500), nullable=False),
            Column("description", Text, nullable=False),
            Column("query", Text, nullable=False),
            Column("settings", JSON, nullable=False),
            Column("archived", Integer, nullable=False, default=0),
            Column("revision", Integer, nullable=False),
            Column("created_at", Float, nullable=False),
            Column("updated_at", Float, nullable=False))
        self.member_table = Table("research_members", self.meta,
            Column("project_id", String(40), ForeignKey("research_projects.id", ondelete="CASCADE"), primary_key=True),
            Column("username", String(200), primary_key=True),
            Column("role", String(20), nullable=False))
        self.item_table = Table("research_items", self.meta,
            Column("id", String(40), primary_key=True),
            Column("project_id", String(40), ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False, index=True),
            Column("kind", String(40), nullable=False, index=True),
            Column("label", String(500), nullable=False),
            Column("data", JSON, nullable=False),
            Column("revision", Integer, nullable=False),
            Column("created_at", Float, nullable=False),
            Column("updated_at", Float, nullable=False))
        self.event_table = Table("research_events", self.meta,
            Column("id", String(40), primary_key=True),
            Column("project_id", String(40), nullable=False, index=True),
            Column("actor", String(200), nullable=False),
            Column("action", String(100), nullable=False),
            Column("target", String(100), nullable=False),
            Column("data", JSON, nullable=False),
            Column("created_at", Float, nullable=False))
        self.meta.create_all(self.engine)
        from workspace.migrations import record_migration
        record_migration(self.engine, 1, "persistent projects, members, research items, audit events")

    @staticmethod
    def _row(row):
        return dict(row._mapping) if row is not None else None

    def _access(self, conn, project_id: str, actor: str, edit=False, manage=False):
        p = self._row(conn.execute(select(self.project_table).where(self.project_table.c.id == project_id)).first())
        if p is None:
            raise WorkspaceError("项目不存在", 404)
        role = "owner" if actor == p["owner"] else conn.execute(select(self.member_table.c.role).where(
            self.member_table.c.project_id == project_id, self.member_table.c.username == actor)).scalar()
        if not role:
            raise WorkspaceError("项目不存在或无访问权限", 404)
        if manage and role != "owner" or edit and role not in ("owner", "editor"):
            raise WorkspaceError("当前成员没有编辑权限", 403)
        p["role"] = role
        return p

    def _event(self, conn, pid, actor, action, target="", data=None):
        conn.execute(insert(self.event_table).values(id=ident(), project_id=pid, actor=actor,
            action=action, target=target, data=data or {}, created_at=time.time()))
        conn.execute(update(self.project_table).where(self.project_table.c.id == pid).values(updated_at=time.time()))

    def create_project(self, actor: str, title: str, description="", query="") -> dict:
        title = normalized(title)
        if not title or len(title) > 500:
            raise WorkspaceError("项目名称需为 1–500 个字符")
        p = dict(id=ident(), owner=actor, title=title, description=description[:10000], query=query[:10000],
                 settings={}, archived=0, revision=1, created_at=time.time(), updated_at=time.time())
        with self.engine.begin() as conn:
            conn.execute(insert(self.project_table).values(**p))
            self._event(conn, p["id"], actor, "project.created", p["id"])
        return {**p, "role": "owner"}

    def projects(self, actor: str, archived=False) -> list[dict]:
        with self.engine.connect() as conn:
            member_ids = select(self.member_table.c.project_id).where(self.member_table.c.username == actor)
            rows = conn.execute(select(self.project_table).where(
                (self.project_table.c.owner == actor) | self.project_table.c.id.in_(member_ids),
                self.project_table.c.archived == int(archived)).order_by(self.project_table.c.updated_at.desc())).all()
            result = []
            for row in rows:
                p = self._access(conn, row._mapping["id"], actor)
                p["counts"] = {kind: len(self._list(conn, p["id"], kind)) for kind in ("paper", "document", "evidence", "task", "artifact")}
                result.append(p)
            return result

    def project(self, project_id: str, actor: str) -> dict:
        with self.engine.connect() as conn:
            return self._access(conn, project_id, actor)

    def update_project(self, project_id, actor, data, revision) -> dict:
        with self.engine.begin() as conn:
            p = self._access(conn, project_id, actor, edit=True)
            if revision != p["revision"]:
                raise WorkspaceError("项目已被其他成员修改，请刷新后重试", 409)
            values = {k: data[k] for k in ("title", "description", "query", "settings", "archived") if k in data}
            if "title" in values and not normalized(values["title"]):
                raise WorkspaceError("项目名称不能为空")
            if "archived" in values and p["role"] != "owner":
                raise WorkspaceError("只有项目拥有者可以归档", 403)
            values.update(revision=p["revision"] + 1, updated_at=time.time())
            result = conn.execute(update(self.project_table).where(self.project_table.c.id == project_id,
                self.project_table.c.revision == revision).values(**values))
            if result.rowcount != 1:
                raise WorkspaceError("项目版本冲突", 409)
            self._event(conn, project_id, actor, "project.updated", project_id, {"fields": list(data)})
        return self.project(project_id, actor)

    def members(self, pid, actor):
        with self.engine.connect() as conn:
            p = self._access(conn, pid, actor)
            return [{"username": p["owner"], "role": "owner"}] + [self._row(r) for r in conn.execute(select(self.member_table.c.username, self.member_table.c.role).where(self.member_table.c.project_id == pid))]

    def set_member(self, pid, actor, username, role):
        if role not in ("editor", "viewer", "remove") or not username or username == "web-anonymous":
            raise WorkspaceError("请选择真实账号及编辑者/阅读者角色")
        with self.engine.begin() as conn:
            p = self._access(conn, pid, actor, manage=True)
            if username == p["owner"]:
                raise WorkspaceError("不能修改项目拥有者的角色")
            conn.execute(delete(self.member_table).where(self.member_table.c.project_id == pid, self.member_table.c.username == username))
            if role != "remove":
                conn.execute(insert(self.member_table).values(project_id=pid, username=username, role=role))
            self._event(conn, pid, actor, "member." + role, username)
        return self.members(pid, actor)

    def _list(self, conn, pid, kind=None):
        q = select(self.item_table).where(self.item_table.c.project_id == pid)
        if kind:
            q = q.where(self.item_table.c.kind == kind)
        return [self._row(r) for r in conn.execute(q.order_by(self.item_table.c.created_at.asc()))]

    def items(self, pid, actor, kind=None):
        with self.engine.connect() as conn:
            self._access(conn, pid, actor)
            return self._list(conn, pid, kind)

    def item(self, pid, actor, item_id, kind=None):
        with self.engine.connect() as conn:
            self._access(conn, pid, actor)
            row = self._row(conn.execute(select(self.item_table).where(self.item_table.c.project_id == pid,
                self.item_table.c.id == item_id)).first())
            if row is None or kind and row["kind"] != kind:
                raise WorkspaceError("项目资料不存在", 404)
            return row

    def put(self, pid, actor, kind, label, data, item_id=None, revision=None, *, creation_id=None):
        """Create/update an internally validated object with optimistic locking."""
        with self.engine.begin() as conn:
            self._access(conn, pid, actor, edit=True)
            old = self._row(conn.execute(select(self.item_table).where(self.item_table.c.id == item_id,
                self.item_table.c.project_id == pid)).first()) if item_id else None
            if item_id and old is None:
                raise WorkspaceError("项目资料不存在", 404)
            if old and (old["kind"] != kind or revision != old["revision"]):
                raise WorkspaceError("资料版本已变化，请重新加载后修改", 409)
            record = dict(id=item_id or creation_id or ident(), project_id=pid, kind=kind, label=label[:500], data=copy.deepcopy(data),
                          revision=old["revision"] + 1 if old else 1,
                          created_at=old["created_at"] if old else time.time(), updated_at=time.time())
            if old:
                result = conn.execute(update(self.item_table).where(self.item_table.c.id == item_id,
                    self.item_table.c.revision == revision).values(**record))
                if result.rowcount != 1:
                    raise WorkspaceError("资料版本冲突", 409)
            else:
                conn.execute(insert(self.item_table).values(**record))
            if kind in ("manuscript", "presentation"):
                conn.execute(insert(self.item_table).values(id=ident(), project_id=pid, kind=kind + "_version",
                    label=f"版本 {record['revision']}", data={kind + "_id": record["id"], "version": record["revision"],
                        "author": actor, "snapshot": copy.deepcopy(data)}, revision=1, created_at=time.time(), updated_at=time.time()))
            self._event(conn, pid, actor, kind + (".updated" if old else ".created"), record["id"], {"revision": record["revision"]})
            if old and kind in ("evidence", "chart"):
                self._invalidate(conn, pid, item_id)
            if old and kind in ("paper", "document"):
                keys = ("title", "abstract", "authors", "year", "doi") if kind == "paper" else ("sha256", "pages")
                if any(old["data"].get(k) != data.get(k) for k in keys):
                    for e in self._list(conn, pid, "evidence"):
                        if e["data"].get("paper_id" if kind == "paper" else "document_id") == item_id:
                            self._invalidate(conn, pid, e["id"])
            return record

    def remove(self, pid, actor, item_id):
        with self.engine.begin() as conn:
            self._access(conn, pid, actor, edit=True)
            old = self._row(conn.execute(select(self.item_table).where(self.item_table.c.id == item_id,
                self.item_table.c.project_id == pid)).first())
            if not old:
                raise WorkspaceError("项目资料不存在", 404)
            if old["kind"] in ("paper", "document", "chart", "collection"):
                dependents = [r for r in self._list(conn, pid) if r["data"].get("paper_id") == item_id or r["data"].get("document_id") == item_id or item_id in r["data"].get("chart_ids", []) or item_id in r["data"].get("collection_ids", [])]
                if dependents:
                    raise WorkspaceError("该来源仍被文档或证据引用，请先处理关联资料", 409)
            self._invalidate(conn, pid, item_id)
            conn.execute(delete(self.item_table).where(self.item_table.c.id == item_id))
            self._event(conn, pid, actor, old["kind"] + ".deleted", item_id)

    def _invalidate(self, conn, pid, evidence_id):
        for row in self._list(conn, pid):
            dependencies = row["data"].get("evidence_ids", [])
            if (evidence_id in dependencies or evidence_id in row["data"].get("chart_ids", [])) and row["kind"] in ("manuscript", "presentation", "artifact", "answer", "review", "chart"):
                data = {**row["data"], "stale": True, "stale_reason": "引用证据发生变化，请重新核对", "updated_evidence": evidence_id}
                conn.execute(update(self.item_table).where(self.item_table.c.id == row["id"]).values(
                    data=data, revision=row["revision"] + 1, updated_at=time.time()))

    def events(self, pid, actor, limit=100):
        with self.engine.connect() as conn:
            self._access(conn, pid, actor)
            return [self._row(r) for r in conn.execute(select(self.event_table).where(
                self.event_table.c.project_id == pid).order_by(self.event_table.c.created_at.desc()).limit(limit))]

    def add_paper(self, pid, actor, paper):
        if not normalized(paper.get("title", "")):
            raise WorkspaceError("文献必须有真实标题")
        aliases = paper_aliases(paper)
        old = next((r for r in self.items(pid, actor, "paper") if set(r["data"].get("aliases", [])) & set(aliases)), None)
        incoming_dois={a for a in aliases if a.startswith("doi:")}
        version_match=bool(old and old["data"].get("doi") and incoming_dois and
            not incoming_dois.intersection(paper_aliases({"doi":old["data"]["doi"]})))
        if not old:
            title_key=lambda value:re.sub(r"[^\w]","",normalized(value).casefold())
            authors={title_key(a) for a in paper.get("authors",[]) if str(a).strip()}
            if len(title_key(paper["title"]))>=40 and authors:
                old=next((r for r in self.items(pid,actor,"paper") if title_key(r["label"])==title_key(paper["title"])
                    and authors & {title_key(a) for a in r["data"].get("authors",[])}),None)
                version_match=bool(old)
        data = {**(old["data"] if old else {}), **{k: v for k, v in paper.items() if v not in (None, "", [])},
                "aliases": sorted(set(aliases + (old["data"].get("aliases", []) if old else [])))}
        if version_match:
            # Preserve the existing citation/source text; link the alternate
            # publication without silently replacing evidence with its abstract.
            versions=old["data"].get("related_versions",[])
            if not any(set(paper_aliases(v)) & set(aliases) for v in versions):
                versions=versions+[{k:paper[k] for k in ("doi","arxiv_id","title","year","authors","abstract","url") if paper.get(k)}]
            data={**old["data"],"aliases":data["aliases"],"related_versions":versions[:30]}
        data["abstract_hash"] = digest(data.get("abstract", ""))
        data.setdefault("tags", [])
        data.setdefault("screening", {})
        return self.put(pid, actor, "paper", data["title"], data, old["id"] if old else None, old["revision"] if old else None)

    def add_evidence(self, pid, actor, data, evidence_id=None, revision=None):
        """Validate a verbatim quote against its stored source and location."""
        quote = str(data.get("quote") or "").strip()
        if len(quote) < 3 or len(quote) > 12000:
            raise WorkspaceError("证据片段需为 3–12000 个字符的原文")
        paper = self.item(pid, actor, data.get("paper_id"), "paper")
        doc_id = data.get("document_id")
        page_number = data.get("page")
        if doc_id:
            doc = self.item(pid, actor, doc_id, "document")
            if doc["data"].get("paper_id") != paper["id"]:
                raise WorkspaceError("文档与文献不对应")
            page = next((p for p in doc["data"].get("pages", []) if p["number"] == page_number), None)
            if not page:
                raise WorkspaceError("证据页码不存在")
            text = page.get("text", "")
            location = {"document_id": doc_id, "page": page_number}
            scope = "fulltext"
        else:
            scope = data.get("scope", "abstract")
            if scope not in ("title", "abstract"):
                raise WorkspaceError("没有 PDF 的证据只能引用标题或摘要")
            text = str(paper["data"].get(scope, ""))
            location = {"scope": scope}
        if normalized(quote) not in normalized(text):
            raise WorkspaceError("证据片段不能在指定原文中核对")
        # Compute a location rather than trusting a client-supplied bounding box.
        start = normalized(text).index(normalized(quote))
        clean = {"paper_id": paper["id"], **location, "quote": quote,
                 "field": str(data.get("field", "finding"))[:100], "value": str(data.get("value", quote))[:12000],
                 "scope": scope, "source_hash": digest(text), "source_revision": paper["revision"],
                 "start": start, "end": start + len(normalized(quote)),
                 "offset_basis": "normalized_whitespace",
                 "validation": "quote_verified", "confirmed_by": actor if data.get("confirmed") else None,
                 "confirmed_at": time.time() if data.get("confirmed") else None,
                 "value_status": "extract" if normalized(str(data.get("value", quote))) in normalized(quote) else "interpretation",
                 "note": str(data.get("note", ""))[:5000]}
        if data.get("span_id") and doc_id:
            span = next((s for s in page.get("spans", []) if s.get("id") == data["span_id"]), None)
            if not span or normalized(quote) not in normalized(span.get("text", "")):
                raise WorkspaceError("指定文本位置与证据不符")
            clean.update(span_id=span["id"], bbox=span.get("bbox"))
        return self.put(pid, actor, "evidence", clean["field"], clean, evidence_id, revision)

    def verify_evidence(self, pid, actor, evidence_id):
        e = self.item(pid, actor, evidence_id, "evidence")
        d = e["data"]
        paper = self.item(pid, actor, d["paper_id"], "paper")
        if d.get("document_id"):
            doc = self.item(pid, actor, d["document_id"], "document")
            page = next((p for p in doc["data"].get("pages", []) if p["number"] == d.get("page")), {})
            text = page.get("text", "")
        else:
            text = paper["data"].get(d.get("scope", "abstract"), "")
        return {"evidence_id": e["id"], "valid": digest(text) == d["source_hash"] and normalized(d["quote"]) in normalized(text),
                "confirmed": bool(d.get("confirmed_by")), "scope": d["scope"], "location": {k: d[k] for k in ("page", "span_id", "bbox", "start", "end") if k in d}}


_store = None
_store_lock = threading.RLock()


def get_store() -> WorkspaceStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = WorkspaceStore()
        return _store
