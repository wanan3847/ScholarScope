#!/usr/bin/env python3
"""Local migration/backup/restore CLI; connection credentials come from env."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from workspace.store import WorkspaceStore, WorkspaceError
from workspace.documents import ObjectStore
from workspace.knowledge import ProjectIndex
from workspace.backup import backup_archive, restore_archive
from workspace.migrations import versions

parser = argparse.ArgumentParser(description="ScholarScope workspace administration")
sub = parser.add_subparsers(dest="command", required=True)
sub.add_parser("migrate")
backup = sub.add_parser("backup"); backup.add_argument("output")
restore = sub.add_parser("restore"); restore.add_argument("source")
args = parser.parse_args()
try:
    store = WorkspaceStore()
    runtime = Path(os.getenv("SCHOLARSCOPE_DATA_DIR", Path(__file__).resolve().parents[1] / "src" / "data"))
    if args.command == "migrate":
        ProjectIndex(store)
        result = {"schema_versions": versions(store.engine)}
    elif args.command == "backup": result = backup_archive(store, ObjectStore(), args.output, runtime)
    else: result = restore_archive(store, ObjectStore(), args.source, runtime)
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2))
except WorkspaceError as e:
    print(json.dumps({"status": "error", "detail": str(e)}, ensure_ascii=False)); sys.exit(1)
except Exception:
    print(json.dumps({"status": "error", "detail": "管理操作失败，请检查连接、空目标和文件权限；未输出连接凭据。"}, ensure_ascii=False)); sys.exit(1)
