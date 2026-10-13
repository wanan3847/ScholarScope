# SPAR2 引擎设计（基于 SPAR 成熟方案的竞赛提分改造）

> 日期：2026-08-12。作者：Codex（superpowers brainstorming → writing-plans 流程产物）。
> 决策依据：在可实际运行的成熟方案中，SPAR 在 AutoScholarQuery 上公布 F1=0.3843，
> 超过 PaSa（0.2449）56.92%，且是免训练架构（可接 DeepSeek API，本机无 GPU 跑不动 PaSa-7B）。

## 1. 目标

把 SakuraScholar 的评分链路从"本地自研低分流水线"切换到**成熟的 SPAR 架构**，并做针对性提升，
使 `run_eval.py` 在 real_scholar / auto_scholar / litqa2 / paper_finder 上的 F1@K 显著高于
2026-08-09 实测的 F1@10=0.0171。

## 2. 评分口径（来自 docs/赛题整理_*.md 与 src/evaluation）

| 指标 | 权重 | 说明 |
| --- | --- | --- |
| F1@K (K=5/10/20) | 70% | arXiv（去版本）/ DOI（小写）/ S2 corpusId 三 ID 归一化后精确匹配 |
| 运行效率 | 20% | API 调用次数、Token 消耗、端到端延时 |
| 结构化输出 | 10% | JSON + Markdown 表格 + 关系图三件套 |

结论：先提 F1（召回+精排），同时控制 LLM 调用（预算：每条查询 ≤ 12 次 LLM 调用、≤ 30k token）。

## 3. 架构（SPAR 为主干 + 4 处关键改造）

```
Query ─▶ QueryPlanner(LLM×1) ─▶ keywords/end_date
          │
          ▼
  多通道检索（无 Google key 依赖）
   ├─ arXiv API（布尔 AND 关键词，替代 Google site:arxiv）
   ├─ OpenAlex search（语义全文检索；mailto → api_key 自动降级）
   ├─ CrossRef（query.bibliographic → DOI，服务 litqa2/paper_finder）
   └─ LocalCorpus（PaSa 20 万篇标题：BGE-small 语义 top-K + 词法倒排，离线零成本）
          │
          ▼
  去重 + ID 归一化（arxiv/doi/openalex/title）
          │
          ▼
  RelevanceJudge(LLM 批量 0~1 打分 + True/False) ─▶ 阈值过滤
          │
          ▼
  CitationExpander（top-5 种子 → OpenAlex referenced_works 1 跳引用扩展）→ 再判分
          │
          ▼
  排序（judge 分 > 引用数 > 年份）+ end_date 过滤 ─▶ top-10 输出
```

## 4. 相对 vanilla SPAR 的改进点

1. **QueryPlanner 输出短关键词**：SPAR 原版输出整句扩展查询（"survey papers on Give me papers
   which..."），对 arXiv/OpenAlex 词法引擎是灾难；改为 6 个判别性技术短语（如
   "in-context learning"、"data pruning"）。
2. **arXiv 通道**：替换 `google_search_arxiv_id`（无 Google key 403）为 arXiv API 布尔查询
   （`all:"k1" AND all:"k2"`），并支持 end_date 过滤。
3. **OpenAlex 通道**：`search=` 语义全文检索 + mailto polite pool；429 时自动降级到
   `api_key`（本机实测 2026-08-12 匿名池额度耗尽、key 通道 200）。
4. **新增 LocalCorpus 语义通道**：PaSa 官方 paper_database（199,447 篇 arXiv 标题）
   + BGE-small 标题向量（补全后覆盖全语料），解决"gold 标题与查询词面零重叠"的
   1/3 语义型查询。
5. **批量 LLM 判分**：SPAR 原版逐篇调用 similarity_code_v4（4 次重试）；改为一次性
   批量 prompt 打分，把 LLM 调用压到每条查询个位数。
6. **引用扩展**：启用 SPAR 的 RefChain（原版默认关闭），种子来自判分后的 top-5，
   通过 OpenAlex `referenced_works`（免费/付费通道）抓取，1 跳即可。
7. **端到端效率预算**：plan 1 次 + judge 2~4 次 + expand judge 1~2 次 + 标题解析
   （可选），目标 P50 < 60s、LLM 调用 < 12、token < 30k。

## 5. 兼容性

- 新引擎以 `SPAR2Engine.run(query, before_date)` 暴露，返回 `{papers:[{title, arxiv_id,
  doi, ids, score}], stats:{api_calls, tokens, elapsed_seconds}, ...}`。
- `run_eval.py --engine spar2` 选择新引擎；默认 `orchestrator` 保持不变（199 个单测全绿）。
- 结构化三件套：由 runner 已有的 `papers/table/relationships` 组装，10% 权重不丢。

## 6. 风险与对策

| 风险 | 对策 |
| --- | --- |
| S2 长期 429 → paper_finder 的 corpusId 映射失败 | 依赖 S2 恢复；litqa2 的 DOI gold 不受影响；代码保留 `_resolve_s2_corpus_ids` |
| OpenAlex key 每日 $1 额度耗尽 | mailto 优先、key 兜底；arXiv/本地语义/CrossRef 三通道保底 |
| DeepSeek 输出格式漂移 | prompt 给死格式 + 重试 2 次 + 解析兜底 |
| 本地语义索引未覆盖全部语料 | 后台补全 199,447 篇标题向量（已启动） |

## 7. 验收标准

- `real_scholar` 50 条全量：F1@10 ≥ 0.10（当前 0.0171），候选池 gold 召回率 ≥ 40%。
- `litqa2` 199 条：F1@10 ≥ 0.05（DOI 通道生效）。
- 效率：P50 延时 ≤ 90s，平均 LLM 调用 ≤ 12 次/条。
- `pytest tests/ -q` 199 个全绿（新增测试另计）。
