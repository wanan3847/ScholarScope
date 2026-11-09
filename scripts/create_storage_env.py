#!/usr/bin/env python3
"""Create a private Compose storage env file; never print credentials."""
import os
import secrets
import sys
from pathlib import Path
path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env.storage")
fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, "w") as file:
    for name in ("SCHOLARSCOPE_PG_PASSWORD", "SCHOLARSCOPE_S3_ACCESS_KEY", "SCHOLARSCOPE_S3_SECRET_KEY"):
        file.write(name + "=" + secrets.token_hex(24) + "\n")
print("Created private storage configuration: " + str(path))
