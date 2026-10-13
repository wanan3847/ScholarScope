"""
ScholarScope 全局配置

集中管理：
  - 检索后端开关
  - LLM 选型
  - 评分阈值 / 召回数量等超参
  - 路径常量

设计原则：MVP 阶段不依赖任何外部 key，所有参数可由环境变量覆盖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# 加载 .env（README: cp .env.example .env）
# 同时兼容 src/.env 与仓库根目录 .env
try:
    from dotenv import load_dotenv
    _ENV_CANDIDATES = [
        Path(__file__).resolve().parent / ".env",        # src/.env
        Path(__file__).resolve().parent.parent / ".env",  # 仓库根/.env
    ]
    for _env_path in _ENV_CANDIDATES:
        if _env_path.exists():
            load_dotenv(_env_path)
except ImportError:
    pass


# ------------------------------------------------------------------ #
# 路径常量
# ------------------------------------------------------------------ #
PROJECT_ROOT: Path = Path(__file__).resolve().parent
SRC_ROOT: Path = PROJECT_ROOT
PROMPT_DIR: Path = SRC_ROOT / "prompts"
DATA_DIR: Path = SRC_ROOT / "data"
EXAMPLE_DIR: Path = SRC_ROOT / "examples"


# ------------------------------------------------------------------ #
# 主配置
# ------------------------------------------------------------------ #
@dataclass
class Settings:
    """全局配置（dataclass 实现，便于子类化与测试覆盖）。"""

    # ---------- LLM 选型 ---------- #
    # 可选: "mock" | "qwen" | "openai" | "deepseek" | "qwen_api" | "glm"
    llm_provider: str = os.getenv("SAKURA_LLM_PROVIDER", "mock")
    llm_model_name: str = os.getenv("SAKURA_LLM_MODEL", "mock-llm-v1")
    # Qwen 本地路径（启用 qwen 时填写）
    qwen_model_path: str = os.getenv("SAKURA_QWEN_PATH", "Qwen/Qwen2.5-7B-Instruct")
    # OpenAI 兼容 endpoint（启用 openai / deepseek / qwen_api / glm 时填写）
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    # DeepSeek 专用
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    # 通义千问 API 专用
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    qwen_api_model: str = "qwen-plus"
    # 智谱 GLM 专用
    glm_api_key: str = os.getenv("GLM_API_KEY", "")
    glm_model: str = "glm-4-flash"

    # ---------- 检索后端开关 ---------- #
    enabled_backends: List[str] = field(
        default_factory=lambda: [
            # 本地公开语料优先：稳定、零限流；其余后端补充 DOI/摘要元数据。
            "local_corpus",
            "crossref",
            "semantic_scholar",
            "openalex",
            "arxiv",
            "pubmed",
        ]
    )
    # 每个后端最大召回数
    per_backend_top_k: int = int(os.getenv("SAKURA_PER_BACKEND_K", "20"))

    # ---------- 评分阈值 ---------- #
    selector_threshold: float = 0.5  # PaSa 风格 selector 阈值
    selector_top_k: int = 30         # selector 之后保留的 paper 数
    rerank_top_k: int = 20           # 与 PaSa Recall@20 官方口径一致

    # ---------- RefChain 演化 ---------- #
    refchain_max_new_queries: int = 5
    refchain_bfs_depth: int = 2

    # ---------- Crawler ---------- #
    crawler_candidate_queries: int = 5  # PaSa 风格 crawler 生成的候选 query 数

    # ---------- 日志 ---------- #
    log_level: str = os.getenv("SAKURA_LOG_LEVEL", "INFO")

    # ---------- 是否使用 mock 数据 ---------- #
    use_mock_retrieval: bool = True   # MVP 阶段默认 True，真实 API 时设为 False


# 全局单例
settings = Settings()


def get_settings() -> Settings:
    """获取全局配置（便于测试时 monkeypatch）。"""
    return settings
