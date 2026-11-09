"""Existing model setup contracts: reuse saved credentials and provider parameters."""
import asyncio
import json
import httpx
import pytest
from fastapi import HTTPException
from llm.router import LLMRouter, ModelEndpoint, _RoutedLLM


def test_preset_update_retains_existing_key_priority_and_rejects_empty_cloud_key(monkeypatch):
    import web.app as web
    from llm.openai_compat import PRESETS
    router = LLMRouter()
    router.register("deepseek", "old-model", PRESETS["deepseek"]["base_url"], "ContractKeyOnly", priority=1)
    monkeypatch.setattr(web, "_is_admin", lambda token: True)
    monkeypatch.setattr(web, "_get_llm_router", lambda: router)
    monkeypatch.setattr(web, "_save_llm_config", lambda: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    result = asyncio.run(web.register_preset(web.LLMPresetRegisterRequest(provider="deepseek", model="deepseek-flash", priority=30), token="contract"))
    assert router._endpoints["deepseek"].api_key == "ContractKeyOnly"
    assert router.get().ep.model == "deepseek-flash" and router.get().ep.priority == 30
    assert "ContractKeyOnly" not in json.dumps(result)
    router.unregister("deepseek")
    with pytest.raises(HTTPException) as error:
        asyncio.run(web.register_preset(web.LLMPresetRegisterRequest(provider="deepseek"), token="contract"))
    assert error.value.status_code == 400 and not router.list_endpoints()


@pytest.mark.parametrize("model", ["kimi-k2.6", "kimi-k3", "gpt-4.1-mini"])
def test_model_payload_accepts_fixed_parameter_providers_without_new_config_path(monkeypatch, model):
    import llm.router as module
    client = httpx.Client
    def handle(request):
        body = json.loads(request.content)
        assert body["model"] == model and body["max_tokens"] == 200
        if model.startswith("kimi-"):
            assert "temperature" not in body
            if model == "kimi-k2.6": assert body["thinking"] == {"type": "disabled"}
            else: assert body["reasoning_effort"] == "low" and "thinking" not in body
        else: assert body["temperature"] == 0
        return httpx.Response(200, json={"choices": [{"message": {"content": "Verified contract response"}}]})
    monkeypatch.setattr(module.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(handle)))
    llm = _RoutedLLM(ModelEndpoint("contract", model, "https://provider.invalid/v1", "ContractOnly"))
    assert llm._chat_openai_compat([{"role": "user", "content": "test"}], max_tokens=200) == "Verified contract response"
