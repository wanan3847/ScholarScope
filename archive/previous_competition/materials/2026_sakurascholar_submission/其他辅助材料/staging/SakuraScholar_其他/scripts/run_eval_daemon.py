#!/usr/bin/env python3
"""通用 run_eval 守护启动器：双 fork + setsid 脱离终端，防止后台评测被误杀。

用法：
    python scripts/run_eval_daemon.py --n 20 --benchmarks real_scholar \
        --engine spar2 --real --llm ollama \
        --output /abs/out.json --log /tmp/eval.log

环境变量（如 SAKURA_LLM_PROVIDER）继承自启动它的 shell。
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys

SRC = "/Users/yangyazhou/SakuraPaper/src"
PY = "/Users/yangyazhou/miniconda3/bin/python"


def daemonize() -> None:
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    os.chdir(SRC)


def main() -> None:
    argv = list(sys.argv[1:])
    log = "/tmp/run_eval_daemon.log"
    for i, a in enumerate(argv):
        if a == "--log" and i + 1 < len(argv):
            log = argv[i + 1]
            argv = argv[:i] + argv[i + 2:]
            break
    daemonize()
    cmd = [PY, "run_eval.py"] + argv
    env = dict(os.environ)
    with open(log, "a") as f:
        f.write(f"\n=== daemon start {datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
                f"({' '.join(argv)}) ===\n")
    subprocess.Popen(cmd, cwd=SRC, env=env,
                     stdout=open(log, "a"), stderr=subprocess.STDOUT)


if __name__ == "__main__":
    main()
