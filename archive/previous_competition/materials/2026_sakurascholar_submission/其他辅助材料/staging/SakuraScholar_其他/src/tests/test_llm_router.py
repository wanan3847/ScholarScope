"""LLM 路由器回归测试：ollama 模式不得继承云端模型名。"""

from __future__ import annotations

import os

import llm.router as router_mod


def _reset_default_router():
    router_mod._default = None


def test_ollama_endpoint_uses_dedicated_model(monkeypatch):
    """SAKURA_LLM_MODEL=deepseek-chat 时，ollama 端点仍用 OLLAMA_MODEL/qwen3:8b。"""
    monkeypatch.setenv("SAKURA_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SAKURA_LLM_MODEL", "deepseek-chat")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    _reset_default_router()
    try:
        r = router_mod.get_default_router()
        ep = r._endpoints["ollama"]
        assert ep.model == "qwen3:8b"
        assert "11434" in ep.base_url
    finally:
        _reset_default_router()


def test_ollama_endpoint_honors_ollama_model_override(monkeypatch):
    monkeypatch.setenv("SAKURA_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SAKURA_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:14b")
    _reset_default_router()
    try:
        r = router_mod.get_default_router()
        assert r._endpoints["ollama"].model == "qwen3:14b"
    finally:
        _reset_default_router()
