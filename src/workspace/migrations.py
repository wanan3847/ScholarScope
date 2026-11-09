"""Idempotent schema version records; migrations never erase runtime data."""
import time
from sqlalchemy import text


def record_migration(engine, version, name):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS research_schema_versions (version INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, applied_at DOUBLE PRECISION NOT NULL)"))
        conn.execute(text("INSERT INTO research_schema_versions (version,name,applied_at) VALUES (:v,:n,:at) ON CONFLICT (version) DO NOTHING"),
            {"v": version, "n": name, "at": time.time()})


def versions(engine):
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text("SELECT version,name,applied_at FROM research_schema_versions ORDER BY version"))]
