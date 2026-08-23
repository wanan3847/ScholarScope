# References - 参考系统与数据集

> 赛题：科研场景下复杂学术查询的智能论文搜索与推荐
> 下载时间：2026-07-01
> 用途：本地参考与基线对照

---

## 📦 源码仓库清单

| # | 名称 | 类型 | 来源 | 路径 | 大小 |
|---|------|------|------|------|------|
| 1 | **PaSa** | 源码 | [bytedance/pasa](https://github.com/bytedance/pasa) | `references/PaSa/` | 3.8M |
| 2 | **AstaBench** | 源码+评测 | [allenai/asta-bench](https://github.com/allenai/asta-bench) | `references/AstaBench/` | 4.3M |
| 3 | **SPAR** | 源码+基准 | [xiaofengShi/SPAR](https://github.com/xiaofengShi/SPAR) | `references/SPAR/` | 5.1M |
| 4 | **PaperQA2** | 源码(sparse) | [Future-House/paper-qa](https://github.com/Future-House/paper-qa) | `references/PaperQA2/` | 11M |
| 5 | **LitSearch** | 数据集 | [princeton-nlp/LitSearch](https://github.com/princeton-nlp/LitSearch) | `references/LitSearch/` | 208K |
| 6 | **AI2ScholarQA** | 源码 | [AI2ScholarQA](https://github.com/UKPLab/AI2ScholarQA) | `references/AI2ScholarQA/` | 9.2M |
| 7 | **OpenScholar** | 源码 | [allenai/openscholar](https://github.com/allenai/openscholar) | `references/OpenScholar/` | 9.6M |
| 8 | **DSPy** | 框架 | [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) | `references/DSPy/` | 1.2M |
| 9 | **ScholarCopilot** ⭐ | 学术写作+引用 | [TIGER-AI-Lab/ScholarCopilot](https://github.com/TIGER-AI-Lab/ScholarCopilot) | `references/ScholarCopilot/` | 388K |
| 10 | **deep-research** ⭐ | 通用深度研究 Agent | [dzhng/deep-research](https://github.com/dzhng/deep-research) | `references/deep-research/` | 188K |
| 11 | **PaSa-7B** | 模型权重 | [bytedance-research/pasa-7b-crawler](https://huggingface.co/bytedance-research) | `models/pasa-7b-{crawler,selector}/` | 30G 下载中 |

> ⭐ 与赛题相关性最高：ScholarCopilot（动态引用）、deep-research（递归 query 分解）、PaSa（RL 训练双 Agent）

### 未下载/网络受限项目（已识别）

- **ZeroSearch** (Alibaba-NLP) — LLM 模拟搜索，零 API 成本
- **DeerFlow** (bytedance) — 字节深度研究框架
- **AgentFlow** (lupantech) — Stanford+UW+上海AI 可训练多智能体
- **Search-R1** (PeterGriffinJin) — RL 训练 LLM 搜索能力
- **STORM** (stanford-oval) — 科研综述多轮专家检索
- **GPT Researcher** — 多源并行研究 Agent
- **AI-Researcher** (HKUDS) — Google AI Co-Scientist 开源替代

---

## 📊 数据集清单

### 评测基准

| 数据集 | 位置 | 样本数 | 说明 |
|--------|------|--------|------|
| **PaperFindingBench (test/val)** ⭐ | `data/asta-bench/tasks/paper_finder_bench/{test,validation}_2025_05.json` | ~50/100 | AstaBench 论文搜索核心评测 |
| **LitQA2** ⭐ | `data/asta-bench/litqa2_hf_cache/` | ~200 | Future House 全文检索 QA 基准（PaperQA2 用） |
| **LitQA2 Mapping** | `data/asta-bench/tasks/labbench/litqa2_mapping.json` | — | LitQA2 → PaperFindingBench corpus_ids 映射 |
| **E2E Discovery (dev/test)** | `data/asta-bench/tasks/e2e_discovery/` | 4 集 | 端到端科研发现评测 |
| **DiscoveryBench** | `data/asta-bench/tasks/discoverybench/` | 2 集 | 数据驱动假设发现 |
| **ScholarQA (SQA)** | `data/asta-bench/tasks/sqa/rubrics_v*.json` | 4 文件 | ScholarQA 评测 |
| **arxivdigestables** | `data/asta-bench/tasks/arxivdigestables/` | 3 文件 | arXiv digest 推荐 |
| **library_diagnostic** | `data/asta-bench/tasks/library_diagnostic/` | 3 文件 | 文献诊断 |
| **AutoScholarQuery (test)** | `references/SPAR/benchmark/AutoScholarQuery_test.jsonl` | 1000 | 学术论文搜索测试集，PaSa/SPAR 通用基线 |
| **SPARBench** | `references/SPAR/benchmark/spar_bench.jsonl` | 50 | 专家标注的真实查询，SPAR 自建基准 |
| **PaperFinder (样例)** | `references/AstaBench/astabench/evals/paper_finder/data.json` | 1 | Ai2 Paper Finder 评测样例 |

### 训练数据（PaSa）

| 数据集 | 位置 | 大小 | 说明 |
|--------|------|------|------|
| **AutoScholarQuery (train)** | `data/PaSa/AutoScholarQuery/train.jsonl` | 33M | PaSa 训练集 |
| **RealScholarQuery (test)** | `data/PaSa/RealScholarQuery/test.jsonl` | 7.6M | PaSa 真实场景测试集 |
| **SFT Crawler (train)** | `data/PaSa/sft_crawler/train.jsonl` | 27.4M | Crawler Agent SFT 数据 |
| **SFT Selector (test)** | `data/PaSa/sft_selector/test.jsonl` | 14M | Selector 评测集 |
| **SFT Selector (train)** | `data/PaSa/sft_selector/train.jsonl` | 51M | 下载中 |
| **Paper Database** | `data/PaSa/paper_database/id2paper.json` | 58M | 下载中 |
| **CS Paper 2nd** | `data/PaSa/paper_database/cs_paper_2nd.zip` | 2.4G | 下载中 |

---

## 🏗️ 四大参考系统对照

| 系统 | 核心方法 | 关键文件 | 性能参考 |
|------|----------|----------|----------|
| **PaSa-7B** | Crawler+Selector 双 Agent + RL 训练 | `PaSa/paper_agent.py` · `PaSa/paper_node.py` · `PaSa/agent_prompt.json` | RealScholarQuery Recall@20 超 Google+GPT-4o 37.78% |
| **SPAR** | RefChain 查询分解 + 查询演化 + 多 Agent | `SPAR/pipeline_spar.py` · `SPAR/search_engine.py` · `SPAR/rerank.py` | AutoScholar F1=0.38，超 PaSa 56% |
| **Ai2 Paper Finder** | 多索引语义检索 + LLM 改写 + 引文追踪 | `AstaBench/astabench/tools/paper_finder_ai2i.py` · `AstaBench/astabench/evals/paper_finder/` | PaperFindingBench 得分超 ReAct Agent 一倍以上 |
| **PaperQA2** | 全文检索 + LLM QA | `PaperQA2/src/paperqa/agents/` · `PaperQA2/src/paperqa/llms.py` | LitQA2 上表现优异 |

### 五大辅助系统

| 系统 | 核心方法 | 用途 |
|------|----------|------|
| **OpenScholar** | 8B 检索增强 LLM + 迭代检索 | 学术问答与综述 |
| **AI2ScholarQA** | 多 Agent + RAG | 学术 QA |
| **STORM** ⭐ | 专家式多轮检索 + 主题大纲 | **科研综述/论文写作**（与赛题思路接近） |
| **GPT Researcher** ⭐ | 多源（arXiv/web/news）+ 多 Agent | **通用深度研究**（可借鉴多源策略） |
| **DSPy** | 提示优化 + 模块化编程 | 优化 LLM 流水线 |

---

## 🔧 关键模块定位

### PaSa (`references/PaSa/`)
- [paper_agent.py](file:///Users/yangyazhou/SakuraPaper/references/PaSa/paper_agent.py) — Crawler+Selector 主流程
- [paper_node.py](file:///Users/yangyazhou/SakuraPaper/references/PaSa/paper_node.py) — 论文节点数据结构
- [models.py](file:///Users/yangyazhou/SakuraPaper/references/PaSa/models.py) — LLM 接口封装
- [agent_prompt.json](file:///Users/yangyazhou/SakuraPaper/references/PaSa/agent_prompt.json) — Agent prompt 模板
- [metrics.py](file:///Users/yangyazhou/SakuraPaper/references/PaSa/metrics.py) — Recall/Precision 评测

### SPAR (`references/SPAR/`)
- [pipeline_spar.py](file:///Users/yangyazhou/SakuraPaper/references/SPAR/pipeline_spar.py) — SPAR 主流程
- [search_engine.py](file:///Users/yangyazhou/SakuraPaper/references/SPAR/search_engine.py) — 检索后端
- [rerank.py](file:///Users/yangyazhou/SakuraPaper/references/SPAR/rerank.py) — 重排序
- [search_node.py](file:///Users/yangyazhou/SakuraPaper/references/SPAR/search_node.py) — 搜索节点
- [base_class.py](file:///Users/yangyazhou/SakuraPaper/references/SPAR/base_class.py) — 基础类
- [local_db_v2.py](file:///Users/yangyazhou/SakuraPaper/references/SPAR/local_db_v2.py) — 本地数据库
- [demo_app_with_front.py](file:///Users/yangyazhou/SakuraPaper/references/SPAR/demo_app_with_front.py) — Web 演示（带前端）
- [index.html](file:///Users/yangyazhou/SakuraPaper/references/SPAR/index.html) — 前端页面

### AstaBench (`references/AstaBench/`)
- [astabench/evals/paper_finder/task.py](file:///Users/yangyazhou/SakuraPaper/references/AstaBench/astabench/evals/paper_finder/task.py) — Ai2 Paper Finder 任务定义
- [astabench/evals/paper_finder/eval.py](file:///Users/yangyazhou/SakuraPaper/references/AstaBench/astabench/evals/paper_finder/eval.py) — 评测逻辑
- [astabench/evals/paper_finder/relevance.py](file:///Users/yangyazhou/SakuraPaper/references/AstaBench/astabench/evals/paper_finder/relevance.py) — 相关性判定
- [astabench/evals/litqa2/task.py](file:///Users/yangyazhou/SakuraPaper/references/AstaBench/astabench/evals/labbench/litqa2/task.py) — LitQA2 任务（PaperQA2 评测）
- [astabench/tools/paper_finder_ai2i.py](file:///Users/yangyazhou/SakuraPaper/references/AstaBench/astabench/tools/paper_finder_ai2i.py) — Paper Finder AI2I 工具实现
- [solvers/paper_finder/](file:///Users/yangyazhou/SakuraPaper/references/AstaBench/solvers/paper_finder/) — Paper Finder 求解器（含 demo.sh）

### PaperQA2 (`references/PaperQA2/`)
- [src/paperqa/agents/main.py](file:///Users/yangyazhou/SakuraPaper/references/PaperQA2/src/paperqa/agents/main.py) — Agent 主流程
- [src/paperqa/agents/search.py](file:///Users/yangyazhou/SakuraPaper/references/PaperQA2/src/paperqa/agents/search.py) — 文献检索 Agent
- [src/paperqa/agents/tools.py](file:///Users/yangyazhou/SakuraPaper/references/PaperQA2/src/paperqa/agents/tools.py) — 工具集
- [src/paperqa/llms.py](file:///Users/yangyazhou/SakuraPaper/references/PaperQA2/src/paperqa/llms.py) — LLM 接入
- [src/paperqa/core.py](file:///Users/yangyazhou/SakuraPaper/references/PaperQA2/src/paperqa/core.py) — 核心逻辑
- [src/paperqa/prompts.py](file:///Users/yangyazhou/SakuraPaper/references/PaperQA2/src/paperqa/prompts.py) — Prompt 模板
- [src/paperqa/clients/](file:///Users/yangyazhou/SakuraPaper/references/PaperQA2/src/paperqa/clients/) — 学术 API 客户端（Semantic Scholar、OpenAlex、Crossref 等）

### STORM (`references/STORM/`) ⭐
- 斯坦福 OVAL 实验室出品
- **核心思路**：Topic → Outline → 多轮专家式检索 → 文章
- 参考其 **query 分解 + 迭代检索 + 引用追踪** 策略

### GPT Researcher (`references/GPTResearcher/`) ⭐
- 通用深度研究 Agent
- **核心思路**：Plan → Parallel Research → Filter → Write
- 参考其 **多源并行检索 + 任务规划** 策略

---

## 📥 后续可补充

1. **PaSa-7B 模型权重**（下载中）— [bytedance-research/pasa-7b-crawler](https://huggingface.co/bytedance-research/pasa-7b-crawler) & [bytedance-research/pasa-7b-selector](https://huggingface.co/bytedance-research/pasa-7b-selector)
2. **PaSa paper_database/cs_paper_2nd.zip**（下载中，2.4G）
3. **ASTA MCP 工具集** — 完整实现需要 ASTA_TOOL_KEY
4. **AGILE 论文与代码**（赛题参考文献[7]）— PaSa 论文[7]，需查证准确 arXiv ID
