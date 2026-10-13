"""DeepSeek LLM 客户端（OpenAI 兼容，统一封装）。"""

from __future__ import annotations

import os
import time

import requests

_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
_BASE_URL = os.getenv("SPAR2_LLM_BASE", "https://api.deepseek.com/v1/chat/completions")
_MODEL = os.getenv("SPAR2_LLM_MODEL", "deepseek-chat")


def chat(prompt: str, max_tokens: int = 1500, temperature: float = 0.0,
         retries: int = 2) -> str | None:
    """调用 DeepSeek chat；失败重试 retries 次，最终失败返回 None（静默降级）。"""
    if not _API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.post(_BASE_URL, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            pass
        if attempt < retries:
            time.sleep(1.0 + attempt)
    return None


def estimate_tokens(text: str) -> int:
    """粗略 token 估计（按 4 字符/token）。"""
    return max(1, len(text) // 4)
