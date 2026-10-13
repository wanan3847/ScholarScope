"""
OpenAI 兼容 API 预设。

统一管理各云端 LLM 提供商的 base_url、默认模型、API key 环境变量。
所有预设都走 OpenAI 兼容接口，可由 router._chat_openai_compat 直接调用。

支持的提供商：
    - openai:   GPT-4o / GPT-4o-mini
    - deepseek: DeepSeek-V3 / DeepSeek-R1
    - qwen_api: 通义千问 qwen-plus / qwen-max
    - glm:      智谱 GLM-4 / GLM-4-Flash
    - moonshot: Kimi K1.5
    - ollama:   本地 Ollama（特殊处理，走原生接口）

使用：
    from llm.openai_compat import PRESETS, list_presets
    preset = PRESETS["deepseek"]
    # base_url, model, env_key
"""

from __future__ import annotations

from typing import Dict


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
        "model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "desc": "DeepSeek-V3 / R1，性价比高",
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
        "model": "moonshot-v1-8k",
        "env_key": "MOONSHOT_API_KEY",
        "desc": "Kimi K1.5，长上下文",
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
        "model": "qwen/qwen-2.5-7b-instruct",
        "env_key": "OPENROUTER_API_KEY",
        "desc": "一个 key 接入 200+ 模型（GPT-4o/Claude/Gemini/Qwen/DeepSeek/Llama 等）",
    },
    "siliconflow": {
        "name": "SiliconFlow 硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "env_key": "SILICONFLOW_API_KEY",
        "desc": "国内聚合，一个 key 接入 Qwen/DeepSeek/GLM/Llama 等",
    },
}


# OpenRouter / SiliconFlow 上常见的热门模型列表（用于前端选择）
AGGREGATOR_MODELS: Dict[str, List[Dict[str, str]]] = {
    "openrouter": [
        {"model": "qwen/qwen-2.5-7b-instruct", "name": "Qwen 2.5 7B (免费)", "free": True},
        {"model": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B"},
        {"model": "deepseek/deepseek-chat", "name": "DeepSeek V3"},
        {"model": "deepseek/deepseek-r1", "name": "DeepSeek R1"},
        {"model": "openai/gpt-4o-mini", "name": "GPT-4o mini"},
        {"model": "openai/gpt-4o", "name": "GPT-4o"},
        {"model": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet"},
        {"model": "google/gemini-flash-1.5", "name": "Gemini Flash 1.5"},
        {"model": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B"},
        {"model": "01-ai/yi-large", "name": "Yi Large"},
    ],
    "siliconflow": [
        {"model": "Qwen/Qwen2.5-7B-Instruct", "name": "Qwen 2.5 7B (免费)", "free": True},
        {"model": "Qwen/Qwen2.5-72B-Instruct", "name": "Qwen 2.5 72B"},
        {"model": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3"},
        {"model": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1"},
        {"model": "THUDM/glm-4-9b-chat", "name": "GLM-4 9B (免费)", "free": True},
        {"model": "meta-llama/Meta-Llama-3.1-8B-Instruct", "name": "Llama 3.1 8B (免费)", "free": True},
        {"model": "meta-llama/Meta-Llama-3.1-70B-Instruct", "name": "Llama 3.1 70B"},
    ],
}


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
        self.timeout = timeout
        self._call_count = 0
        self._token_used = 0

    def _is_ollama(self) -> bool:
        return "localhost:11434" in self.base_url or "127.0.0.1:11434" in self.base_url

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
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("[OpenAICompat] %s 调用失败: %s", self.model, e)
            return ""

    def _chat_ollama_native(self, messages: List[dict], **kw) -> str:
        base = self.base_url.replace("/v1", "").rstrip("/")
        url = f"{base}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": kw.get("temperature", 0.0),
                "num_predict": kw.get("max_tokens", 1024),
            },
        }
        with httpx.Client(timeout=self.timeout, proxy=None, trust_env=False) as client:
            resp = client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
        data = resp.json()
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
        with httpx.Client(timeout=self.timeout, proxy=None, trust_env=False) as client:
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


__all__ = ["PRESETS", "AGGREGATOR_MODELS", "list_presets", "get_preset", "OpenAICompatLLM", "create_llm"]
