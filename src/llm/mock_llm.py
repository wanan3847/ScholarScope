"""
MockLLM - 离线 mock LLM

目的：
  - MVP 阶段不依赖任何外部 API key
  - 用关键词匹配 + 启发式规则返回概率与文本
  - 方便单测、CI 与本地一键运行

启发式：
  - 关键词匹配数 / 总关键词数  -> score
  - 文本补全：用规则拼接
"""

from __future__ import annotations

import re
from typing import List

from llm.base import BaseLLM, LLMMessage


class MockLLM(BaseLLM):
    """基于关键词匹配的 mock LLM。"""

    name = "mock-llm-v1"

    def __init__(self, **kwargs):
        # 不需要任何外部资源
        self._call_count = 0
        self._token_used = 0

    # ------------------------------------------------------------------ #
    # 工具：分词 + 关键词
    # ------------------------------------------------------------------ #
    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """简单按非字母数字切分 + 小写。"""
        return [t.lower() for t in re.split(r"[^A-Za-z0-9\u4e00-\u9fa5]+", text) if t]

    def _extract_keywords(self, prompt: str) -> List[str]:
        """
        从 prompt 中提取"查询关键词"。

        约定：prompt 中以 "用户查询" / "User Query" / "Query" / "query" 开头的一行（紧跟的内容）
        """
        # 同时兼容 "Key: xxx" 与 markdown 风格 "# Key\nxxx"
        patterns = [
            r"(?:User Query|用户查询|Question|关键词|Query|query)\s*[：:]?\s*\n+\s*(.+)",
            r"(?:User Query|用户查询|Question|关键词|Query|query)\s*[：:]\s*([^\n]+)",
        ]
        for p in patterns:
            m = re.search(p, prompt, re.IGNORECASE)
            if m:
                target = m.group(1).strip()
                return self._tokenize(target)
        return self._tokenize(prompt)

    def _extract_doc_keywords(self, prompt: str) -> List[str]:
        """
        提取候选文档的关键词（title + abstract）。
        同时支持：
            "Title: ..." / "Abstract: ..."
            "# 论文标题\n..." / "# 论文摘要\n..."
        """
        title = ""
        abstract = ""

        # 英文 "Title:" / "Abstract:" 形式
        m_title = re.search(r"^Title\s*[：:]\s*(.+)$", prompt,
                            re.IGNORECASE | re.MULTILINE)
        m_abs = re.search(r"^Abstract\s*[：:]\s*(.+)$", prompt,
                          re.IGNORECASE | re.MULTILINE)
        if m_title:
            title = m_title.group(1).splitlines()[0]
        if m_abs:
            abstract = m_abs.group(1).splitlines()[0]

        # 中文 "# 论文标题\n..." 形式（覆盖到下一个 # 之前）
        if not title:
            m = re.search(r"# 论文标题\s*\n+(.+?)(?=\n\s*#|\Z)",
                          prompt, re.DOTALL)
            if m:
                title = m.group(1).strip()
        if not abstract:
            m = re.search(r"# 论文摘要\s*\n+(.+?)(?=\n\s*#|\Z)",
                          prompt, re.DOTALL)
            if m:
                abstract = m.group(1).strip()

        return self._tokenize(title + " " + abstract)

    def _gen_batch_scores(self, prompt: str, q_kw: List[str]) -> str:
        """
        批量打分场景：解析 prompt 中的论文列表，基于关键词重叠
        返回 `[i] score` 格式，分数有区分度。

        prompt 格式（来自 selector.score_batch）:
            用户查询: {query}

            以下是 N 篇候选论文:

            [0] 标题: xxx
            摘要: yyy

            [1] 标题: xxx
            摘要: yyy

            请对每篇论文与查询的相关性打分...
        """
        import hashlib

        # 1) 提取查询关键词（用户查询: 后面那行）
        q_set = set(q_kw)
        if not q_set:
            # 兜底：用 prompt 前 100 字符分词
            q_set = set(self._tokenize(prompt[:200]))

        # 2) 解析论文列表：[i] 标题: xxx \n 摘要: yyy
        # 用正则匹配每个论文块
        paper_blocks = re.findall(
            r"\[(\d+)\]\s*标题\s*[：:]\s*(.+?)\s*\n+\s*摘要\s*[：:]\s*(.+?)(?=\n+\[\d+\]|\Z)",
            prompt,
            re.DOTALL,
        )

        if not paper_blocks:
            # 解析失败：返回递减分数（保证有区分度）
            return "[0] 0.85\n[1] 0.62\n[2] 0.48\n[3] 0.35\n[4] 0.22"

        # 3) 对每篇论文计算分数
        lines = []
        for idx_str, title, abstract in paper_blocks:
            idx = int(idx_str)
            doc_kw = set(self._tokenize(title + " " + abstract))
            # 关键词重叠度
            if q_set:
                overlap = len(q_set & doc_kw) / max(1, min(len(q_set), 8))
            else:
                overlap = 0.3
            # 位置加权：靠前的论文分数略高（模拟 LLM 偏好）
            pos_bonus = max(0, 0.15 - idx * 0.02)
            # 基于论文内容的确定性扰动（让同 query 不同论文分数不同）
            seed_str = f"{idx}|{title[:30]}"
            h = int(hashlib.md5(seed_str.encode("utf-8")).hexdigest()[:4], 16) / 0xFFFF
            noise = (h - 0.5) * 0.2  # [-0.1, 0.1]
            score = max(0.05, min(0.95, overlap * 0.6 + 0.25 + pos_bonus + noise))
            lines.append(f"[{idx}] {score:.2f}")

        return "\n".join(lines) if lines else "[0] 0.50"

    # ------------------------------------------------------------------ #
    # 接口实现
    # ------------------------------------------------------------------ #
    def complete(self, prompt: str, **kwargs) -> str:
        """根据 prompt 类型生成合理的 mock 输出。"""
        self._call_count += 1
        self._token_used += self.count_tokens(prompt)
        kw = self._extract_keywords(prompt)

        # 判断 prompt 类型，返回匹配场景的输出
        prompt_lower = prompt.lower()

        # --- 批量打分类：selector.score_batch 调用 ---
        # prompt 含 "请对每篇论文" / "相关性打分" / "[序号] 分数"
        if ("相关性打分" in prompt or "请对每篇论文" in prompt
                or "打分（0.0-1.0）" in prompt or "打分(0.0-1.0)" in prompt):
            return self._gen_batch_scores(prompt, kw)

        # --- Crawler query 生成类：返回多行 query ---
        if any(k in prompt_lower for k in [
            "generate", "diverse search queries", "search queries",
            "new diverse search", "输出", "候选", "改写",
        ]):
            base_query = " ".join(kw[:6]) if kw else "research"
            # 返回 5 行真实风格的 query 变体
            variants = [
                f"{base_query} survey and review",
                f"{base_query} recent advances and benchmarks",
                f"{base_query} empirical study and analysis",
                f"comprehensive review of {base_query}",
                f"{base_query} state of the art methods",
            ]
            return "\n".join(variants)

        # --- RefChain 演化类：返回精炼 query ---
        if any(k in prompt_lower for k in ["refine", "rewrite", "evolve", "focus", "改写"]):
            base_query = " ".join(kw[:5]) if kw else "research"
            return f"{base_query} comprehensive study"

        # --- 摘要/总结类 ---
        if any(k in prompt_lower for k in ["summar", "abstract", "总结", "摘要"]):
            base_query = " ".join(kw[:4]) if kw else "this research"
            return (
                f"This study investigates {base_query}, presenting a novel approach "
                f"that achieves state-of-the-art performance on standard benchmarks. "
                f"The paper discusses implications and future directions."
            )

        # --- JSON 结构化输出类（查询理解）---
        if "json" in prompt_lower or "intent" in prompt_lower:
            base_query = " ".join(kw[:4]) if kw else "research"
            import json as _json
            return _json.dumps({
                "intent": "survey" if any(w in base_query.lower() for w in ["survey", "review", "综述"]) else "semantic",
                "rewritten_query": base_query,
                "keyword_query": " OR ".join(kw[:4]) if kw else base_query,
                "sub_queries": [f"{base_query} method", f"{base_query} dataset", f"{base_query} evaluation"],
                "search_filters": {"fields_of_study": ["Computer Science"], "year_range": [2018, 2026]},
            }, ensure_ascii=False)

        # 默认：简洁回答
        if not kw:
            return "Based on the available information, here are the relevant results."
        return f"Relevant findings about {', '.join(kw[:3])}: multiple studies have investigated this topic."

    def chat(self, messages: List[LLMMessage], **kwargs) -> str:
        """取最后一条 user 消息做 complete。"""
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        return self.complete(last_user, **kwargs)

    def score_true_probability(self, prompt: str, **kwargs) -> float:
        """
        计算 True 概率（mock）：
            score = |doc_keywords ∩ query_keywords| / |query_keywords|

        约定：调用方传入的 prompt 是 "prompt + Answer: True" 形式。
        如果是 "prompt + Answer: False" 形式，则返回 1 - relevance。
        """
        self._call_count += 1
        self._token_used += self.count_tokens(prompt)

        # 判断问的是 True 还是 False
        is_true = bool(re.search(r"answer:\s*true\s*$", prompt, re.IGNORECASE))
        # 计算相关度
        q_kw = set(self._extract_keywords(prompt))
        d_kw = set(self._extract_doc_keywords(prompt))
        if not q_kw:
            relevance = 0.5
        else:
            overlap = q_kw & d_kw
            relevance = len(overlap) / max(1, len(q_kw))

        if is_true:
            return float(min(1.0, max(0.0, relevance)))
        # 没有明确 "Answer: True" 结尾时，约定为问 True 概率
        return float(min(1.0, max(0.0, relevance)))

    # ------------------------------------------------------------------ #
    # 统计
    # ------------------------------------------------------------------ #
    @property
    def stats(self) -> dict:
        return {"calls": self._call_count, "tokens": self._token_used}
