#!/usr/bin/env python3
"""等 OpenAlex/S2 免费额度重置（北京时间 08:00）后自动启动 real_scholar 评测。

守护化（双 fork + setsid）：启动后父进程立即退出，评测在 08:00:15 由
子进程拉起，即使终端/会话被中断也不受影响。
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
import time

SRC = "/Users/yangyazhou/SakuraPaper/src"
PY = "/Users/yangyazhou/miniconda3/bin/python"
OUT = "/Users/yangyazhou/SakuraPaper/results/2026-08-22"


def daemonize() -> None:
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    os.chdir(SRC)
    sys.stdout.flush()


def main() -> None:
    daemonize()
    now = datetime.datetime.now()
    target = now.replace(hour=8, minute=0, second=15, microsecond=0)
    if now >= target:
        target = now + datetime.timedelta(seconds=3)
    time.sleep(max(0.0, (target - now).total_seconds()))

    jobs = [
        (["run_eval.py", "--n", "50", "--benchmarks", "real_scholar",
          "--engine", "spar2", "--real", "--llm", "ollama",
          "--output", f"{OUT}/real_scholar_50_qwen3.json"],
         "/tmp/real50_qwen3.log",
         {"SAKURA_LLM_PROVIDER": "ollama", "SPAR2_DEADLINE": "170"}),
        (["run_eval.py", "--n", "20", "--benchmarks", "real_scholar",
          "--engine", "spar2", "--real", "--llm", "deepseek",
          "--output", f"{OUT}/real_scholar_20_deepseek.json"],
         "/tmp/real20_deepseek.log",
         {"SPAR2_DEADLINE": "170"}),
    ]
    for args, log, extra_env in jobs:
        env = dict(os.environ)
        env.update(extra_env)
        with open(log, "a") as f:
            f.write(f"\n=== restarted by daemon at "
                    f"{datetime.datetime.now():%H:%M:%S} ===\n")
        subprocess.Popen(
            [PY] + args, cwd=SRC, env=env,
            stdout=open(log, "a"), stderr=subprocess.STDOUT,
        )
    with open("/tmp/evals_started.log", "a") as f:
        f.write(f"started at {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")


if __name__ == "__main__":
    main()
