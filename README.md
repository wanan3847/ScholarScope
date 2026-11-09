# 研索 ScholarScope

面向研究人员、博士生和科研工程师的 Literature Intelligence Workspace。

研索是一个文献检索与阅读工作台：描述研究问题，查找最相关的论文，阅读摘要和推荐理由，将文献按课题收藏整理。支持已有文献文件导入及引用导出。

## 启动

```bash
cd src
pip install -r requirements.txt
python3 -m uvicorn web.app:app --host 127.0.0.1 --port 8765
```

- 线上：<https://scholarscope.041126.xyz/>（Cloudflare Tunnel → `127.0.0.1:8766`，服务端目录 `/opt/sites/scholarscope`，systemd 单元 `scholar-scope`）
- 首页：<http://127.0.0.1:8765/>（内容按窗口宽度铺满，页边距与工作台一致）
- 检索工作台：<http://127.0.0.1:8765/app>
- 科研项目：<http://127.0.0.1:8765/app#projects>

完整平台改造的 [开发任务书](docs/implementation/2026-10-14-research-workspace-taskbook.md) 基础模块已交付，正在补齐智能分析与真实检索效果，验收结果和外部接口边界见 [执行记录](docs/implementation/research-workspace-verification.md)，模块与许可见 [架构记录](docs/implementation/research-platform-architecture.md)。科研项目支持持久资料、成员权限、PDF 按页阅读、证据库、自定义比较矩阵、跨论文原文检索问答、双人筛选、综述编辑、科研图表和演示报告。研究任务实际调用这些工具，保留计划、核验确认、进度和产物；Zotero 同步、开放全文获取、文献动态与参考关系接入真实接口，容器模式支持 PostgreSQL/pgvector 与私有 S3。

项目数据默认保存在忽略提交的 `src/data/workspace/`，支持用 `SCHOLARSCOPE_DATABASE_URL` 选择 PostgreSQL，用 `SCHOLARSCOPE_S3_BUCKET` / `SCHOLARSCOPE_S3_ENDPOINT` 选择对象存储。项目接口通过 Bearer 会话识别账号；未登录用户使用共享匿名项目空间。证据保存来源哈希与位置，不能提交不在原文中的片段；修改证据会将依赖的研究产物标记为待复核。

项目问答使用本地 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 做语义与关键词联合检索，默认读取已缓存模型，不在请求中自动下载。没有可用模型时保留关键词检索；可设置 `SCHOLARSCOPE_ALLOW_MODEL_DOWNLOAD=1` 允许下载，或 `SCHOLARSCOPE_DISABLE_EMBEDDINGS=1` 禁用语义模型。配置可用模型后，回答综合跨论文方法与结果，矩阵按字段提取中文概括；每条概括须有实际原文引用并经过第二次语义核对。模型超时、无效引用或核对失败时回退到原文整理，界面标示实际生成模式和章节覆盖，资料不足时明确说明。模型选择已知原文片段 ID，后端附上原始片段，避免模型改写引文；明确的内部研究标记只解析为所引论文的原始标题，未知或错引标记被拒绝，语义核对仍须通过。问答可导出包含回答、原文引文和出处的 Markdown。矩阵提取保留原文候选，支持批量、列级重跑、人工修改与确认；人工修改的单元格不会被批量重跑覆盖。

综述草稿按项目证据组织章节，使用本地 Tiptap 编辑；引文、参考文献、来源变化检查、版本恢复和成员评论均持久保存。支持 Word、PDF、Markdown 导出。研究演示可生成 12 页组会、开题、答辩或论文讲解草稿，在线修改页面、要点、顺序、布局、备注和项目品牌，导出原生文本框可编辑的 PPTX、Markdown 或离线网页幻灯片。模型按章节检索相关原文并分批生成，字段标签不完整时仍可使用对应文本；去除重复片段、平衡不同论文，并为各章节及缺漏重试分配时间预算。比较型演示要点可引用两篇研究，全部出处保留在预览、导出备注和来源变化检查中。没有通过核对的模型结果时使用明确标识的原文整理；覆盖记录区分独立综合、摘要/结论复用、项目范围说明与未完成章节。草稿仍需要研究者完善论证。PPTX 服务端导出需要 Node.js 及 `npm ci --prefix frontend` 的依赖。

项目概览可编辑课题、查看近期资料/任务与待复核产物。知识库支持标签、资料集合、项目收藏/已阅、文件导入与 BibTeX/RIS/JSON/CSV 导出；矩阵可导出含原文出处的 Excel。写作模板支持研究者配置章节、引用格式、摘要/关键词限制、字号、纸张和页边距，并保存规范来源；通用模板不声称符合某一期刊。科研图表区分报告值、研究者数据和派生数据，核对数值、轴和单位，导出 SVG/PNG 并在 PPT 中复用为原生 Office 图表。

“研究任务”可启用按缺口补检索：保留原始主题、方法和年份约束，在共用 210 秒预算内最多执行八轮真实检索，达到目标数量即停止，并尝试取得可用公开全文。查询按目标参数、同义词和模型名称展开；原始研究问题用于每轮资格核对与最终推荐，符合条件的候选优先进入有限的模型判断预算。各轮保留新增、重复、拒绝数量及停止原因。年份条件发送到 arXiv、OpenAlex、Crossref，并在合并后再次核对；不为凑数量放宽条件。筛选建议保留原文依据，不替代成员的人工决定。任务保存实际工具计划，单步执行在受限子进程中，最多同时执行两个任务；支持取消、失败重试与中断恢复，已完成步骤和产物保留。证据核验阶段等待项目编辑者确认；确认后来源变化会重新核验。生成 Word/PPTX 文件与私有 ZIP 来源清单可在任务面板下载。项目内原创科研技能有版本、许可证与工具契约；自定义工作流只能选择白名单操作，十项技能均接入实际工具；Zotero 导入步骤使用当前账号的专用连接，写入远端库由同步面板的独立导出操作触发。

项目“文献同步”支持 Zotero 个人/群组库与集合、条目/标签/PDF 附件导入、元数据导出、增量版本和双向冲突选择。连接及进度按账号加密保存，项目成员只共享已导入资料，密钥不进入项目产物包。导出须先启用该账号的写入选项；远端版本变化时不覆盖。个人库实测需要有效凭据，目前验收覆盖官方公共 API 与接口契约。

使用自己的 Zotero 账号：

1. 打开工作台“登录账号”，登录或注册研索账号；进入“科研项目”，打开自己拥有或可编辑的项目，选择“文献同步”。
2. 点击“获取库 ID 和密钥”，在 [Zotero 官网](https://www.zotero.org/settings/keys) 登录自己的 Zotero 账号，创建用于研索的专用 API Key，允许读取对应文献库；导入附件时还需文件读取权限。
3. 在项目表单选择“个人库”，填写密钥页面的数字用户 ID 和 API Key；集合键可留空。点击“保存连接配置”，再点击“检查连接”验证读取权限，然后“增量导入到项目”。保存配置本身不表示远端认证成功；连接检查只读，不会导入或写入 Zotero。密钥只填网页表单。
4. 测试向 Zotero 导出时，密钥需有写入权限，并在表单启用“允许此账号将项目元数据导出到该 Zotero 库”，再点击导出。账号及私有连接保持隔离。用户 ID 与用户名不同，详见 [Zotero 官方文档](https://www.zotero.org/support/dev/web_api/v3/basics)。

知识库可按 DOI 取得真实元数据、查询开放 PDF 链接、下载解析公开 HTTPS 文件并核对来源。下载限制 25 MB、验证公开 DNS 地址和每次跳转、固定连接地址、保留 TLS 证书验证；不向跳转源转发账号密钥。阅读器批注随原文位置持久保存。扫描页使用本机 Poppler/Tesseract OCR，保留识别置信度和 PDF 位置；缺少依赖时仍可阅读原图。Docker 默认使用英文/简体中文 OCR，已通过实际中文扫描页解析验收；本机可用 `brew install poppler tesseract`，其他语言通过 `SCHOLARSCOPE_OCR_LANG` 指定已安装语言包。图表和公式可调用视觉模型对实际区域辅助解读，结果标为待人工核对，不自动写成已确认数据。

“研究动态”保存问题及年份范围，支持手动或按日/周检查；任务和已见记录跨重启保留，新发现相对于项目及检索已见资料，不冒称是刚发表的论文。检查可选择自动加入项目，暂停自动检查后可手动继续。参考关系来自 OpenAlex 实际记录，来源失败保留明确空状态。

存储已用独立的 PostgreSQL 17、pgvector 与 S3 服务实测，包含真实 PDF、跨语言向量检索、重新连接与备份恢复。本地管理命令从仓库根执行，数据库和对象存储连接通过上文环境变量配置：

```bash
python3 scripts/workspace_admin.py migrate
python3 scripts/workspace_admin.py backup /absolute/path/research-backup.zip
python3 scripts/workspace_admin.py restore /absolute/path/research-backup.zip
```

备份含账号、运行配置、加密集成记录及解密文件与研究文件，权限为 0600。恢复要求空数据库与空运行目录，并验证文件哈希；旧资料和已有备份不会被覆盖。

Docker 启动：从仓库根运行 `docker compose up -d --build`。默认 SQLite/本地文件；生成 `.env.storage` 后可使用 `compose.storage.yaml` 启动 PostgreSQL/pgvector 与认证 S3。镜像为非 root、只读根文件系统，语义模型是可选构建配置。完整命令、模型准备与备份恢复见 [容器部署](docs/implementation/container-deployment.md)。两种模式均已用实际 API、PDF、任务和恢复验证。

账号接口按会话隔离收藏、已阅、文件夹和导入，不接受客户端用户名作为身份。新密码使用 PBKDF2，旧密码哈希在成功登录后迁移；会话限时七天，令牌以哈希保存。新环境仅在显式设置 `SAKURA_ADMIN_PASSWORD` 时创建管理员（可用 `SAKURA_ADMIN_USER` 指定账号）；不再自动创建固定密码管理员。已有账号及其资料继续保留。

可以在页面模型设置中注册 DeepSeek、Ollama 或 OpenAI 兼容模型，在检索设置中配置学术数据源密钥。模型配置持久化在 `src/data/llm_config.json`，数据源配置通过 `/api/settings/api` 管理。未配置可用模型时，搜索按文本匹配降级。已检查本机 `qwen3.5:4b` 并注册 Ollama 研究模型，默认本地上下文限制为 8,192 token，研究上下文可用 `SCHOLARSCOPE_RESEARCH_CONTEXT` 调整；同一服务进程的本地推理串行，排队时间计入请求预算，空闲约 90 秒后释放模型内存；该本机配置是运行数据，不提交。容器中连接宿主机 Ollama 时使用 `http://host.docker.internal:11434/v1`。模型输出仍需研究者核对，当前尚未用独立评测证明达到市场同类产品的分析效果。

模型设置中的“本次检索使用的模型”用于检索请求；项目问答、综述、演示和研究任务自动使用可用端点中优先级最高的模型。用真实云端 API 验收项目功能时，用管理员账号配置端点，将云端优先级设为高于现有 Ollama，保存后先点击“测试”，再生成项目内容；API Key 只填设置表单。

模型设置的“预设提供商”直接复用现有注册、持久化、测试和路由服务，提供常用模型下拉框并支持自定义模型 ID；优先级可填写，新增表单默认为 30，已配置列表显示各端点优先级。更新同一官方提供商时 API Key 留空会保留已保存密钥，不覆盖为无凭据端点。2026-10-14 按官方目录核对常用选择，包括 [OpenAI](https://developers.openai.com/api/docs/models/gpt-4.1-mini)、[DeepSeek](https://api-docs.deepseek.com/)、[通义千问](https://help.aliyun.com/zh/model-studio/models)、[GLM](https://docs.bigmodel.cn/cn/guide/models/text/glm-4)、[Kimi](https://platform.kimi.com/docs/models) 和聚合提供商；列表不承诺账号权限或免费额度。新注册 DeepSeek 默认使用 `deepseek-flash`，Kimi 默认 `kimi-k2.6` 并适配固定温度参数；已保存的模型配置不会自动改写。Ollama 选项需要本机已安装模型，不触发下载。

Zotero 导出按[官方响应格式](https://www.zotero.org/support/dev/web_api/v3/write_requests)处理已保存、未变更与逐条失败结果；中断恢复先核对固定条目键，认证或网络失败时不会继续写入。单条字段错误保留重试状态并继续其他文献；共享报告只记录错误码和已识别字段，不保存远端可能回显凭据的原始错误。真实私有库连接需要在可联网服务中点击“检查连接”验证；接口契约通过不等于实际账号同步成功。

## 检索与阅读

用户验收按需求追踪、实际接口旅程、真实文件解析、浏览器操作和外部服务质量分层执行，计划及逐项边界见 [用户验收报告](docs/testing/user-acceptance.md)。在仓库根运行 `.venv/bin/python src/tests/run_acceptance.py`，会隔离账号/数据库、运行回归和构建、按环境条件启动自己的服务并执行五套 Playwright 用例，生成带 PASS/FAIL/BLOCKED 的报告；退出码 2 表示仍有阻塞，不能算全部通过。当前浏览器运行受端口限制，真实研究模型测试沿用用户后续 API 验收安排。

检索阶段异常现在返回脱敏的服务不可用提示，不把提供商原始异常放入响应或日志；失败不生成占位论文。该路径通过故障注入复现、修复并回归检查。

Web 与 MCP 的在线检索统一使用 `src/agent/orchestrator.py` 中的 `Orchestrator` 和 SPAR2 Agent：

1. 把研究问题转为标准学术术语和聚焦的检索短语，保留方法、任务、研究对象与明确年份约束。
2. 并行检索 arXiv、OpenAlex、Crossref、Semantic Scholar、Europe PMC 和本地文献索引；配置授权密钥后启用 Scopus，Crossref Plus 为可选配额，合并 DOI / arXiv 别名，去除重复标题。
3. 由 Agent 沿已检索文献的参考文献扩展候选，再根据标题和摘要按研究用途选择文献；推荐理由附带可核对的原文证据。最终推荐顺序不采用数值评分、引用量或 venue 声望。
4. 模型、语义模型或某个数据源不可用时使用剩余可用结果；无真实候选时返回空结果。摘要缺失时提示证据有限。

明确的深度学习、图神经网络、测井资料及目标参数约束先由标题/摘要核对，再进入用途选择；模型不可用时同样保留这些约束。2026-10-14 的真实测井验收以 30 篇为目标，首次仅得到 2 篇；后续补检索在约 210 秒、3 轮中保存 10 个真实候选，仍未达到目标。其中中子孔隙度曲线预测、测井/试井/地震融合和学位论文需按研究用途区分，推荐与项目资料显示适用范围提示。同标题且作者相符的预印本/出版版本保留关联版本与原始证据，不重复计数。真实模型网页流程已通过矩阵、问答、综述和 12 页报告的调用及 Word/PPTX 导出检查；目前综述和演示的 AI 综合仍会只覆盖部分章节。数量、全文或论证不足均保留实际状态，不补造论文；摘要不能替代全文研究评估。

推荐理由用于帮助选择阅读顺序，不替代原文阅读。年份筛选应用于所有来源，日期缺失的文献在指定年份时不列入结果。SPAR2 检索预算为 50 秒，最终用途选择最多 32 秒，接口保护上限 95 秒。Agent 最终选择失败时保留 SPAR2 多源和引文召回的候选，并标明降级模式。

点击列表文献进入阅读面板，查看完整摘要、推荐理由与可核对的证据片段；支持收藏、标记已阅、打开原文和引用导出。阅读器可以展开或打开独立窗口，并提供摘要摘录、阅读笔记、进度和标签。

高级筛选按返回文献的数据库来源、方法词、引用次数和代码链接过滤；缺失元数据不会被当作满足条件。方法对比表展示检索文本识别的方法、已有数据集信息和代码链接。知识上下文提供返回数据中的文献关系图、方法概念对应图和当前结果的发表时间分布；文本相似关系与引文分开，数据缺失时显示空状态。年份筛选仍在搜索 API 中执行。

## 文献库与文件

- 按课题建立文件夹，设置默认收藏文件夹，移动和移除文献。
- 导入 BibTeX、RIS、CSV、JSON 文件；导出全部收藏或单个文件夹。
- 本地账号支持注册、登录、修改密码；收藏、已阅、文件夹按用户隔离。
- 未登录用户使用服务器上的共享匿名文献库。
- 检索历史保存在浏览器，含缓存的结果，重新打开时可恢复。
- 保存的检索记录问题和年份条件；阅读笔记、摘录、进度和标签按账号保存在当前浏览器，独立阅读窗口同步笔记修改。这些新增本机资料不随文献文件导出，也不跨设备同步。
- `Cmd/Ctrl K` 快捷检索；文献列表使用上下方向键浏览，Enter 打开阅读，Escape 返回窄屏列表。
- 内置管理员可编辑帮助文档，内容存储在 `src/data/docs_content.json`。

## 设计

首页与工作台延续 `docs/design/Open-Design-Landing.zip` 的 Atelier Zero 风格：暖纸色 `#efe7d2`、浅骨色表面、墨色正文、珊瑚色主操作、衬线强调与点状分隔。首页保留拼贴封面和章节布局，所有产品入口进入真实工作台；场景预览标明阅读示意，不作为检索结果。`/app` 为三栏科研工作台，保留文献列表、方法对比、阅读与知识上下文、文献库、历史及设置。支持深浅色、展开阅读、独立阅读窗口和窄屏列表/阅读切换。

首页源码在 `frontend/landing.html`，共享字体、封面和首页样式/交互在 `frontend/public/brand/`，工作台源码在 `frontend/src/`。字体与关键资源本地提供，不依赖外部 CDN。视觉规范见 [前端设计语言](docs/design/DESIGN.md)，功能和保存范围见 [科研工作台设计](docs/design/research-workspace.md)（2026-10-13）。
前端构建（仓库根目录）：

```bash
npm ci --prefix frontend
node scripts/build_frontend.mjs
```

构建会生成 `src/web/static/ui/` 与 `src/web/static/brand/`，将首页安装到 `/`、工作台安装到 `/app`。首页检索路径可携带问题进入 `/app?q=...`，文献库与导入分别进入 `/app#favorites`、`/app#import`。开发可运行 `npm run dev --prefix frontend`，由 Vite 代理请求到已启动的 FastAPI 服务。

## MCP

```bash
cd src
python mcp_server.py --transport stdio
# 或
python mcp_server.py --transport sse --port 8766
```

仓库根 `.mcp.json` 已提供本地服务配置。`search_papers` 使用与 Web 相同的在线检索流程；论文详情、引用和被引查询、收藏操作可通过对应工具调用。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `src/agent/orchestrator.py` | Web 与 MCP 共用的 Agent 入口和用途选择 |
| `src/agent/spar2/engine.py` | 多轮检索、语义预筛、判别和引文扩展 |
| `src/agent/spar2/retrievers.py` | 多源检索与本地语义匹配 |
| `src/agent/collections.py` | 文献库、文件夹、已阅和账号 |
| `frontend/` | 全新 React 界面源码与组件 |
| `src/web/` | FastAPI 页面、API 和前端构建资源 |
| `src/sakura_mcp/` | MCP 工具 |
| `src/data/` | 运行配置与本地文献数据 |
| `src/tests/` | 自动回归与界面检查 |
| `scripts/` | 本地索引构建等辅助脚本 |
| `data/` | 本地评测数据集 |

本地文献索引使用现有论文语料，只将标题、摘要与书目资料用于搜索。

## 开发检查

```bash
cd src
python3 -m pytest tests/ -q
```

模板改动后提取内联 JavaScript 并执行 `node --check`；界面检查需先启动本地服务。运行时文献库、用户、密钥与缓存不提交。论文 ID API 使用 `{paper_id:path}`，支持带斜杠的 DOI。

从仓库根运行界面检查（首次安装浏览器）：

```bash
npm install --prefix .cache/ui-check playwright@1.64.0
.cache/ui-check/node_modules/.bin/playwright install chromium
node src/tests/ui_smoke.js
node src/tests/ui_research.js
node src/tests/ui_landing.js
node src/tests/ui_platform.js
python3 scripts/check_inline_js.py
```

界面检查使用受控检索、账号与文献库响应，不改动真实运行数据；覆盖首页筛选与场景切换、真实入口跳转、原有资料管理流程与筛选、关系图、笔记、标签、键盘导航和多窗口阅读，并检查 360 至 1920px 的首页与工作台响应式布局。截图输出到 `.cache/ui-check/screenshots/`。

平台检查另启隔离 API 与临时数据库，上传真实测试 PDF，核对矩阵、原文问答、写作、可编辑幻灯片、原生图表和带人工核验的实际任务流程，并重新打开 DOCX、PPTX 与 ZIP。测试资料明确为受控 fixture，不作为产品默认文献。

2026-10-14 基础工程验收曾通过 94 项 Python 回归、三套既有 UI 与平台 31 类检查、两种存储模式的容器与恢复。最新正式复验通过 **148 项 Python 回归**（含 24 条用户流程用例），生产构建、内联 JavaScript 校验及实际比较型 PPTX 的双来源导出检查通过。本轮隔离服务因执行环境网络限制未能启动，最新浏览器检查尚未通过；检索数量与模型生成效果留待真实 API 验收，不能沿用之前结果宣称新逻辑已达到市场同等效果。完整证据见执行记录。

## 参赛材料

对外申报与比赛材料集中在 `比赛材料/`：`常州大学智能体大赛/`（赛事文件、提交材料、计划书源文件与图表）、`江苏省青年发明家大赛/`（申报材料、模板、图表源文件）、`英迈云/`。软件著作权材料与截图保留在根目录 `软著/`。索引见 `比赛材料/00-索引.md`。

2026-11-03 的常州大学智能体创新大赛（赛道二 工具调度与自主任务智能体）提交材料由三个脚本生成：`bash scripts/build_cczu_agent_plan.sh`（计划书 PDF）、`python3 scripts/polish_cczu_plan_docx.py`（计划书 Word）、`python3 scripts/fill_cczu_signup.py`（报名表）。正文中的实测数字来自当日 `pytest tests/ -q`（148 passed，48.90 秒）与实机启动检查。

2026-10-14 的[正式申报材料](比赛材料/江苏省青年发明家大赛/申报材料/江苏省青年发明家创新大赛_人工智能+专项赛_参赛项目申报材料_研索ScholarScope.docx)按团队当前版本修订正文，保留需求、六项创新点、应用价值、后续计划与佐证目录。正文经中文字体渲染和逐页检查为 4 页，沿用已有工作流图，补充技术架构图、工程验证表与第三方来源说明；测试数字来自正式验收记录，未完成项如实列出。封面、已填写申报表、填写说明、承诺书、原有图片及正文以外的格式均保持原样，已做 XML 字节与渲染像素比对。早先的[独立正文建议稿](比赛材料/江苏省青年发明家大赛/申报材料/研索ScholarScope_申报书正文图表修订建议_2026-10-14.docx)保留作参考，以正式申报材料为准。

图表源文件位于 `比赛材料/江苏省青年发明家大赛/图表源文件/`；生成脚本为 `scripts/revise_competition_visuals.py`，使用文档技能的 Codex primary runtime。脚本只生成另存的建议稿；如建议稿已被人工修改，哈希检查会拒绝覆盖。

正文局部修订脚本 `scripts/correct_competition_body.py` 仅从任务备份生成 `.cache/competition-body-correction-20261014/candidate.docx`，不会写入正式申报材料；保留正文以外的 XML 字节和未修改的文档包部件，并输出保留范围校验记录。正式文件在候选稿逐页验收、原文件未被并发修改后更新。
