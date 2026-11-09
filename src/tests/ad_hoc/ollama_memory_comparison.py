"""Deferred, guarded 9B UI check after download, without changing user settings.

Only starts when no model is loaded, our check VM is stopped and macOS reports
normal pressure. Terminates its own test group and unloads its own 9B model on
sustained warning/critical pressure. Model files and other applications remain.
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from datetime import datetime,timezone
import httpx

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'.cache/ollama-9b-comparison'
OUT.mkdir(parents=True,exist_ok=True)
MODEL='qwen3.5:9b'
state={'model':MODEL,'status':'waiting_download','default_changed':False}


def checkpoint(status,**extra):
    state.update(status=status,updated_at=datetime.now(timezone.utc).isoformat(),**extra)
    (OUT/'status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))


def memory():
    r=subprocess.run(['sysctl','kern.memorystatus_vm_pressure_level','vm.swapusage'],capture_output=True,text=True,timeout=3)
    level=re.search(r'pressure_level:\s*(\d+)',r.stdout)
    swap=re.search(r'used\s*=\s*([\d.]+)M',r.stdout)
    return {'pressure_level':int(level.group(1)) if level else None,'swap_mb':float(swap.group(1)) if swap else None}


def local_api(path):
    with httpx.Client(timeout=5,trust_env=False) as client:
        r=client.get('http://127.0.0.1:11434'+path);r.raise_for_status();return r.json()


def vm_running():
    try:
        return subprocess.run(['colima','-p','scholarscope-check','status'],capture_output=True,timeout=5).returncode==0
    except FileNotFoundError:return False


def stop_test(process):
    if process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
    try:
        with httpx.Client(timeout=15,trust_env=False) as client:
            r=client.post('http://127.0.0.1:11434/api/generate',json={'model':MODEL,'keep_alive':0})
            state['unload_status']=r.status_code
    except Exception:state['unload_status']='request_failed'


deadline=time.monotonic()+6*3600
normal_since=None
checkpoint('waiting_download')
while time.monotonic()<deadline:
    try:
        downloaded=any(m['name']==MODEL for m in local_api('/api/tags')['models'])
        if not downloaded:
            normal_since=None;checkpoint('waiting_download');time.sleep(15);continue
        current=memory()
        if current['pressure_level']!=1 or local_api('/api/ps')['models'] or vm_running():
            normal_since=None;checkpoint('waiting_idle_memory',memory=current);time.sleep(15);continue
        normal_since=normal_since or time.monotonic()
        if time.monotonic()-normal_since<60:
            checkpoint('waiting_idle_memory',memory=current);time.sleep(15);continue
        break
    except Exception as e:
        checkpoint('waiting_local_service',error_type=type(e).__name__);time.sleep(15)
else:
    checkpoint('deferred_timeout',message='Download/idle prerequisites were not met; no model was loaded.')
    raise SystemExit(0)

checkpoint('testing',baseline_memory=memory())
env={**os.environ,'SCHOLARSCOPE_EVAL_MODEL':MODEL,'SCHOLARSCOPE_EVAL_OUTPUT':'ui-real-ai-9b-8k'}
warning_since=None
started=time.monotonic()
with tempfile.TemporaryDirectory(prefix='research-memory-check-') as directory,(OUT/'test.log').open('w') as log:
    env['SCHOLARSCOPE_EVAL_TEMP_ROOT']=directory
    process=subprocess.Popen(['node','src/tests/ad_hoc/ui_real_ai.js'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
    try:
        while process.poll() is None:
            current=memory()
            state['latest_memory']=current
            if current['pressure_level'] is None:raise RuntimeError('Memory pressure unavailable')
            warning_since=(warning_since or time.monotonic()) if current['pressure_level']>=2 else None
            if current['pressure_level']>=4 or warning_since and time.monotonic()-warning_since>=20:
                checkpoint('memory_limited',message='Stopped the 9B test on sustained memory pressure; default 4B retained.')
                stop_test(process);break
            if time.monotonic()-started>900:
                checkpoint('test_timeout');stop_test(process);break
            checkpoint('testing');time.sleep(2)
        else:
            code=process.returncode
            stop_test(process)
            report=ROOT/'.cache/ui-real-ai-9b-8k/report.json'
            checkpoint('tested' if code==0 else 'test_failed',exit_code=code,
                report=json.loads(report.read_text()) if report.exists() else {})
    except BaseException:
        stop_test(process);checkpoint('interrupted');raise
checkpoint(state['status'],final_memory=memory(),seconds=round(time.monotonic()-started,1))
