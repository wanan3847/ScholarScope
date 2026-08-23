# SPAR2 引擎实施计划

> **For agentic workers:** 执行本计划请使用 executing-plans，逐任务推进、每步验证。

**Goal:** 把评分链路切到 SPAR 架构改造的 SPAR2 引擎，使 4 个官方测试集 F1@K 显著提升。

**Architecture:** 独立 `src/agent/spar2/` 包；`run_eval.py --engine spar2` 接入；
旧 Orchestrator 与 199 个单测不动。

**Tech Stack:** Python 3.13 / DeepSeek API（OpenAI 兼容）/ arXiv API / OpenAlex / CrossRef /
fastembed(BGE-small) / 本地 PaSa 语料。

## Global Constraints

- LLM 通道：DeepSeek `deepseek-chat`，`src/agent/spar2/llm.py` 统一封装（读取 `DEEPSEEK_API_KEY`）。
- 检索端到端失败必须静默降级，不抛异常（与 AGENTS.md 一致）。
- ID 归一化复用 `src/retrieval/base.py::normalize_paper_id` / `paper_id_variants`。
- 评测输出路径用绝对路径。
- 改模板后用 `node --check`（本计划不涉及模板）。

---

### Task 1: SPAR2 包骨架 + LLM 客户端

**Files:**
- Create: `src/agent/spar2/__init__.py`
- Create: `src/agent/spar2/llm.py`
- Test: `src/tests/test_spar2_llm.py`

**Interfaces:**
- `SPAR2Engine`（Task 6 提供）`.run(query: str, before_date: str) -> dict`
- `llm.chat(prompt: str, max_tokens: int = 1500) -> str | None`：调用 DeepSeek，失败重试 2 次

- [ ] Step 1: 写失败测试（mock LLM 返回固定文本，断言 `llm.chat` 正常返回、异常时返回 None）
- [ ] Step 2: 运行测试确认失败
- [ ] Step 3: 实现 `llm.py`（requests 直连 DeepSeek，`DEEPSEEK_API_KEY` 环境变量）
- [ ] Step 4: 运行测试确认通过
- [ ] Step 5: commit

### Task 2: 查询规划器（QueryPlanner）

**Files:**
- Create: `src/agent/spar2/query_planner.py`
- Test: `src/tests/test_spar2_query_planner.py`

**Interfaces:**
- `plan_query(query: str, llm_chat) -> dict`：返回 `{"keywords": [6 个短技术短语]}`
  - 失败时返回 `{"keywords": []}`（下游降级为词法检索）

- [ ] Step 1: 写测试：mock LLM 返回 JSON，断言解析出 6 个 keywords；非法输出返回空列表
- [ ] Step 2: 跑测试确认失败
- [ ] Step 3: 实现（prompt 要求只输出 JSON；解析容错：去代码块、取首个 `{...}`）
- [ ] Step 4: 跑测试确认通过
- [ ] Step 5: commit

### Task 3: 多通道检索器

**Files:**
- Create: `src/agent/spar2/retrievers.py`
- Test: `src/tests/test_spar2_retrievers.py`

**Interfaces:**
- `search_arxiv(keywords, end_date="", max_results=20) -> list[dict]`（arxiv_id/title/abstract）
- `search_openalex(keywords, end_date="", per_page=25) -> list[dict]`（arxiv_id/doi/title/abstract/openalex_id/cited_by）
- `search_crossref(keywords, rows=20) -> list[dict]`（doi/title）
- `search_local(query, top_k=200) -> list[dict]`（arxiv_id/title，来自 `LocalCorpusBackend`）
- 每个函数失败返回 `[]`（静默降级）

- [ ] Step 1: 写单测：mock `requests.get` / `arxiv.Client` / `LocalCorpusBackend`，断言字段解析
- [ ] Step 2: 跑测试确认失败
- [ ] Step 3: 实现四个函数（arXiv 布尔 `all:"k" AND all:"k2"`；OpenAlex `search=`+mailto→api_key；
  CrossRef `query.bibliographic`；本地语义 `_semantic_rank`）
- [ ] Step 4: 跑测试确认通过
- [ ] Step 5: commit

### Task 4: ID 归一化与候选合并

**Files:**
- Create: `src/agent/spar2/normalize.py`
- Test: `src/tests/test_spar2_normalize.py`

**Interfaces:**
- `norm_arxiv(s) -> str`
- `merge_candidates(channels: list[list[dict]]) -> dict[key, doc]`：按归一化 ID 去重，
  每篇 doc 带 `ids: [arxiv, doi, corpusId]`、`score`（初始 0）、`source`

- [ ] Step 1: 写单测：arXiv 版本号归一化、DOI 小写化、跨通道去重合并
- [ ] Step 2: 跑测试确认失败
- [ ] Step 3: 实现
- [ ] Step 4: 跑测试确认通过
- [ ] Step 5: commit

### Task 5: LLM 相关性判分器 + 引用扩展

**Files:**
- Create: `src/agent/spar2/judge.py`
- Create: `src/agent/spar2/expand.py`
- Test: `src/tests/test_spar2_judge.py`

**Interfaces:**
- `judge_docs(query, docs, llm_chat, batch_size=8) -> list[float]`：批量打分 0~1
- `expand_citations(docs_top, llm_chat=None) -> list[dict]`：OpenAlex `referenced_works` 抓引用，
  失败返回 `[]`

- [ ] Step 1: 写单测：mock LLM 返回 `{"scores": [0.9, 0.2]}`；断言打分与失败降级
- [ ] Step 2: 跑测试确认失败
- [ ] Step 3: 实现 judge（prompt 要求 JSON 数组；解析失败重试 1 次；兜底词法分）
- [ ] Step 4: 跑测试确认通过
- [ ] Step 5: commit

### Task 6: SPAR2Engine 编排 + run_eval 接入

**Files:**
- Create: `src/agent/spar2/engine.py`
- Modify: `src/run_eval.py`（加 `--engine spar2`）
- Test: `src/tests/test_spar2_engine.py`

**Interfaces:**
- `SPAR2Engine.run(query, before_date="") -> dict`：
  `{"papers": [{"title", "arxiv_id", "doi", "ids", "score"}], "stats": {"api_calls", "tokens", "elapsed_seconds"}, "table", "relationships"}`
- 流程：plan → 4 通道检索 → 合并 → judge 过滤（≥0.5）→ top-5 种子引用扩展 → 再判分 →
  排序（score desc，cited_by desc）→ top-10；end_date 过滤（arXiv/OpenAlex 返回年份 > end_date 年剔除）

- [ ] Step 1: 写单测：mock 各通道 + LLM，断言 run() 返回 papers 结构、顺序、end_date 过滤
- [ ] Step 2: 跑测试确认失败
- [ ] Step 3: 实现 engine + run_eval 接入
- [ ] Step 4: 跑测试确认通过；`python3 -m py_compile` 全部文件
- [ ] Step 5: commit

### Task 7: 真机小样本评测 + 调参

**Files:**
- Modify: 无（调参改 `src/agent/spar2/` 内常量）

- [ ] Step 1: `python3 run_eval.py --n 10 --benchmarks real_scholar --engine spar2 --real --llm deepseek --output /tmp/spar2_rs10.json`
- [ ] Step 2: 检查 F1@K、耗时、失败率；按需调 judge 阈值/检索 per-page/top-K
- [ ] Step 3: `python3 run_eval.py --n 20 --benchmarks litqa2 --engine spar2 ...`
- [ ] Step 4: 记录结果到 docs/评测记录.md；commit

### Task 8: 全量评测 + 回归

- [ ] Step 1: real_scholar 50 全量；litqa2 199 全量；auto_scholar 100 子集
- [ ] Step 2: `/Users/yangyazhou/miniconda3/bin/pytest tests/ -q` 全绿（旧 199 + 新增）
- [ ] Step 3: 更新 README / docs/评测记录.md / docs/给新模型的交接文档.md
- [ ] Step 4: commit
