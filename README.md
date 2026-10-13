# 研索 ScholarScope

> 面向复杂学术查询的智能论文检索与推荐系统

研索（ScholarScope）是一个面向科研工作者的多 Agent 论文检索与推荐系统，针对复杂学术查询提供端到端处理：从查询理解、多源检索、迭代式搜索、RefChain 引文扩展，到结构化输出（JSON + Markdown 表格 + 关系图）与反馈闭环。

> **SPAR2 检索引擎**：系统评测使用基于 SPAR 架构改造的
> `SPAR2Engine`（`src/agent/spar2/`，`run_eval.py --engine spar2`）。
> 查询规划（关键词+语义短语）→ 5 通道检索（arXiv API / OpenAlex / CrossRef /
> Semantic Scholar / 本地 PaSa 语义语料）
> → BGE 语义预排 → LLM 批量判分 → RefChain 引用扩展 → 排序输出。
> 上一届比赛背景下形成的设计记录见 [旧比赛材料归档](archive/previous_competition/README.md)。

## 核心特性

- **SPAR2 流水线**：QueryPlanner 查询理解（关键词+语义短语）→ 5 通道检索（arXiv / OpenAlex / CrossRef / Semantic Scholar / 本地 PaSa 语义语料）→ BGE 语义预排 → LLM 批量判分 → RefChain 双向引文扩展（引用+被引）→ 排序输出
- **SPAR2 常驻创新机制**：迭代检索（BFS 多轮）/ 文档驱动查询生成 / RefChain 双向引文扩展 / BGE 语义预筛+保底 / 多通道检索 / 评测截止日期过滤
- **真实学术 API + 离线语料**：Semantic Scholar、OpenAlex（均无需 API key）以及 PaSa
  官方公开论文标题库的本地倒排/向量召回；S2 429 或断网时仍可复现检索结果。
- **多 LLM 支持**：MockLLM（离线）/ OpenAI / DeepSeek / 通义千问 / 智谱 GLM / 本地 Qwen
- **5 个评测 Benchmark**：AutoScholarQuery / RealScholarQuery / paper_finder_bench / LitQA2 / SPARBench（自建）
- **三件套输出**：JSON + Markdown 对比表 + HTML 关系图（自包含 SVG，离线可开），
  关系边由论文间相似度生成（`src/agent/graph_synthesizer.py`）
- **反馈闭环**：点击/复制/引用/跳过/隐藏/星级事件收集与奖励统计（`src/agent/feedback_loop.py`）
- **完全离线可跑通**：MVP 阶段不依赖任何 API key

## 快速开始

```bash
# 1. 安装依赖
cd src
pip install -r requirements.txt
# 以下命令都在 src/ 目录下执行；新开终端请先 cd src

# 2. 启动 Web 服务（主入口，浏览器打开 http://localhost:8765/app）
python3 -m uvicorn web.app:app --host 127.0.0.1 --port 8765

# 3. 离线 Demo（全 Mock，零依赖）
python examples/run_demo.py

# 4. 真实 API 搜索（无需 key，S2 + OpenAlex）
python examples/real_search_demo.py

# 5. 官方测试集评测（推荐：SPAR2 引擎）
python run_eval.py --n 10 --benchmarks real_scholar --engine spar2 --real --llm deepseek \
  --output /绝对路径/结果.json
```

## 使用真实 LLM

复制 `.env.example` 为 `.env`，填入对应 API key：

```bash
cp .env.example .env
# 编辑 .env，例如：
#   SAKURA_LLM_PROVIDER=deepseek
#   DEEPSEEK_API_KEY=sk-xxxx
```

支持 provider：

| provider | 模型 | 说明 |
| --- | --- | --- |
| `mock` | mock-llm-v1 | 离线关键词匹配（默认，零依赖） |
| `openai` | gpt-4o-mini | OpenAI 官方 API |
| `deepseek` | deepseek-chat | DeepSeek API（价格友好） |
| `qwen_api` | qwen-plus | 通义千问 DashScope 兼容 API |
| `glm` | glm-4-flash | 智谱 GLM（免费额度） |
| `qwen` | Qwen2.5-7B-Instruct | 本地 Qwen 模型（需 GPU） |

## MCP Server（Claude Code / Cursor 直接调用）

岗位化改造 P0：把检索/收藏/评测能力暴露为标准 MCP 工具，任意 MCP 客户端可直接调用：

```bash
cd src
python mcp_server.py --transport stdio      # Claude Code / Cursor 里配置为本地 MCP server
python mcp_server.py --transport sse --port 8766   # SSE 模式
```

仓库根已提供 `.mcp.json`，Claude Code 会自动加载 `scholarscope` 服务（如 python 环境不同，改 `command` 为你的解释器路径）。

| 工具 | 能力 |
| --- | --- |
| `search_papers` | 多通道检索（arXiv/OpenAlex/CrossRef/S2/本地语义 + LLM 判分） |
| `get_paper` / `get_references` / `get_citations` | 论文详情 + RefChain 双向引文扩展 |
| `save_favorite` / `list_favorites` | 收藏/个人库（按用户隔离） |
| `run_eval` | 跑官方 benchmark 评测（F1/Recall） |

依赖：`pip install -r requirements.txt`（新增 `mcp`）。

## 项目结构

```
SakuraPaper/
├── src/                          # 主源码
│   ├── config.py                 # 全局配置
│   ├── mcp_server.py             # MCP Server 入口（stdio/SSE）
│   ├── sakura_mcp/               # MCP 工具定义（检索/详情/收藏/评测）
│   ├── agent/                    # SPAR2 引擎 + 反馈闭环 + 结构化输出
│   │   ├── orchestrator.py       # 顶层编排器
│   │   ├── spar2/                # SPAR2 引擎（engine/query_planner/judge/
│   │   │                         #   retrievers/expand/normalize）
│   │   ├── graph_synthesizer.py  # 三件套输出
│   │   ├── feedback_loop.py      # 反馈闭环
│   │   ├── collections.py        # 收藏夹 / 已阅 / 文件夹 / 用户认证
│   ├── retrieval/                # 检索后端
│   │   ├── base.py               # RawPaper / BaseBackend
│   │   ├── semantic_scholar.py   # Semantic Scholar（真实 API）
│   │   ├── openalex.py           # OpenAlex（真实 API）
│   │   ├── arxiv.py              # arXiv
│   │   ├── pubmed.py             # PubMed
│   │   ├── multi_source.py       # FOS 路由 + 多源合并
│   ├── llm/                      # LLM 客户端
│   │   ├── base.py               # BaseLLM 抽象
│   │   ├── mock_llm.py           # MockLLM（离线）
│   │   ├── openai_compat.py      # OpenAI 兼容（OpenAI/DeepSeek/Qwen API/GLM）
│   │   ├── qwen.py               # 本地 Qwen
│   ├── evaluation/               # 评测
│   │   ├── metrics.py            # P@K / R@K / F1@K
│   │   ├── runner.py             # 评测 Runner（5 benchmark）
│   ├── data/                     # 数据结构 + 评测集
│   │   ├── paper_node.py         # PaperNode
│   │   ├── schemas.py            # Pydantic 模型
│   │   ├── benchmarks/           # 真实评测数据
│   │   │   ├── AutoScholarQuery/test.jsonl
│   │   │   ├── RealScholarQuery/test.jsonl
│   │   │   ├── paper_finder_bench/test_2025_05.json
│   │   │   ├── litqa2/test.jsonl
│   │   │   └── SPARBench/test.jsonl  # 自建（100 条）
│   ├── training/                 # 训练 / 微调
│   │   └── sscp.py               # ⑩ SSCP 自监督对比预训练
│   ├── utils/
│   │   └── tracer.py             # LangSmith 风格 trace
│   ├── web/                      # FastAPI Web 服务
│   │   ├── app.py                # 搜索 / 收藏 / 已阅 / 文件夹 / 认证 / LLM 配置等 REST API
│   │   └── templates/            # Web 前端界面
│   ├── tests/                    # 单元测试（当前 32 个，全绿）
│   │   └── ad_hoc/               # 手动验证脚本（pytest 自动跳过）
│   ├── prompts/                  # LLM prompt 模板
│   └── examples/                 # 演示脚本
├── docs/                         # 设计文档
│   ├── 评测记录.md
│   └── 岗位化改造方案.md
├── archive/previous_competition/ # 上一届比赛材料与旧评分依据
├── scripts/                      # 构建 / 评测辅助脚本
├── results/                      # 评测输出（运行时数据，不入库）
├── data_prep/                    # 早期数据准备脚本（比赛材料）
├── data/                         # 原始数据集
│   ├── PaSa/                     # PaSa 真实数据
│   └── asta-bench/               # AstaBench 数据
├── references/                   # 参考项目源码
└── .env.example                  # 环境变量示例
```

## 常用命令（均在 src/ 下）

```bash
# 启动 Web 服务（页面 / 与 /app）
python3 -m uvicorn web.app:app --host 127.0.0.1 --port 8765

# 官方测试集评测（--n 传大数即全量；绝对路径最稳）
python3 run_eval.py --n 5000 --benchmarks real_scholar auto_scholar paper_finder litqa2 \
  --real --llm deepseek --output /绝对路径/结果.json

# 单元测试（32 个，必须全绿）
/Users/yangyazhou/miniconda3/bin/pytest tests/ -q

# 真机 UI 冒烟（Playwright，需先起服务）
node src/tests/ui_smoke.js

# 预填充 S2 corpusId 缓存（评测前可跑，仓库根目录执行）
python3 scripts/prefill_s2_cache.py
```

## Web API

启动服务后访问：

- `GET  /`、`GET /app` — 项目展示首页 / 搜索使用界面（温暖学术风格）
- `POST /api/search` — 执行搜索（支持 `format=three_part` 三件套输出）
- `GET  /api/paper/{id}` / `/api/references/{id}` / `/api/citations/{id}` — 论文详情 / 参考文献 / 被引
- `POST /api/feedback`、`GET /api/feedback/report` — 反馈事件与统计
- `GET  /api/benchmarks`、`POST /api/eval` — 评测列表与触发
- `GET  /api/stats`、`GET /api/innovations`、`GET /api/health` — 系统统计 / 创新机制 / 健康检查
- 收藏相关：`GET/POST/DELETE /api/favorites[/{paper_id}]`、`GET /api/favorites/check/{id}`
- 已阅相关：`GET/POST/DELETE /api/read_papers[/{paper_id}]`、`GET /api/read_papers/check/{id}`
- 文件夹：`GET/POST /api/folders`、`GET/PUT /api/folders/default`（默认收藏文件夹）、
  `PUT/DELETE /api/folders/{folder_id}`、`POST /api/folders/{folder_id}/papers/{paper_id}`
- 用户认证：`POST /api/auth/register` / `login` / `logout`
- 账号管理：`POST /api/auth/change-password`（改密码后旧密码失效、其他会话下线）
- 批量导入：`POST /api/favorites/import`（BibTeX / RIS / CSV / JSON，按 user_id 隔离）
- LLM 配置：`GET /api/llm/models`、`POST /api/llm/register` / `unregister` / `test`、
  `GET /api/llm/presets`、`POST /api/llm/register_preset`、`GET /api/llm/aggregator_models/{provider}`
- API 配置：`GET/PUT /api/settings/api`（OpenAlex / S2 key，界面填写、存储脱敏）

Web 界面功能：品牌首页（介绍页，顶栏布局与搜索页一致，图标可直达 /app 对应面板）
与搜索页、收藏夹（文件夹管理 + BibTeX/RIS/CSV/JSON 导入导出）、
已阅标记、搜索历史、检索后端/创新模块开关、大模型配置弹窗（预设/已注册/自定义/当前使用）、
本地账号体系（登录/注册/改密码/登出，右上角头像进入账号面板）、
右上角「帮助」文档弹窗（用户使用手册：快速上手/收藏夹/导入导出/账号/设置/常见问题，
管理员可编辑）、设置里可直接填写 OpenAlex / S2 API key（不用改 .env）、
界面默认放大 15%（字大一点不难受）。
收藏夹：移动/移除按存储的真实论文 ID（arXiv / DOI）操作，DOI 收藏也可正常跨文件夹移动；
可设置「默认收藏文件夹」，新收藏自动进入该文件夹；在某个文件夹里导出时只导出该文件夹、
导出文件名跟随文件夹名（如 `tabpfn.bib`）。

注意：Web 搜索始终走真实 SPAR2 多通道检索（arXiv/OpenAlex/CrossRef/S2/本地语义），
前端已移除无效的“真实 API / 结构化输出”开关（SPAR2 固定全通道检索）；
Web 模式 deadline 60s、接口硬超时 75s（外部 API 额度耗尽或网络慢时可能返回 504，
可稍后重试）。评测模式不受此限制（`run_eval.py` 使用 170s deadline）。
帮助文档内容存放在 `src/data/docs_content.json`，管理员可在文档弹窗里直接编辑。
内置管理员账号：`admin` / `admin123`（启动时自动创建，可用 `.env` 的
`SAKURA_ADMIN_USER` / `SAKURA_ADMIN_PASSWORD` 覆盖；文档弹窗里也写了提示）。

## 系统评测

### 1. 基准测试集

系统检索实验使用以下公开 benchmark（数据已下载到本地，无需联网下载）：

| 来源 | 测试集 | 本地位置 | 规模 |
| --- | --- | --- | --- |
| [bytedance/pasa](https://github.com/bytedance/pasa) | AutoScholarQuery test | `data/PaSa/AutoScholarQuery/test.jsonl`（= `src/data/benchmarks/AutoScholarQuery/test.jsonl`） | 1000 |
| bytedance/pasa | RealScholarQuery test | `data/PaSa/RealScholarQuery/test.jsonl`（= `src/data/benchmarks/RealScholarQuery/test.jsonl`） | 50 |
| [allenai/asta-bench](https://github.com/allenai/asta-bench) | paper_finder_bench | `src/data/benchmarks/paper_finder_bench/test_2025_05.json` | 267 |
| allenai/asta-bench | LitQA2 | `data/litqa2/LitQA2/*.parquet`（= `src/data/benchmarks/litqa2/test.jsonl`） | 199 |

注册表 Key：`auto_scholar` / `real_scholar` / `paper_finder` / `litqa2` / `sparbench`（自建抽样）。

### 2. 怎么跑

先配置真实 LLM（`cp .env.example .env`，填 `DEEPSEEK_API_KEY`，`SAKURA_LLM_PROVIDER=deepseek`），
然后在 `src/` 下执行：

```bash
# 快速验证（每个测试集前 10 条，真实检索 + DeepSeek）
python run_eval.py --n 10 --benchmarks real_scholar auto_scholar paper_finder litqa2 \
  --real --llm deepseek --output /absolute/path/quick.json

# 全量评测（--n 传一个大于样本数的值即跑全量；real_scholar 全量 50 条
# DeepSeek 约 1.5-2 小时、本地 qwen3 约 3 小时；建议守护方式启动）
python run_eval.py --n 5000 --benchmarks real_scholar auto_scholar paper_finder litqa2 \
  --real --llm deepseek --output /absolute/path/full.json

# 只看某一个
python run_eval.py --n 5000 --benchmarks real_scholar --real --llm deepseek --output /absolute/path/real_scholar.json
```

输出 JSON 含 `macro_metrics`（F1@5/10/20、Recall、Precision）、`efficiency`
（API 调用 / Token / P50-P99 延时）与逐条 `detailed`。

### 3. 指标口径与已知限制

- **F1 按论文 ID 精确匹配**：arXiv ID（去版本）/ DOI（小写）/ S2 corpusId 三 ID 归一化后
  任一命中即算中；paper_finder 的 gold 是 S2 corpusId，本地评分时通过 S2 batch 接口
  原位映射预测 ID —— **S2 限流（429）时该项会显示 0 分，等 S2 恢复后重跑即可**。
- **语义型 gold 依赖 S2/OpenAlex**：如 "diffusion models + RL" → `Planning with Diffusion`
  （标题/摘要不含查询词），关键词检索找不到，需语义通道。无 S2 key 时真实模式会额外生成
  一条去问题措辞的“标题风格”查询，与 AND 查询并行送入 OpenAlex/CrossRef；S2 恢复后
  自动全量生效。该降级不读取评测 gold，适用于隐藏集。
- **效率指标**：SPAR2 真实模式 DeepSeek P50 ≈ 176-181s、API 调用 24-54 次/条；
  本地 qwen3 P50 ≈ 205s、33 次/条（每查询硬超时 170s，`SPAR2_DEADLINE` 可调）。
- **当前最佳（2026-08-22）**：RealScholarQuery DeepSeek 20 条三件套 F1@10=**0.1055**、
  本地 qwen3 全量 50 条 F1@10=0.0893，详见 [docs/评测记录.md](docs/评测记录.md)。
- **参考基线**：AutoScholarQuery PaSa-7B Recall@20 = 0.708；RealScholarQuery PaSa-7B Recall@20 = 0.733。

历次评测结果、优化空间与重跑方法见 [docs/评测记录.md](docs/评测记录.md)。

## 测试

```bash
cd src
pytest tests/ -v
```

## 文档

- [评测记录](docs/评测记录.md)
- [项目改造方案](docs/岗位化改造方案.md)
- [旧比赛材料归档](archive/previous_competition/README.md)

## 致谢

本项目借鉴了以下优秀工作：
- [PaSa](https://github.com/bytedance/pasa) — LLM Agent for Comprehensive Academic Paper Search
- [SPAR](https://github.com/bytedance/SPAR) — Sub-graph PaSaR
- [ScholarCopilot / AI2ScholarQA](https://github.com/allenai/ai2-scholar-qa)
- [PaperQA2](https://github.com/future-chem/paper-qa)
- [AstaBench](https://github.com/elicit/asta-bench)

评测数据来自 PaSa 与 AstaBench 官方发布。
RealScholarQuery 全量基线（2026-08-09）：F1@10=0.0171、Recall@20=0.0292；
2026-08-11 关键词 AND + PaSa 截止日期修复的小样本（5 条）F1@10=0.0285、
Recall@20=0.0268。该结果仍低于 PaSa-7B 参考线，不能宣称达标；完整验收以
`run_eval.py --n 50` 的真实网络结果为准。paper_finder 当前受 S2 429 影响。
