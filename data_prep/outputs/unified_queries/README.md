# 统一查询数据 (unified_queries)

> 由 `unify_data.py` 整合自 3 个核心数据源，用于智能论文搜索与推荐赛题的训练与评测。

## 1. 文件结构

```
unified_queries/
├── all_queries.jsonl    # 全部统一记录 (jsonl)
├── train.jsonl          # 80% 训练子集
├── test.jsonl           # 20% 测试子集
├── by_source/           # 按数据源拆分
│   ├── autoscholar.jsonl
│   ├── paper_finder_bench.jsonl
│   └── litqa2.jsonl
├── by_type/             # 按查询类型拆分
│   ├── survey.jsonl
│   ├── specific.jsonl
│   ├── metadata.jsonl
│   └── semantic.jsonl
└── README.md            # 本文件
```

## 2. 统一字段

| 字段 | 类型 | 说明 |
| ---- | ---- | ---- |
| `id` | str | 全局唯一 ID，前缀 `query_auto_` / `query_pfb_` / `query_litqa_` |
| `query` | str | 自然语言查询 |
| `type` | str | `survey` / `specific` / `metadata` / `semantic` |
| `source` | str | `autoscholar` / `paper_finder_bench` / `litqa2` |
| `gold_papers` | list[dict] | 标准答案论文列表 |
| `distractors` | list[str] | (仅 LitQA2) 干扰项 |
| `options` | list[str] | (仅 LitQA2) 4 个选项 |
| `correct_answer` | str | (仅 LitQA2) 正确答案文本 |
| `scorer_criteria` | dict | (仅 paper_finder_bench) 评分细则 |
| `original_id` | str | 数据源内 ID，便于回溯 |

## 3. 统计概览

- 总记录数：**36083**
- 训练集：**28866** 条
- 测试集：**7217** 条

### 按数据源

- `autoscholar`: 35551 条
- `litqa2`: 199 条
- `paper_finder_bench`: 333 条

### 按查询类型

- `metadata`: 43 条
- `semantic`: 242 条
- `specific`: 247 条
- `survey`: 35551 条

## 4. 类型定义

- **survey**    — 综述/主题类查询 (如 '请给我推荐关于 X 的论文')
- **specific**  — 明确论文标题/作者/DOI 或 4 选 1 知识问答
- **metadata**  — 元数据/作者年份类 (如 '2012 年 David Harel 的论文')
- **semantic**  — 主题语义类，需结合多篇论文的相关性进行评估

## 5. 数据样例 (jsonl)

```jsonl
{"id": "query_auto_AutoScholarQuery_train_0", "query": "What works are related to the field of image retrieval?", "type": "survey", "source": "autoscholar", "gold_papers": [{"paper_id": "1909.11740", "title": "UNITER: UNiversal Image-TExt Representation Learning", "abstract": "", "year": null, "venue": "", "authors": []}], "distractors": [], "options": [], "correct_answer": "", "scorer_criteria": {}, "original_id": "AutoScholarQuery_train_0"}
```

## 6. 字段取值说明

- `gold_papers[].paper_id`：
    - AutoScholarQuery → arxiv id (字符串)
    - paper_finder_bench → Semantic Scholar `corpus_id` (字符串)
    - LitQA2 → 优先 S2 `corpus_id`；否则用 DOI 兜底
- `scorer_criteria`：
    - 包含 `known_to_be_bad` (负例 corpus_id) 和 `relevance_criteria` (加权评分项列表)
- `options[0]` 固定为正确答案，其余为干扰项 (LitQA2 专用)
