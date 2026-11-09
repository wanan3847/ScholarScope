"""Account-scoped encrypted integration records, outside shared project data."""
import contextlib
import fcntl
import json
import os
import tempfile
import threading
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from workspace.store import WorkspaceError, digest

_lock = threading.RLock()


class IntegrationVault:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv("SCHOLARSCOPE_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
        self.root.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def locked(self, name="vault"):
        path = self.root / ("integrations-" + name + ".lock")
        with (_lock if name == "vault" else contextlib.nullcontext()), open(path, "a+b") as file:
            os.chmod(path, 0o600)
            fcntl.flock(file, fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(file, fcntl.LOCK_UN)

    def _cipher(self):
        path = self.root / "integrations.key"
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as file: file.write(Fernet.generate_key())
        try: return Fernet(path.read_bytes())
        except (ValueError, OSError): raise WorkspaceError("集成密钥文件不可用，请从完整备份恢复", 503) from None

    def _read(self):
        path = self.root / "integrations.json"
        if not path.exists(): return {}
        try: return json.loads(self._cipher().decrypt(path.read_bytes()))
        except (InvalidToken, ValueError): raise WorkspaceError("集成配置无法解密，请从完整备份恢复", 503) from None

    def get(self, actor, pid):
        with self.locked(): return self._read().get(digest(actor + ":" + pid))

    def put(self, actor, pid, record):
        with self.locked():
            data = self._read(); key = digest(actor + ":" + pid)
            if record is None: data.pop(key, None)
            else: data[key] = record
            blob = self._cipher().encrypt(json.dumps(data, ensure_ascii=False).encode())
            fd, name = tempfile.mkstemp(prefix="integrations-", dir=self.root)
            try:
                with os.fdopen(fd, "wb") as file: file.write(blob); file.flush(); os.fsync(file.fileno())
                os.replace(name, self.root / "integrations.json")
            finally:
                if os.path.exists(name): os.unlink(name)

    def connection_lock(self, actor, pid):
        return self.locked(digest(actor + ":" + pid)[:32])
