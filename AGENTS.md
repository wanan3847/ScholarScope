# AGENTS.md — 研索 ScholarScope

项目说明：研索（ScholarScope）是面向复杂学术查询的智能论文检索与推荐系统。

根 README 是项目唯一入口文档；改代码时保持文档同步。

## 常用命令（均在 `src/` 下）

- 启动 Web：`python3 -m uvicorn web.app:app --host 127.0.0.1 --port 8765`（页面 `/app`）
- 评测官方测试集：`python3 run_eval.py --n 5000 --benchmarks real_scholar auto_scholar paper_finder litqa2 --real --llm deepseek --output /abs/path.json`
- 单元测试：`/Users/yangyazhou/miniconda3/bin/pytest tests/ -q`（32 个，必须全绿）
- 真机 UI 测试：`node src/tests/ui_smoke.js`（Playwright + 无头 Chromium，需先起服务）

## 关键事实（2026-08-23 状态）

- **Web 界面**：收藏夹/已阅/文件夹/认证 API 可用（含默认收藏文件夹、按用户隔离的批量导入/导出、可编辑帮助文档、内置 admin 账号）。品牌为研索 ScholarScope，说明语为“面向复杂学术查询的智能论文检索与推荐系统”。
- **评测数据已本地化**：PaSa 官方集在 `data/PaSa/`（AutoScholarQuery 1000 + RealScholarQuery 50，
  与 `src/data/benchmarks/` 副本一致）；AstaBench paper_finder 267 条、LitQA2 199 条在
  `src/data/benchmarks/`；LitQA2 官方 parquet 在 `data/litqa2/`。
- **benchmark 指标口径**：论文 ID 精确匹配，arXiv（去版本）/ DOI（小写）/ S2 corpusId 三 ID 归一化任一命中即算中。该口径用于系统检索实验。
- **SPAR2 引擎 5 通道检索**：arXiv / OpenAlex / CrossRef / Semantic Scholar / 本地 PaSa 语义语料；
  免费额度（OpenAlex/S2）UTC 零点重置，评测请在北京时间 08:00 后启动（全通道分数才可比）。
- **外部 API 可用性决定 F1**：OpenAlex/S2 匿名额度耗尽时自动静默降级（候选池变小，
  但三件套的 2 跳引文 + 双规划可部分补偿）；arXiv API 偶发超时（已加重试 + 熔断）。
- **LLM 配置持久化**在 `src/data/llm_config.json`，`register_preset` 会自动兜底读 `.env` key。
- **收藏/已阅等 ID 路由**一律用 `{paper_id:path}`（DOI 带斜杠，普通路径参数会 404）。
- **SPAR2 常驻机制**：并行 5 通道检索（40s/通道硬超时）+ 迭代检索（最多 3 轮 BFS）、
  文档驱动查询 + 标题词补充、OpenAlex 摘要补全、RefChain 双向引文（API 模式 2 跳）、
  BGE 语义预筛 + 保底（0.70/0.20/0.10，阈值 0.40）、top-30 相对精排（仅 API 模式）、
  deadline 逐批截断 + 并行判分；本地模型（ollama）自动跳过精排/双规划（实测反效果）。
- **本地模型工作流**：先本地 ollama（`SAKURA_LLM_PROVIDER=ollama --llm ollama`，免费）
  迭代验证，效果可接受后再用 DeepSeek（`--llm deepseek`）确认；评测进程用
  `scripts/run_eval_daemon.py` 守护启动防误杀。
- **`run_eval.py` 输出路径**：绝对路径或 `src/` 相对路径（`results/` 在仓库根，传相对路径会 404
  目录不存在——用绝对路径最稳）。
- **旧比赛材料**：集中保存在 `archive/previous_competition/`。旧赛题评分比例、评审标准和参赛要求仅作为历史材料；开展新比赛工作时，先读取新比赛官方规则，不得将旧标准当作当前评分依据，也不要在新材料中引用旧标准。
- **benchmark 实验记录**：`docs/评测记录.md` 记录系统检索实验数据，与竞赛评分标准分开使用；引用指标时注明测试集、模型、样本量和日期。

## 约定

- 文档里的时间用绝对日期，不留"今天/最近"。
- 检索后端失败必须静默降级，不能拖垮整条流水线（统一 `_safe_call` / 熔断器模式）。
- **前端不依赖浏览器 API 做关键逻辑；改动模板后用 `node --check` 校验内联 JS。**
- **项目结构**：ad-hoc 测试脚本在 `src/tests/ad_hoc/`，构建脚本在 `scripts/`，
  优化报告在 `docs/`。`.gitignore` 已创建，运行时数据（collections/read_papers/users 等）
  不会被提交。
