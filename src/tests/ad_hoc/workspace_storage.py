"""Real PostgreSQL/pgvector and S3 gateway smoke, all data in temporary dirs."""
from __future__ import annotations
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workspace.store import WorkspaceStore, WorkspaceError
from workspace.documents import ObjectStore, attach_pdf
from workspace.knowledge import ProjectIndex
from sqlalchemy import text


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


pg_bin = Path(os.getenv("SCHOLARSCOPE_TEST_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
weed = shutil.which("weed")
if not (pg_bin / "initdb").exists() or not weed:
    raise SystemExit("Install PostgreSQL with pgvector and SeaweedFS before this real integration check.")
with tempfile.TemporaryDirectory(prefix="scholarscope-storage-") as tmp:
    root = Path(tmp); cluster = root / "pg"; socket_dir = root / "socket"; socket_dir.mkdir(); objects = root / "s3"; objects.mkdir()
    pg_port, s3_port = free_port(), free_port()
    master_port, volume_port, filer_port = free_port(), free_port(), free_port()
    private_key, private_secret = secrets.token_hex(12), secrets.token_hex(24)
    config = root / "s3-config.json"
    config.write_text(json.dumps({"identities": [{"name": "research-test", "credentials": [{"accessKey": private_key, "secretKey": private_secret}], "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}))
    config.chmod(0o600)
    subprocess.run([str(pg_bin / "initdb"), "-D", str(cluster), "--auth-local=trust", "--auth-host=trust", "--username=research_test", "--encoding=UTF8", "--locale=C"], check=True, capture_output=True)
    processes = []
    storage_log = (root / "storage.log").open("w+")
    try:
        pg = subprocess.Popen([str(pg_bin / "postgres"), "-D", str(cluster), "-h", "127.0.0.1", "-p", str(pg_port), "-k", str(socket_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); processes.append(pg)
        s3 = subprocess.Popen([weed, "server", "-dir=" + str(objects), "-ip=127.0.0.1", "-ip.bind=127.0.0.1", "-master.port=" + str(master_port), "-master.port.grpc=" + str(free_port()), "-volume.port=" + str(volume_port), "-volume.port.grpc=" + str(free_port()), "-filer", "-filer.port=" + str(filer_port), "-filer.port.grpc=" + str(free_port()), "-s3", "-s3.port=" + str(s3_port), "-s3.port.grpc=" + str(free_port()), "-s3.port.iceberg=0", "-s3.port.lance=0", "-s3.config=" + str(config), "-volume.max=1", "-volume.preStopSeconds=0", "-master.telemetry=false"], stdout=storage_log, stderr=storage_log); processes.append(s3)
        import psycopg
        import boto3
        from botocore.config import Config
        uri = f"postgresql://research_test@127.0.0.1:{pg_port}/postgres"
        s3_client = boto3.client("s3", endpoint_url=f"http://127.0.0.1:{s3_port}", aws_access_key_id=private_key, aws_secret_access_key=private_secret,
            config=Config(connect_timeout=1, read_timeout=2, retries={"total_max_attempts": 1}, s3={"addressing_style": "path"}, proxies={}))
        ready = False
        for _ in range(80):
            try:
                with psycopg.connect(uri, connect_timeout=1) as conn: conn.execute("SELECT 1")
                s3_client.list_buckets(); ready = True; break
            except Exception:
                if any(p.poll() is not None for p in processes):
                    storage_log.flush(); storage_log.seek(0)
                    diagnostic = storage_log.read()[-2500:].replace(private_key, "[redacted]").replace(private_secret, "[redacted]")
                    raise RuntimeError("Temporary storage server failed to start: " + diagnostic)
                time.sleep(.25)
        assert ready, "Temporary PostgreSQL/S3 servers not ready"
        bucket = "research-workspace-test"; s3_client.create_bucket(Bucket=bucket)
        store = WorkspaceStore(uri)
        p = store.create_project("alice", "Real storage integration")
        paper = store.add_paper(p["id"], "alice", {"title": "Controlled multilingual well-log source", "abstract": "A neural network predicts porosity and permeability from well logs. The dataset contains 120 samples."})
        from reportlab.pdfgen.canvas import Canvas
        pdf = io.BytesIO(); canvas = Canvas(pdf); canvas.drawString(50, 750, "The dataset contains 120 samples."); canvas.save()
        object_store = ObjectStore(root, bucket=bucket, client=s3_client)
        doc = attach_pdf(store, object_store, p["id"], "alice", paper["id"], "controlled.pdf", pdf.getvalue())
        assert object_store.get(doc["data"]["object_key"]) == pdf.getvalue()
        ev = store.add_evidence(p["id"], "alice", {"paper_id": paper["id"], "document_id": doc["id"], "page": 1, "quote": "The dataset contains 120 samples."})
        index = ProjectIndex(store)
        result = index.retrieve(p["id"], "alice", "利用测井数据预测储层孔隙度与渗透率")
        assert result["mode"] == "semantic_hybrid" and result["passages"]
        assert result["passages"][0]["paper_id"] == paper["id"]
        with store.engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM research_chunks WHERE embedding IS NOT NULL")).scalar() > 0
            assert conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar() == "vector"
        reopened = WorkspaceStore(uri)
        assert reopened.verify_evidence(p["id"], "alice", ev["id"])["valid"]
        assert ProjectIndex(reopened).retrieve(p["id"], "alice", "porosity dataset")["passages"]
        try:
            reopened.project(p["id"], "bob"); raise AssertionError("Project isolation failed")
        except WorkspaceError as error: assert error.status == 404
        # Verify that bytes actually reside in the S3 server, not the local adapter.
        assert s3_client.head_object(Bucket=bucket, Key=doc["data"]["object_key"])["ContentLength"] == len(pdf.getvalue())
        assert not (root / "objects").exists()
        from workspace.backup import backup_archive, restore_archive
        backup = root / "backup.zip"
        backup_archive(store, object_store, backup)
        with psycopg.connect(uri, autocommit=True) as conn:
            conn.execute("CREATE DATABASE research_restore OWNER research_test")
        restored = WorkspaceStore(uri.replace("/postgres", "/research_restore"))
        restored_objects = ObjectStore(root / "restore")
        restore_archive(restored, restored_objects, backup)
        assert restored.verify_evidence(p["id"], "alice", ev["id"])["valid"]
        assert restored_objects.get(doc["data"]["object_key"]) == pdf.getvalue()
        assert ProjectIndex(restored).retrieve(p["id"], "alice", "孔隙度预测")["passages"]
        print(json.dumps({"status": "PASS", "checks": ["PostgreSQL real transactions", "pgvector extension and persisted 384-dimension embeddings", "Chinese/English semantic retrieval", "real authenticated S3 gateway PDF put/get", "source verification", "reopened store/index", "project isolation", "private full backup and restore to new PostgreSQL DB/local objects"]}, ensure_ascii=False, indent=2))
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=8)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        storage_log.close()
