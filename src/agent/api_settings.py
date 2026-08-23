"""外部 API 配置（OpenAlex / Semantic Scholar）的本地持久化。

设置面板写入 src/data/api_config.json；检索后端构造时优先读取该文件，
未配置的项回退到 .env / 环境变量。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

_CONFIG_FILE = Path(__file__).resolve().parent.parent / "data" / "api_config.json"


def load_api_config() -> Dict[str, str]:
    """读取 API 配置。键：openalex_key / openalex_email / s2_key。"""
    if not _CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        return {k: str(v) for k, v in data.items() if v}
    except (json.JSONDecodeError, OSError):
        return {}


def save_api_config(openalex_key: Optional[str] = None,
                    openalex_email: Optional[str] = None,
                    s2_key: Optional[str] = None) -> Dict[str, str]:
    """保存 API 配置。

    字段语义：None=保持不变；空字符串=清除；非空=覆盖。
    返回实际生效的配置。
    """
    cfg = load_api_config()
    for key, val in (("openalex_key", openalex_key),
                     ("openalex_email", openalex_email),
                     ("s2_key", s2_key)):
        if val is None:
            continue
        val = str(val).strip()
        if val:
            cfg[key] = val
        else:
            cfg.pop(key, None)
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:  # pragma: no cover
        raise RuntimeError(f"保存 API 配置失败: {e}") from e
    return cfg


def get_api_setting(key: str, env_name: str, default: str = "") -> str:
    """优先取界面配置，其次环境变量。"""
    cfg = load_api_config()
    return cfg.get(key) or os.getenv(env_name, "") or default


def mask_key(value: Optional[str]) -> str:
    """脱敏展示：只留前后各 2 位。"""
    v = value or ""
    if len(v) <= 6:
        return "******" if v else ""
    return v[:2] + "****" + v[-2:]
