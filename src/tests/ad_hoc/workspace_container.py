"""Actual container API, private objects, process restart and portable recovery.

Run against a dedicated Compose test project, never a user's existing project.
Credentials exist only in this process and the private temporary test volume.
"""
import io
import json
import os
import secrets
import subprocess
import sys
import time
import zipfile
from pathlib import Path
import requests
from reportlab.pdfgen.canvas import Canvas

base = os.getenv("SCHOLARSCOPE_CONTAINER_URL", "http://127.0.0.1:18870")
container = os.getenv("SCHOLARSCOPE_TEST_CONTAINER", "scholarscope-check-app-1")
docker = ["docker"]
repo = Path(__file__).resolve().parents[3]


def command(args):
    result = subprocess.run(docker + args, capture_output=True, text=True, timeout=90)
    if result.returncode: raise RuntimeError("Container command failed: " + args[0])
    return result.stdout


def wait_health():
    deadline = time.monotonic() + 65
    while time.monotonic() < deadline:
        try:
            if requests.get(base + "/api/health", timeout=1).status_code == 200: return
        except requests.RequestException: pass
        time.sleep(.3)
    raise RuntimeError("Container did not become healthy")


wait_health()
username = "container-check-" + secrets.token_hex(4); password = secrets.token_hex(16)
response = requests.post(base + "/api/auth/register", json={"username": username, "password": password}, timeout=5)
response.raise_for_status(); assert response.json()["status"] == "ok"
response = requests.post(base + "/api/auth/login", json={"username": username, "password": password}, timeout=5)
response.raise_for_status(); token = response.json()["token"]
session = requests.Session(); session.headers["Authorization"] = "Bearer " + token


def api(path, data=None, method=None):
    response = session.request(method or ("POST" if data is not None else "GET"), base + path, json=data, timeout=65)
    response.raise_for_status(); return response.json()


project = api("/api/workspace/projects", {"title": "Controlled container integration", "query": "neural permeability well logs"})
root = "/api/workspace/projects/" + project["id"]
paper = api(root + "/papers", {"paper": {"title": "Controlled container PDF source", "doi": "10.1000/container-" + secrets.token_hex(4), "abstract": "A neural network predicts permeability from well logs. The dataset contains 120 samples. The model achieves RMSE of 0.08."}})
out = io.BytesIO(); c = Canvas(out); c.drawString(40, 740, "A neural network predicts permeability from well logs."); c.drawString(40, 720, "The dataset contains 120 samples."); c.save()
response = session.post(base + root + "/papers/" + paper["id"] + "/pdf", files={"file": ("controlled.pdf", out.getvalue(), "application/pdf")}, timeout=60)
response.raise_for_status(); document = response.json()
file = session.get(base + root + "/documents/" + document["id"] + "/file", timeout=8)
assert file.content == out.getvalue()
assert requests.get(base + root + "/documents/" + document["id"] + "/file", timeout=3).status_code == 404
task = api(root + "/tasks", {"title": "Actual container tools"})


def wait_task(status):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        row = next(t for t in api(root + "/tasks")["tasks"] if t["id"] == task["id"])
        if row["data"]["status"] == status: return row
        if row["data"]["status"] == "failed": raise RuntimeError("Container task failed: " + row["data"]["message"])
        time.sleep(.4)
    raise RuntimeError("Container task did not reach " + status)


checkpoint = wait_task("awaiting_confirmation")
command(["restart", container]); wait_health()
assert next(t for t in api(root + "/tasks")["tasks"] if t["id"] == task["id"])["data"]["status"] == "awaiting_confirmation"
api(root + "/tasks/" + task["id"] + "/approve", {})
finished = wait_task("completed")
artifacts = api(root + "/items?kind=artifact")["items"]
assert len(artifacts) == 2
for artifact in artifacts:
    response = session.get(base + root + "/artifacts/" + artifact["id"] + "/file", timeout=15)
    response.raise_for_status()
    if artifact["data"]["format"] == "docx":
        from docx import Document
        assert Document(io.BytesIO(response.content)).paragraphs
    else:
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            import re
            assert len([n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]) == 12
assert command(["inspect", "--format", "{{.Config.User}} {{.HostConfig.ReadonlyRootfs}}", container]).strip() == "researcher true"
file = session.get(base + root + "/documents/" + document["id"] + "/file", timeout=8); assert file.content == out.getvalue()
backup = "/tmp/container-" + secrets.token_hex(6) + ".zip"
backup_result = json.loads(command(["exec", container, "python", "/app/scripts/workspace_admin.py", "backup", backup]))
assert backup_result["projects"] >= 1 and backup_result["objects"] >= 3
backup_path = repo / ".cache" / (Path(backup).name)
exported = subprocess.run(docker + ["exec", container, "python", "-c", "import sys;sys.stdout.buffer.write(open(sys.argv[1],'rb').read())", backup], capture_output=True, check=True, timeout=30)
fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, "wb") as file: file.write(exported.stdout)
recovery = "scholarscope-recovery-check-" + secrets.token_hex(4)
volume = recovery + "-data"
try:
    command(["run", "-d", "--name", recovery, "--read-only", "--tmpfs", "/tmp:size=512m,mode=1777", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--mount", "type=volume,source=" + volume + ",target=/data", "-p", "127.0.0.1::8765", "scholarscope:check"])
    endpoint = command(["port", recovery, "8765/tcp"]).strip().splitlines()[0]
    base = "http://" + endpoint; wait_health()
    subprocess.run(docker + ["exec", "-i", recovery, "python", "-c", "import sys;open('/tmp/restore.zip','wb').write(sys.stdin.buffer.read())"], input=exported.stdout, capture_output=True, check=True, timeout=30)
    restored = json.loads(command(["exec", recovery, "python", "/app/scripts/workspace_admin.py", "restore", "/tmp/restore.zip"]))
    assert restored["projects"] == backup_result["projects"]
    assert api(root)["id"] == project["id"]
    assert session.get(base + root + "/documents/" + document["id"] + "/file", timeout=8).content == out.getvalue()
    assert next(t for t in api(root + "/tasks")["tasks"] if t["id"] == task["id"])["data"]["status"] == "completed"
finally:
    subprocess.run(docker + ["rm", "-f", recovery], capture_output=True)
    subprocess.run(docker + ["volume", "rm", volume], capture_output=True)
print(json.dumps({"status": "PASS", "project_id": project["id"], "backup_path": str(backup_path),
    "checks": ["non-root read-only container", "actual authenticated project/PDF API", "private PDF object", "bounded real task subprocesses", "confirmation checkpoint survives container restart", "actual DOCX and 12-slide native PPTX", "private database/object/account backup", "restore to new container/SQLite/local objects with original session and completed task"],
    "backup_counts": {k: backup_result[k] for k in ("projects", "items", "objects")}}, ensure_ascii=False, indent=2))
