"""Run reproducible acceptance checks and retain PASS/FAIL/BLOCKED evidence.

No production accounts or integration credentials are loaded by this runner.
Live research quality and private Zotero sync require a separate user session.
"""
import argparse
from datetime import datetime
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv/bin/python"
BROWSER_SCRIPTS = ("ui_smoke.js", "ui_landing.js", "ui_research.js", "ui_platform.js", "ui_accounts_settings.js")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/acceptance" / datetime.now().strftime("%Y-%m-%d-%H%M%S"))
    args = parser.parse_args(); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    checks = []
    with tempfile.TemporaryDirectory(prefix="scholarscope-acceptance-") as private:
        env = dict(os.environ)
        for key in list(env):
            if key.startswith(("SCHOLARSCOPE_S3", "SCHOLARSCOPE_PG")) or key in ("SAKURA_ADMIN_PASSWORD", "SAKURA_ADMIN_USER", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "GLM_API_KEY", "MOONSHOT_API_KEY", "OPENROUTER_API_KEY", "SILICONFLOW_API_KEY"):
                env.pop(key)
        env.update(SCHOLARSCOPE_DATA_DIR=private, SCHOLARSCOPE_WORKSPACE_DIR=private,
            SCHOLARSCOPE_DATABASE_URL="sqlite:///" + private + "/workspace.sqlite3",
            SCHOLARSCOPE_DISABLE_AI="1", SCHOLARSCOPE_DISABLE_EMBEDDINGS="1", PYTHONPATH=str(ROOT / "src"))

        def run(name, cmd, timeout=120):
            path = output / (name + ".log"); started = time.monotonic()
            with path.open("w") as log:
                try:
                    result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
                    state = "PASS" if result.returncode == 0 else "FAIL"
                except subprocess.TimeoutExpired:
                    state = "FAIL"; log.write("\nAcceptance step exceeded its time budget.\n")
            row = {"name": name, "status": state, "elapsed_seconds": round(time.monotonic() - started, 2), "evidence": path.name}
            checks.append(row); print(json.dumps(row, ensure_ascii=False), flush=True)
            return state

        run("python-regression", [str(PYTHON), "-m", "pytest", "src/tests/", "-q", "--junitxml=" + str(output / "regression.xml")], 240)
        build = run("production-build", ["node", "scripts/build_frontend.mjs"])
        run("inline-javascript", [str(PYTHON), "scripts/check_inline_js.py"])
        for script in BROWSER_SCRIPTS:
            run("syntax-" + script, ["node", "--check", "src/tests/" + script])

        # Only launch owned isolated servers when the execution environment permits listening.
        port = None
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
        except OSError:
            pass
        if port is None or build != "PASS":
            reason = "Execution environment denies local listening sockets" if port is None else "Production build failed"
            for script in BROWSER_SCRIPTS:
                checks.append({"name": script, "status": "BLOCKED", "reason": reason})
        else:
            base = "http://127.0.0.1:" + str(port); env["SCHOLARSCOPE_URL"] = base
            with (output / "isolated-server.log").open("w") as log:
                server = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", str(port)],
                    cwd=ROOT / "src", env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    import urllib.request
                    ready = False
                    for _ in range(60):
                        if server.poll() is not None: break
                        try:
                            with urllib.request.urlopen(base + "/api/health", timeout=.5) as response:
                                ready = response.status == 200
                            if ready: break
                        except OSError: time.sleep(.1)
                    if ready:
                        for script in BROWSER_SCRIPTS:
                            run(script, ["node", "src/tests/" + script], 180)
                    else:
                        checks.append({"name": "browser-suite", "status": "BLOCKED", "reason": "Isolated server did not start", "evidence": "isolated-server.log"})
                finally:
                    server.terminate()
                    try: server.wait(timeout=5)
                    except subprocess.TimeoutExpired: server.kill(); server.wait()

    junit = output / "regression.xml"
    cases = []
    if junit.exists():
        for node in ET.parse(junit).iter("testcase"):
            status = "FAIL" if node.find("failure") is not None or node.find("error") is not None else "BLOCKED" if node.find("skipped") is not None else "PASS"
            cases.append({"name": node.get("name"), "status": status, "elapsed_seconds": float(node.get("time", 0))})
    pending = [
        {"name": "live-search-coverage", "status": "BLOCKED", "reason": "Needs real network retrieval and relevance review; controlled regression is insufficient"},
        {"name": "live-model-semantic-quality", "status": "BLOCKED", "reason": "User reserved this check for their real API; this run deliberately disables model calls"},
        {"name": "private-zotero-library", "status": "BLOCKED", "reason": "Requires read verification in the user's connected session; runner never loads private integration keys"},
        {"name": "current-container-postgres-s3", "status": "BLOCKED", "reason": "This execution checks SQLite/local storage; previous container evidence does not certify current build"},
    ]
    checks += pending
    failed = any(r["status"] == "FAIL" for r in checks)
    blocked = any(r["status"] == "BLOCKED" for r in checks)
    status = "FAIL" if failed else "INCOMPLETE" if blocked else "PASS"
    report = {"date": datetime.now().astimezone().isoformat(), "status": status,
        "scope": "Isolated actual application/API and controlled regression; browser checks separately gated",
        "checks": checks, "cases": cases,
        "summary": {s: sum(r["status"] == s for r in cases) for s in ("PASS", "FAIL", "BLOCKED")},
        "checks_summary": {s: sum(r["status"] == s for r in checks) for s in ("PASS", "FAIL", "BLOCKED")},
        "user_journeys": [r for r in cases if re.match(r"test_u\d{2}_", r["name"])]}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    lines = ["# Acceptance execution evidence", "", "Date: " + report["date"], "", "Overall: **" + status + "**", "",
        "| Check | Result | Evidence / constraint |", "| --- | --- | --- |"]
    for r in checks:
        lines.append("| " + r["name"] + " | " + r["status"] + " | " + r.get("evidence", r.get("reason", "")) + " |")
    lines += ["", "## User journeys", "", "| Case | Result | Seconds |", "| --- | --- | --- |"]
    for r in report["user_journeys"]:
        lines.append(f'| {r["name"]} | {r["status"]} | {r["elapsed_seconds"]:.2f} |')
    (output / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"status": status, "summary": report["summary"], "checks_summary": report["checks_summary"], "report": str(output / "report.json")}, ensure_ascii=False))
    return 1 if failed else 2 if blocked else 0


if __name__ == "__main__": sys.exit(main())
