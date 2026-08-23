"""
QwenLLM - 通义千问本地接入

使用 transformers 加载 Qwen2.5-7B-Instruct。
默认是 stub 行为（不实际加载模型，避免本地无 GPU/无模型权重）。
将 USE_QWEN_STUB 设为 0 或安装真实权重后，会启用真实推理。

使用：
    llm = QwenLLM(model_path="Qwen/Qwen2.5-7B-Instruct")
    out = llm.complete("介绍一下大模型智能搜索")
"""

from __future__ import annotations

import os
from typing import List

from llm.base import BaseLLM, LLMMessage


class QwenLLM(BaseLLM):
    """
    Qwen 本地实现（MVP 阶段为 stub）。

    真实启用：
        1. pip install transformers accelerate torch
        2. huggingface-cli login   (若模型在 HF Hub)
        3. 取消下方 _STUB 标志
    """

    name = "qwen-2.5"

    # 默认 stub - 无 GPU 环境无需下载 7B 模型也能跑通
    _STUB = os.getenv("USE_QWEN_STUB", "1") == "1"

    def __init__(self, model_path: str = "Qwen/Qwen2.5-7B-Instruct", **kwargs):
        self.model_path = model_path
        self._call_count = 0
        self._token_used = 0
        self._model = None
        self._tokenizer = None

        if not self._STUB:
            self._load_model()

    def _load_model(self) -> None:
        """实际加载 Qwen 模型（GPU 推荐 ≥ 16GB）。"""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                device_map="auto",
                torch_dtype="auto",
            )
        except ImportError as e:
            raise ImportError(
                "QwenLLM 需要安装 transformers 与 torch，"
                "或在环境变量中设置 USE_QWEN_STUB=1 使用 stub 模式。"
            ) from e

    # ------------------------------------------------------------------ #
    # 真实推理（stub 时返回 mock）
    # ------------------------------------------------------------------ #
    def _real_complete(self, prompt: str) -> str:
        if self._STUB:
            return f"[Qwen-STUB] mock answer for: {prompt[:60]}..."
        assert self._model is not None and self._tokenizer is not None
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        outputs = self._model.generate(
            **inputs, max_new_tokens=512, do_sample=False
        )
        text = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
        return text[len(prompt):].strip()

    def _real_score_true_probability(self, prompt: str) -> float:
        if self._STUB:
            # 在 stub 模式下退化为"是否包含 True 字样"
            return 0.9 if "True" in prompt[-10:] else 0.1
        assert self._model is not None and self._tokenizer is not None
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        out = self._model(**inputs)
        # 找 True / False 在 vocab 中的 id
        true_id = self._tokenizer(" True", add_special_tokens=False)["input_ids"][0]
        false_id = self._tokenizer(" False", add_special_tokens=False)["input_ids"][0]
        # 最后一 token 位置的 logits
        import torch
        logits = out.logits[0, -1]
        probs = torch.softmax(logits, dim=-1)
        return float(probs[true_id] / (probs[true_id] + probs[false_id] + 1e-9))

    # ------------------------------------------------------------------ #
    # 公共接口
    # ------------------------------------------------------------------ #
    def complete(self, prompt: str, **kwargs) -> str:
        self._call_count += 1
        self._token_used += self.count_tokens(prompt)
        return self._real_complete(prompt)

    def chat(self, messages: List[LLMMessage], **kwargs) -> str:
        if self._STUB:
            last_user = next(
                (m.content for m in reversed(messages) if m.role == "user"), ""
            )
            return self._real_complete(last_user)
        # 真实模式：用 chat template
        assert self._tokenizer is not None
        text = self._tokenizer.apply_chat_template(
            [{"role": m.role, "content": m.content} for m in messages],
            tokenize=False, add_generation_prompt=True,
        )
        return self._real_complete(text)

    def score_true_probability(self, prompt: str, **kwargs) -> float:
        self._call_count += 1
        self._token_used += self.count_tokens(prompt)
        return self._real_score_true_probability(prompt)
