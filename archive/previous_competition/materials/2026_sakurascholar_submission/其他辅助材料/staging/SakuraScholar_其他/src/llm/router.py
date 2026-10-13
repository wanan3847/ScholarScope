"""
LLM 转发路由模块

基于 httpx 统一转发，支持任意 OpenAI 兼容端点：
    - Ollama 本地模型（qwen3:8b 等）
    - OpenAI / DeepSeek / 通义千问 / 智谱 GLM 等云端 API
    - 离线 Mock（零依赖保底）

所有端点走同一条 httpx 通道，统一管理、统一切换。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from llm.base import BaseLLM, LLMMessage
from llm.mock_llm import MockLLM

logger = logging.getLogger(__name__)


@dataclass
class ModelEndpoint:
    """模型端点配置。"""

    name: str              # 显示名
    model: str             # 模型标识（如 qwen3:8b, gpt-4o-mini）
    base_url: str          # OpenAI 兼容 base_url
    api_key: str = ""      # API key（Ollama 留空）
    enabled: bool = True
    priority: int = 0

    @property
    def available(self) -> bool:
        if not self.enabled:
            return False
        return bool(self.model and self.base_url)


class LLMRouter:
    """
    转发路由器：统一管理多模型端点，按优先级选择，httpx 直连。
    """

    def __init__(self):
        self._endpoints: Dict[str, ModelEndpoint] = {}
        self._instances: Dict[str, BaseLLM] = {}

    def register(
        self,
        name: str,
        model: str,
        base_url: str,
        api_key: str = "",
        enabled: bool = True,
        priority: int = 0,
    ) -> None:
        self._endpoints[name] = ModelEndpoint(
            name=name, model=model, base_url=base_url.rstrip("/"),
            api_key=api_key, enabled=enabled, priority=priority,
        )
        self._instances.pop(name, None)
        logger.info("[Router] 注册 %s → %s @ %s", name, model, base_url)

    def unregister(self, name: str) -> None:
        self._endpoints.pop(name, None)
        self._instances.pop(name, None)

    def list_endpoints(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": ep.name,
                "model": ep.model,
                "base_url": ep.base_url,
                "enabled": ep.enabled,
                "priority": ep.priority,
                "available": ep.available,
            }
            for ep in sorted(self._endpoints.values(), key=lambda e: -e.priority)
        ]

    def get(self, name: Optional[str] = None) -> BaseLLM:
        """获取 LLM 实例。name=None 选优先级最高的可用端点。"""
        if name is None:
            name = self._best()
        if name and name in self._endpoints and self._endpoints[name].available:
            if name not in self._instances:
                self._instances[name] = _RoutedLLM(self._endpoints[name])
            return self._instances[name]
        # 保底
        return self._instances.setdefault("__mock", MockLLM())

    def _best(self) -> Optional[str]:
        for ep in sorted(self._endpoints.values(), key=lambda e: -e.priority):
            if ep.available:
                return ep.name
        return None


class _RoutedLLM(BaseLLM):
    """单个路由端点的 LLM 实现，httpx 直连 OpenAI 兼容接口。"""

    name = "routed-llm"

    def __init__(self, ep: ModelEndpoint, timeout: int = 180):
        self.ep = ep
        self.timeout = timeout
        self._call_count = 0
        self._token_used = 0

    # ------------------------------------------------------------------ #
    def _headers(self) -> dict:
        key = self.ep.api_key or "ollama"
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }

    def _is_ollama(self) -> bool:
        """是否为 Ollama 本地端点。"""
        return "localhost:11434" in self.ep.base_url or "127.0.0.1:11434" in self.ep.base_url

    def _chat(self, messages: List[Dict], **kw) -> str:
        self._call_count += 1
        try:
            if self._is_ollama():
                content = self._chat_ollama_native(messages, **kw)
            else:
                content = self._chat_openai_compat(messages, **kw)
            return content
        except Exception as e:
            logger.error("[Router] %s 调用失败: %s", self.ep.name, e)
            return ""

    def _chat_ollama_native(self, messages: List[Dict], **kw) -> str:
        """Ollama 原生 /api/chat 接口。

        比 OpenAI 兼容接口更高效，且支持 think:false 关闭 qwen3 思考模式
        （OpenAI 兼容接口的 chat_template_kwargs 在 Ollama 上不生效）。
        """
        base = self.ep.base_url.replace("/v1", "").rstrip("/")
        url = f"{base}/api/chat"
        payload = {
            "model": self.ep.model,
            "messages": messages,
            "stream": False,
            "think": False,  # 关闭 qwen3 思考模式
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
        content = msg.get("content", "") or ""
        # 兜底：thinking 模式未关时从 reasoning 字段取
        if not content and msg.get("reasoning"):
            content = msg["reasoning"]
        # token 统计：Ollama 用 prompt_eval_count + eval_count
        self._token_used += (
            data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
            or self.count_tokens(content)
        )
        return content

    def _chat_openai_compat(self, messages: List[Dict], **kw) -> str:
        """OpenAI 兼容接口（云端 API 用）。"""
        payload = {
            "model": self.ep.model,
            "messages": messages,
            "temperature": kw.get("temperature", 0.0),
            "max_tokens": kw.get("max_tokens", 1024),
            "stream": False,
        }
        url = f"{self.ep.base_url}/chat/completions"
        with httpx.Client(timeout=self.timeout, proxy=None, trust_env=False) as client:
            resp = client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content", "") or ""
        if not content and msg.get("reasoning"):
            content = msg["reasoning"]
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
        return {"calls": self._call_count, "tokens": self._token_used, "model": self.ep.model}


# ------------------------------------------------------------------ #
# 全局默认路由器
# ------------------------------------------------------------------ #
_default: Optional[LLMRouter] = None


def get_default_router() -> LLMRouter:
    """获取全局路由器，首次调用时从环境变量初始化。"""
    global _default
    if _default is not None:
        return _default

    r = LLMRouter()
    # 保底 mock
    r.register("mock", model="mock", base_url="", priority=-1)

    provider = os.getenv("SAKURA_LLM_PROVIDER", "").lower()
    if provider == "ollama":
        r.register(
            "ollama",
            # 独立变量 OLLAMA_MODEL，避免继承 SAKURA_LLM_MODEL（云端模型名，
            # 如 deepseek-chat，会被 ollama 判为未知模型 → 404）
            model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            priority=10,
        )
    elif provider in ("openai", "deepseek", "qwen_api", "glm"):
        from llm.openai_compat import PRESETS
        preset = PRESETS.get(provider, {})
        r.register(
            provider,
            model=os.getenv("SAKURA_LLM_MODEL", preset.get("model", "")),
            base_url=os.getenv("SAKURA_LLM_BASE_URL", preset.get("base_url", "")),
            api_key=os.getenv(preset.get("env_key", "OPENAI_API_KEY"), ""),
            priority=10,
        )

    _default = r
    return r


__all__ = ["LLMRouter", "ModelEndpoint", "get_default_router"]
