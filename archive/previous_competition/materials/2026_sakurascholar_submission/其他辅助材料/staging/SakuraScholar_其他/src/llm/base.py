"""
LLM 抽象基类

设计目标：
  - 让上层 Agent 不绑定具体 LLM（OpenAI / Qwen / Mock）
  - 三个核心能力：
      1) complete(prompt)               - 文本补全
      2) chat(messages)                 - 多轮对话
      3) score_true_probability(prompt) - PaSa 风格：返回 "True" 这一 token 的概率
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class LLMMessage:
    """OpenAI 风格的多轮消息。"""

    role: str  # "system" | "user" | "assistant"
    content: str


class BaseLLM(abc.ABC):
    """LLM 抽象基类。"""

    name: str = "base-llm"

    # ------------------------------------------------------------------ #
    # 基础接口
    # ------------------------------------------------------------------ #
    @abc.abstractmethod
    def complete(self, prompt: str, **kwargs) -> str:
        """单轮文本补全。"""

    @abc.abstractmethod
    def chat(self, messages: List[LLMMessage], **kwargs) -> str:
        """多轮对话。"""

    @abc.abstractmethod
    def score_true_probability(self, prompt: str, **kwargs) -> float:
        """
        PaSa 风格：返回模型在 prompt 之后输出 "True" 这一 token 的概率。
        实现方可以返回 [0, 1] 区间内的浮点。
        """

    # ------------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------------ #
    def count_tokens(self, text: str) -> int:
        """粗略 token 估算（每 4 字符 ≈ 1 token）。"""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def score(self, prompt: str, choices: Optional[List[str]] = None, **kwargs) -> dict:
        """
        多选打分：将每个选项拼到 prompt 末尾，调用 score_true_probability。
        返回 {choice: probability}。
        """
        if choices is None:
            choices = ["True", "False"]
        results = {}
        for c in choices:
            results[c] = self.score_true_probability(
                prompt + "\nAnswer: " + c, **kwargs
            )
        return results
