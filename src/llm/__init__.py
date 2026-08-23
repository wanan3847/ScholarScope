"""LLM 抽象与多实现包。"""

from llm.base import BaseLLM, LLMMessage
from llm.mock_llm import MockLLM
from llm.openai_compat import OpenAICompatLLM, PRESETS, create_llm

try:
    from llm.qwen import QwenLLM  # noqa: F401
except ImportError:
    # 未安装 transformers 时不强制导入
    QwenLLM = None  # type: ignore[assignment]

__all__ = [
    "BaseLLM",
    "LLMMessage",
    "MockLLM",
    "OpenAICompatLLM",
    "QwenLLM",
    "PRESETS",
    "create_llm",
    "get_llm",
]


def get_llm(provider: str = "mock", **kwargs) -> BaseLLM:
    """
    工厂方法：根据 provider 创建对应 LLM 实例。

    Args:
        provider:
            "mock"        - 离线 mock（默认，无需 API key）
            "openai"      - OpenAI 官方 API (gpt-4o-mini)
            "deepseek"    - DeepSeek API (deepseek-chat)
            "qwen_api"    - 通义千问 API (qwen-plus，OpenAI 兼容)
            "glm"         - 智谱 GLM API (glm-4-flash)
            "qwen"        - 本地 Qwen 模型（需 transformers + torch）
        kwargs: 透传给具体实现

    环境变量：
        OPENAI_API_KEY     - OpenAI / 兼容端点的 API key
        OPENAI_BASE_URL    - 自定义 base URL
        SAKURA_LLM_MODEL   - 模型名
        DEEPSEEK_API_KEY   - DeepSeek 专用
        DASHSCOPE_API_KEY  - 通义千问专用
        GLM_API_KEY        - 智谱 GLM 专用
    """
    provider = provider.lower()
    if provider == "mock":
        return MockLLM(**kwargs)
    if provider in ("openai", "deepseek", "qwen_api", "glm"):
        return create_llm(provider, **kwargs)
    if provider == "qwen":
        if QwenLLM is None:  # type: ignore[name-defined]
            raise ImportError("QwenLLM 不可用，请先安装 transformers 与 torch。")
        return QwenLLM(**kwargs)  # type: ignore[call-arg]
    raise ValueError(
        f"未知 LLM provider: {provider}，可选: mock / openai / deepseek / qwen_api / glm / qwen"
    )
