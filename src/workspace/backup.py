"""Portable database/object backups. Restore only to an empty destination."""
import json
import os
import time
import zipfile
import hashlib
import re
from pathlib import Path
from sqlalchemy import insert, select, text
from workspace.store import WorkspaceError, digest
from workspace.documents import ObjectStore
from workspace.knowledge import ProjectIndex

ORDER = ("research_projects", "research_members", "research_items", "research_events", "research_chunks")
RUNTIME_FILES = ("users.json", "collections.json", "read_papers.json", "paper_cache.json", "llm_config.json", "api_config.json", "integrations.json", "integrations.key")


def dump_database(store):
    index = ProjectIndex(store)
    tables = {**store.meta.tables, "research_chunks": index.table}
    with store.engine.connect() as conn:
        if store.engine.dialect.name == "postgresql":
            conn = conn.execution_options(isolation_level="REPEATABLE READ")
        with conn.begin():
            result = {}
            for name in ORDER:
                rows = [dict(r._mapping) for r in conn.execute(select(tables[name]))]
                for row in rows:
                    if row.get("embedding") is not None and hasattr(row["embedding"], "tolist"):
                        row["embedding"] = row["embedding"].tolist()
                result[name] = rows
            return {"format": "scholarscope-workspace-backup", "version": 1, "created_at": time.time(), "tables": result}


def restore_database(store, data):
    if data.get("format") != "scholarscope-workspace-backup" or data.get("version") != 1:
        raise WorkspaceError("备份格式不兼容")
    table_data = data.get("tables", {})
    if set(table_data) != set(ORDER):
        raise WorkspaceError("备份缺少必要数据表")
    index = ProjectIndex(store)
    tables = {**store.meta.tables, "research_chunks": index.table}
    with store.engine.begin() as conn:
        if any(conn.execute(select(tables[n]).limit(1)).first() for n in ORDER):
            raise WorkspaceError("恢复目标不是空数据库；请使用新的目标，避免覆盖现有资料", 409)
        for name in ORDER:
            rows = table_data[name]
            if rows:
                conn.execute(insert(tables[name]), rows)
        if store.engine.dialect.name == "sqlite":
            for r in table_data["research_chunks"]:
                conn.execute(text("INSERT INTO research_chunks_fts(id,project_id,text) VALUES (:id,:pid,:text)"), {"id": r["id"], "pid": r["project_id"], "text": r["text"]})


def backup_archive(store, objects, output, runtime_dir=None):
    output = Path(output)
    if output.exists():
        raise WorkspaceError("备份目标已存在，请使用新的文件名", 409)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = dump_database(store)
    keys = sorted({r["data"]["object_key"] for r in snapshot["tables"]["research_items"] if r["kind"] in ("document", "artifact") and r["data"].get("object_key")})
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as file, zipfile.ZipFile(file, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("database.json", json.dumps(snapshot, ensure_ascii=False))
            for key in keys:
                archive.writestr("objects/" + key, objects.get(key))
            if runtime_dir:
                root = Path(runtime_dir)
                for name in RUNTIME_FILES:
                    source = root / name
                    if source.exists(): archive.writestr("runtime/" + name, source.read_bytes())
        return {"projects": len(snapshot["tables"]["research_projects"]), "items": len(snapshot["tables"]["research_items"]), "objects": len(keys)}
    except Exception:
        output.unlink(missing_ok=True)
        raise


def restore_archive(store, objects, source, runtime_dir=None):
    root = Path(runtime_dir) if runtime_dir else None
    with zipfile.ZipFile(source) as archive:
        if sum(info.file_size for info in archive.infolist()) > 5 * 1024**3:
            raise WorkspaceError("备份超过本次恢复预算")
        if len(archive.namelist()) != len(set(archive.namelist())) or any(i.file_size > 100 * 1024**2 for i in archive.infolist()):
            raise WorkspaceError("备份含重复条目或单文件超过恢复预算")
        if root and any((root / n).exists() for n in RUNTIME_FILES):
            raise WorkspaceError("目标运行目录已有账号或配置，请使用空目录", 409)
        data = json.loads(archive.read("database.json"))
        # Check empty DB and archive objects before making any destination writes.
        for name in ORDER[:4]:
            with store.engine.connect() as conn:
                if conn.execute(select(store.meta.tables[name]).limit(1)).first():
                    raise WorkspaceError("恢复目标不是空数据库", 409)
        keys = {r["data"]["object_key"] for r in data["tables"]["research_items"] if r["kind"] in ("document", "artifact") and r["data"].get("object_key")}
        for key in keys:
            if not re.fullmatch(r"[a-f0-9]{2}/[a-f0-9]{64}\.[a-z0-9]{1,10}", key): raise WorkspaceError("备份对象标识无效")
            hasher = hashlib.sha256()
            with archive.open("objects/" + key) as file:
                while block := file.read(65536): hasher.update(block)
            if hasher.hexdigest() != key.split("/")[1].split(".")[0]:
                raise WorkspaceError("备份文件完整性验证失败")
        vault_entries = {n for n in ("integrations.json", "integrations.key") if "runtime/" + n in archive.namelist()}
        if vault_entries and len(vault_entries) != 2: raise WorkspaceError("集成凭据备份不完整")
        if vault_entries:
            from cryptography.fernet import Fernet, InvalidToken
            try: json.loads(Fernet(archive.read("runtime/integrations.key")).decrypt(archive.read("runtime/integrations.json")))
            except (InvalidToken, ValueError): raise WorkspaceError("集成凭据备份无法核验") from None
        for key in keys:
            blob = archive.read("objects/" + key)
            saved = objects.put(blob, key.rsplit(".", 1)[1])
            if saved["object_key"] != key: raise WorkspaceError("对象恢复校验失败")
        restore_database(store, data)
        if root:
            root.mkdir(parents=True, exist_ok=True)
            for name in RUNTIME_FILES:
                entry = "runtime/" + name
                if entry in archive.namelist():
                    target = root / name; target.write_bytes(archive.read(entry)); target.chmod(0o600)
        return {"projects": len(data["tables"]["research_projects"]), "objects": len(keys)}
