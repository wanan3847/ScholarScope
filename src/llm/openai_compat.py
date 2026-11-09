"""
OpenAI 兼容 API 预设。

统一管理各云端 LLM 提供商的 base_url、默认模型、API key 环境变量。
所有预设都走 OpenAI 兼容接口，可由 router._chat_openai_compat 直接调用。

支持的提供商：
    - openai:   GPT-4o-mini / GPT-4.1
    - deepseek: DeepSeek Flash / V4 Pro
    - qwen_api: 通义千问
    - glm:      智谱 GLM
    - moonshot: Kimi K2.6 / K3
    - ollama:   本地 Ollama（特殊处理，走原生接口）

使用：
    from llm.openai_compat import PRESETS, list_presets
    preset = PRESETS["deepseek"]
    # base_url, model, env_key
"""

from __future__ import annotations

from typing import Dict, List


# ------------------------------------------------------------------ #
# 预设：base_url + 默认模型 + API key 环境变量名
# ------------------------------------------------------------------ #
PRESETS: Dict[str, Dict[str, str]] = {
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "desc": "GPT-4o / GPT-4o-mini，通用能力强",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-flash",
        "env_key": "DEEPSEEK_API_KEY",
        "desc": "DeepSeek Flash / V4 Pro，官方 OpenAI 兼容接口",
    },
    "qwen_api": {
        "name": "通义千问 API",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "env_key": "DASHSCOPE_API_KEY",
        "desc": "qwen-plus / qwen-max，阿里云端",
    },
    "glm": {
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "env_key": "GLM_API_KEY",
        "desc": "GLM-4 / GLM-4-Flash，智谱清言",
    },
    "moonshot": {
        "name": "月之暗面 Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k2.6",
        "env_key": "MOONSHOT_API_KEY",
        "desc": "Kimi K2.6 / K3，官方云端接口",
    },
    "ollama": {
        "name": "Ollama 本地",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen3:8b",
        "env_key": "",  # Ollama 不需要 key
        "desc": "本地部署，离线可用",
    },
    "openrouter": {
        "name": "OpenRouter 聚合",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4.1-mini",
        "env_key": "OPENROUTER_API_KEY",
        "desc": "一个 key 接入多家提供商的模型",
    },
    "siliconflow": {
        "name": "SiliconFlow 硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen3-8B",
        "env_key": "SILICONFLOW_API_KEY",
        "desc": "国内聚合，一个 key 接入 Qwen/DeepSeek/GLM/Llama 等",
    },
}


# Common choices checked against official catalogs on 2026-10-14.
# Suggestions do not assert account access, pricing or local installation.
COMMON_MODELS = {
    "openai": [
        {"model": "gpt-4o-mini", "name": "GPT-4o mini"},
        {"model": "gpt-4.1-mini", "name": "GPT-4.1 mini"},
        {"model": "gpt-4.1", "name": "GPT-4.1"},
    ],
    "deepseek": [
        {"model": "deepseek-flash", "name": "DeepSeek Flash"},
        {"model": "deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
    ],
    "qwen_api": [
        {"model": "qwen-plus", "name": "Qwen Plus"},
        {"model": "qwen3.7-plus", "name": "Qwen 3.7 Plus"},
        {"model": "qwen3.8-flash", "name": "Qwen 3.8 Flash"},
        {"model": "qwen3.8-max", "name": "Qwen 3.8 Max"},
    ],
    "glm": [
        {"model": "glm-4-flash", "name": "GLM-4 Flash"},
        {"model": "glm-4-flash-250414", "name": "GLM-4 Flash 250414"},
        {"model": "glm-4-plus", "name": "GLM-4 Plus"},
    ],
    "moonshot": [
        {"model": "kimi-k2.6", "name": "Kimi K2.6"},
        {"model": "kimi-k3", "name": "Kimi K3"},
    ],
    "ollama": [
        {"model": "qwen3:8b", "name": "Qwen 3 8B（需本机已安装）"},
        {"model": "qwen3.5:4b", "name": "Qwen 3.5 4B（需本机已安装）"},
        {"model": "qwen3.5:9b", "name": "Qwen 3.5 9B（需本机已安装）"},
    ],
    "openrouter": [
        {"model": "openai/gpt-4.1-mini", "name": "GPT-4.1 mini"},
        {"model": "deepseek/deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
    ],
    "siliconflow": [
        {"model": "Qwen/Qwen3-8B", "name": "Qwen 3 8B"},
    ],
}
# Retain the existing aggregator endpoint contract.
AGGREGATOR_MODELS = {k: COMMON_MODELS[k] for k in ("openrouter", "siliconflow")}


def list_presets() -> list:
    """列出所有预设（带是否可用的标志）。"""
    import os
    out = []
    for key, p in PRESETS.items():
        env_key = p.get("env_key", "")
        has_key = bool(not env_key or os.getenv(env_key))
        out.append({
            "key": key,
            "name": p["name"],
            "base_url": p["base_url"],
            "model": p["model"],
            "env_key": env_key,
            "desc": p.get("desc", ""),
            "available": has_key,
            "models": [dict(m) for m in COMMON_MODELS.get(key, [])],
        })
    return out


def get_preset(provider: str) -> Dict[str, str]:
    """获取指定 provider 的预设。"""
    return PRESETS.get(provider, {})


# ------------------------------------------------------------------ #
# OpenAICompatLLM - 直接走 httpx 调 OpenAI 兼容接口
# ------------------------------------------------------------------ #

import os
from typing import List

import httpx

from llm.base import BaseLLM, LLMMessage


class OpenAICompatLLM(BaseLLM):
    """OpenAI 兼容 LLM 实现（httpx 直连）。

    适配 OpenAI / DeepSeek / 通义千问 / 智谱 GLM / Kimi / Ollama 等任何
    OpenAI 兼容端点。Ollama 走原生 /api/chat 接口以支持 think:false。
    """

    name = "openai-compat"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "",
        timeout: int = 180,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = max(1, min(float(timeout), 30))
        self._call_count = 0
        self._token_used = 0

    def _is_ollama(self) -> bool:
        from urllib.parse import urlsplit
        address=urlsplit(self.base_url)
        return address.hostname in {"localhost","127.0.0.1","host.docker.internal"} and address.port==11434

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key or 'ollama'}",
        }

    def _chat(self, messages: List[dict], **kw) -> str:
        self._call_count += 1
        try:
            if self._is_ollama():
                return self._chat_ollama_native(messages, **kw)
            return self._chat_openai_compat(messages, **kw)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("OpenAI-compatible model temporarily unavailable")
            return ""

    def _chat_ollama_native(self, messages: List[dict], **kw) -> str:
        base = self.base_url.replace("/v1", "").rstrip("/")
        url = f"{base}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": kw.get("keep_alive", "90s"),
            "options": {
                "temperature": kw.get("temperature", 0.0),
                "num_predict": kw.get("max_tokens", 1024),
                "num_ctx": min(32768,max(2048,int(kw.get("num_ctx",8192)))),
            },
        }
        if kw.get("structured_json"):payload["format"]=kw.get("json_schema") or "json"
        from llm.ollama_transport import chat_response
        data = chat_response(url,payload,self._headers(),min(70,max(.1,float(kw.get("timeout_seconds",self.timeout)))))
        msg = data.get("message", {})
        content = msg.get("content", "") or msg.get("reasoning", "") or ""
        self._token_used += (
            data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
            or self.count_tokens(content)
        )
        return content

    def _chat_openai_compat(self, messages: List[dict], **kw) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kw.get("temperature", 0.0),
            "max_tokens": kw.get("max_tokens", 1024),
            "stream": False,
        }
        url = f"{self.base_url}/chat/completions"
        with httpx.Client(timeout=min(70,max(.1,float(kw.get("timeout_seconds",self.timeout)))), proxy=None, trust_env=False) as client:
            resp = client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content", "") or msg.get("reasoning", "") or ""
        usage = data.get("usage", {})
        self._token_used += usage.get("total_tokens", self.count_tokens(content))
        return content

    def complete(self, prompt: str, **kwargs) -> str:
        self._token_used += self.count_tokens(prompt)
        return self._chat([{"role": "user", "content": prompt}], **kwargs)

    def chat(self, messages: List[LLMMessage], **kwargs) -> str:
        return self._chat(
            [{"role": m.role, "content": m.content} for m in messages], **kwargs
        )

    def score_true_probability(self, prompt: str, **kwargs) -> float:
        text = self.complete(
            prompt + "\n请只回答 True 或 False。", max_tokens=5, **kwargs
        ).strip().lower()
        return 0.9 if "true" in text else 0.1

    @property
    def stats(self) -> dict:
        return {"calls": self._call_count, "tokens": self._token_used, "model": self.model}


def create_llm(provider: str = "openai", **kwargs) -> BaseLLM:
    """工厂方法：根据预设 provider 创建 LLM 实例。

    Args:
        provider: openai / deepseek / qwen_api / glm / moonshot / ollama
        kwargs: 可覆盖 model / base_url / api_key / timeout
    """
    preset = PRESETS.get(provider)
    if not preset:
        raise ValueError(f"未知 provider: {provider}，可选: {list(PRESETS.keys())}")

    model = kwargs.pop("model", None) or preset["model"]
    base_url = kwargs.pop("base_url", None) or preset["base_url"]
    env_key = preset.get("env_key", "")
    api_key = kwargs.pop("api_key", None)
    if api_key is None and env_key:
        api_key = os.getenv(env_key, "")
    if api_key is None:
        api_key = ""

    return OpenAICompatLLM(
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout=kwargs.pop("timeout", 180),
    )


__all__ = ["PRESETS", "COMMON_MODELS", "AGGREGATOR_MODELS", "list_presets", "get_preset", "OpenAICompatLLM", "create_llm"]
