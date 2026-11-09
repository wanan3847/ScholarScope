#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包 Beta 版程序源代码（可运行程序 + 源码）用于参赛提交。

用法（仓库根目录）:
    .venv/bin/python 英迈云/scripts/package_beta.py

只打包源码与文档；排除虚拟环境、依赖目录、运行数据、模型权重与个人信息。
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "英迈云" / "提交材料" / "Beta版程序-研索ScholarScope-源代码.zip"

INCLUDE_DIRS = ["src", "frontend/src", "frontend/public", "docs", "scripts"]
INCLUDE_FILES = [
    "README.md",
    "compose.yaml",
    "compose.storage.yaml",
    "Dockerfile",
    "frontend/package.json",
    "frontend/index.html",
    "frontend/landing.html",
    ".env.example",
]

SKIP_PARTS = {"node_modules", "__pycache__", ".pytest_cache", ".git", ".venv",
              "data", "models", ".cache", "log", "dist", "build"}
SKIP_SUFFIX = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".so", ".dylib",
               ".zip", ".pt", ".bin", ".safetensors", ".pdf"}
SKIP_NAMES = {"llm_config.json", ".env", ".env.storage", ".DS_Store"}


def wanted(path: Path) -> bool:
    if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIX:
        return False
    return not (set(path.parts) & SKIP_PARTS)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for d in INCLUDE_DIRS:
            base = ROOT / d
            if not base.is_dir():
                continue
            for f in sorted(base.rglob("*")):
                if f.is_file() and wanted(f.relative_to(ROOT)):
                    z.write(f, f.relative_to(ROOT))
                    count += 1
        for name in INCLUDE_FILES:
            f = ROOT / name
            if f.is_file():
                z.write(f, name)
                count += 1
    size = OUT.stat().st_size / 1024 / 1024
    print(f"written: {OUT}  ({count} 个文件, {size:.1f} MB)")


if __name__ == "__main__":
    main()
