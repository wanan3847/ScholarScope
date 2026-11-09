#!/usr/bin/env python3
"""Bounded storage initialization, migrations and one supervised API worker."""
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def prepare_storage():
    deadline = time.monotonic() + 60
    while True:
        try:
            from workspace.store import WorkspaceStore
            from workspace.knowledge import ProjectIndex
            from workspace.documents import ObjectStore
            store = WorkspaceStore(); ProjectIndex(store); store.engine.dispose()
            objects = ObjectStore()
            if objects.bucket:
                from botocore.exceptions import ClientError
                try: objects.client.head_bucket(Bucket=objects.bucket)
                except ClientError as error:
                    if str(error.response.get("Error", {}).get("Code")) not in ("404", "NoSuchBucket"): raise
                    objects.client.create_bucket(Bucket=objects.bucket)
            return
        except Exception:
            if time.monotonic() >= deadline:
                raise RuntimeError("Storage initialization timed out; verify private storage settings.") from None
            time.sleep(1)


if __name__ == "__main__":
    try: prepare_storage()
    except RuntimeError as error:
        print(str(error), file=sys.stderr); sys.exit(1)
    os.execvp(sys.executable, [sys.executable, "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8765", "--no-access-log"])
