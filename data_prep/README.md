# 数据准备脚本集合 (data_prep)

> 适用于"科研场景下复杂学术查询的智能论文搜索与推荐"赛题
> 把已下载的 3 个核心数据集统一格式化为训练 + 评测可用的标准格式。

---

## 1. 目录结构

```
data_prep/
├── unify_data.py        # 主脚本：3 数据源 → 统一 jsonl
├── paper_index.py       # 论文库 embedding 索引
├── eval_runner.py       # 检索系统统一评测器
├── load_unified.py      # 训练/评测侧的数据加载 API
├── stats.py             # 数据统计 + 报告
├── requirements.txt     # 依赖清单
└── README.md            # 本文件

outputs/                 # 默认输出目录
├── unified_queries/     # unify_data.py 输出
├── paper_index/         # paper_index.py 输出
├── eval_results/        # eval_runner.py 输出
└── stats/               # stats.py 输出
```

---

## 2. 输入数据源

| 数据源 | 原始路径 | 记录数 | 角色 |
| ------ | -------- | ------ | ---- |
| AutoScholarQuery | `data/PaSa/AutoScholarQuery/*.jsonl` | 35,551 | 训练/评测：综述/主题类查询 |
| paper_finder_bench | `data/asta-bench/tasks/paper_finder_bench/*.json` | 333 | 评测：semantic / specific / metadata |
| LitQA2 | `data/litqa2/LitQA2/*.parquet` | 199 | 评测：4 选 1 知识问答 |
| 论文库 | `data/PaSa/paper_database/{id2paper.json,cs_paper_2nd.zip}` | — | 候选论文元数据/全文 |

---

## 3. 快速开始

```bash
# (1) 安装依赖
pip install -r requirements.txt

# (2) 统一数据格式
python unify_data.py --root /Users/yangyazhou/SakuraPaper

# (3) 构建论文索引
python paper_index.py --root /Users/yangyazhou/SakuraPaper --use-api --limit 5000
# 注意：--limit 用于控制联网次数，正式跑可去掉

# (4) 评测
python eval_runner.py \
    --gold /Users/yangyazhou/SakuraPaper/data_prep/outputs/unified_queries/test.jsonl \
    --predictions /path/to/your/predictions.jsonl

# (5) 统计
python stats.py --root /Users/yangyazhou/SakuraPaper
```

---

## 4. 统一数据格式

每行 jsonl：

```json
{
  "id":        "query_auto_AutoScholarQuery_train_0",
  "query":     "What works are related to the field of image retrieval?",
  "type":      "survey",
  "source":    "autoscholar",
  "gold_papers": [
    {"paper_id": "1909.11740", "title": "UNITER: UNiversal Image-TExt Representation Learning",
     "abstract": "", "year": null, "venue": "", "authors": []}
  ],
  "distractors":     [],
  "options":         [],
  "correct_answer":  "",
  "scorer_criteria": {},
  "original_id":     "AutoScholarQuery_train_0"
}
```

字段说明见 `outputs/unified_queries/README.md` (由 `unify_data.py` 自动生成)。

---

## 5. 脚本说明

### 5.1 `unify_data.py`

读取 3 个数据源，按统一 schema 写入：

- `outputs/unified_queries/all_queries.jsonl`
- `outputs/unified_queries/train.jsonl` (默认 80%)
- `outputs/unified_queries/test.jsonl`  (默认 20%)
- `outputs/unified_queries/by_source/*.jsonl`
- `outputs/unified_queries/by_type/*.jsonl`
- `outputs/unified_queries/README.md`

```bash
python unify_data.py --test-ratio 0.2 --seed 42
```

### 5.2 `paper_index.py`

抽取所有唯一 `paper_id` → 优先本地 zip → 回退 `id2paper.json` → 选 S2 API。
输出 `papers.jsonl` + `faiss.index` (+ `id_map.json`)。
若未安装 `faiss` / `sentence-transformers`，自动回退到 `HashingBow + numpy`。

```bash
python paper_index.py --use-api --api-rps 1.0
python paper_index.py --no-api          # 仅本地
python paper_index.py --limit 200       # 限制处理数
```

### 5.3 `eval_runner.py`

读 gold jsonl + 预测文件，计算并写出：

- `metrics.json`：Precision@K, Recall@K, F1, mean api_calls/tokens/latency
- `per_query.jsonl`：每条详情
- `report.md`：人类可读报告

预测文件支持 jsonl (每行一条) 或 json (顶层 list)，每条字段：

```json
{
  "id":     "query_xxx",
  "papers": [{"paper_id": "...", "score": 0.9, "markdown_evidence": "..."}],
  "answer": "...",   // LitQA2 时必填
  "metrics": {"api_calls": 4, "tokens": 1234, "latency_sec": 5.6}
}
```

### 5.4 `load_unified.py`

轻量 API，可被训练 / 推理脚本直接 import：

```python
from load_unified import load_queries, paper_index_lookup, compute_f1

train = load_queries("train")
paper = paper_index_lookup("1909.11740")
print(compute_f1(["A", "B"], ["A", "C"]))
```

### 5.5 `stats.py`

对 `all_queries.jsonl` + `papers.jsonl` 做统计：

- 各数据集样本数
- 唯一论文数
- 论文年份分布
- 查询长度分布
- gold_papers 长度分布
- 字段缺失率
- 学科分布 (按 source 推断)

输出 `outputs/stats/{summary.json, summary.md, figures/*.png}`。

---

## 6. CLI 帮助

每个脚本都支持 `-h/--help`，可查看具体参数。例：

```bash
$ python unify_data.py -h
$ python paper_index.py -h
$ python eval_runner.py -h
$ python load_unified.py -h
$ python stats.py -h
```

---

## 7. 错误处理约定

- 文件缺失：脚本会 log 警告/错误并跳过或返回非 0 退出码。
- zip/json 损坏：`paper_index.py` 自动回退到 `id2paper.json`，再回退到 S2 API。
- 缺网络/缺 API：日志提示，所有论文标记为 `source=missing`，索引仍可构建。
- 缺 `faiss`/`sentence-transformers`：自动回退到 hash-bow + numpy，索引以 `*.npy` 形式存储。

---

## 8. 致谢

- AutoScholarQuery 来自 PaSa / SPARBench
- paper_finder_bench 来自 AstaBench (Allen AI)
- LitQA2 来自 FutureHouse PaperQA2 / lab-bench
- 论文库 `cs_paper_2nd.zip` 来自 PaSa 仓库
