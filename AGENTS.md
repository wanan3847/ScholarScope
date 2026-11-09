# AGENTS.md — 研索 ScholarScope

研索是面向研究者的文献检索、阅读和资料整理工作台。根 README 是项目唯一入口文档，改动代码时同步更新。

## 工作重点

- 优先解决真实研究问题：主题、方法、研究对象和明确约束与论文是否直接匹配。
- 在线检索入口为 `src/agent/orchestrator.py` 中的 `Orchestrator`，Web 与 MCP 共用 SPAR2 Agent。最终推荐按研究用途整理，不对外展示数值评分。
- 推荐理由必须基于检索到的标题或摘要，证据引用须能在原文片段中核对。引用量和期刊声望不决定推荐顺序；检索失败不生成占位论文。
- 保持收藏、已阅、文件夹、账号隔离、文献文件导入导出等功能可用。
- 设计参考 `/Users/yangyazhou/awesome-design-md`，使用克制、清晰、适合阅读的布局。

## 命令

在 `src/` 下启动：
`python3 -m uvicorn web.app:app --host 127.0.0.1 --port 8765`，页面 `/app`。

在 `src/` 下运行回归：
`python3 -m pytest tests/ -q`。

修改模板后必须提取内联 JavaScript 并用 `node --check` 校验。UI 检查使用 `src/tests/` 中的 Playwright 脚本，先启动服务。

## 约定

- 外部检索源与模型失败必须静默降级；每个阶段有时间预算，单源故障不能阻塞整个搜索。
- 前端关键功能不依赖外部 CDN、浏览器特有接口或实验性 API。
- DOI 包含斜杠，论文 ID 路由一律使用 `{paper_id:path}`。
- 账号、收藏、已阅、API 配置属于运行数据，不提交；不要在日志或回答中输出密钥。
- 文档日期使用绝对日期。
- 构建脚本放 `scripts/`，临时检验脚本放 `src/tests/ad_hoc/`，产品文档放 `docs/`，对外申报与比赛材料放 `比赛材料/`（索引见 `比赛材料/00-索引.md`）。
