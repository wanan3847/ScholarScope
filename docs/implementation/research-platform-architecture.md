# 科研平台架构与依赖记录

记录日期：2026-10-14。根 [README](../../README.md) 是使用与开发入口。

项目内模块沿用首页提供的 Atelier Zero 设计语言，关键字体、PDF 字符映射、编辑器和交互在本地构建，不依赖 CDN。前端路由在既有文献工作台下增加科研项目上下文，逐项接入有实际接口与持久数据的研究模块。

| 边界 | 实现与约束 |
| --- | --- |
| 检索 | Web/MCP 使用 `agent.orchestrator.Orchestrator` 与 SPAR2；外部检索、模型调用分阶段限时；结果只能来自真实标题/摘要 |
| 账号 | `agent.collections` 兼容已有资料；会话哈希、PBKDF2 与旧密码迁移，事务级文件锁及原子文件替换 |
| 项目与证据 | `workspace.store` 控制所有项目成员读写；统一文献、原文、证据、文稿、演示、图表和版本，乐观并发及审计 |
| 数据库 | SQLAlchemy Core 的 SQLite / PostgreSQL；显式 schema 版本、CLI 初始化/迁移与空目标恢复；恢复保持 ID 与依赖关系 |
| 原文 | `workspace.documents` 真实 PDF 解析，受限子进程、大小/页数/加密/扫描件状态；文件按 SHA-256 寻址，本地或有时限的 S3 接口 |
| 检索问答 | `workspace.knowledge` 保存来源段落，SQLite FTS5 / PostgreSQL GIN 与 pgvector；本地多语言模型，模型失败退回关键词 |
| 矩阵与筛选 | `workspace.research_tools` 只从可核对原文提取候选；人工修改保留；摘要/全文与每位审阅者的判断独立持久保存 |
| 综述 | `workspace.writing` 校验富文本节点与项目引用；章节草稿来自证据原文，统一生成实际参考文献与 DOCX/PDF/Markdown |
| 演示 | `workspace.presentations` 保存可编辑页面/品牌/来源版本；PptxGenJS 将文本、形状、数据图表及备注生成为原生 Office 对象 |
| 图表 | `workspace.charts` 区分报告值、研究者数据与派生数据；核对数值出处、轴和单位；Matplotlib 生成 SVG/PNG |
| 任务 | `workspace.runtime` 计划、乐观租约、持久步骤、受限子进程、预算/取消/恢复与幂等产物；`workspace.skills` 从项目原创指令发现版本与工具契约，不能以文本注入代码 |
| 资料审查 | `workspace.review` 核对实际来源、方法/结论关联及资料覆盖，保留未知与摘要边界，不虚构实验评价 |
| 资料与产物 | `workspace.library` 项目标签/集合/引用和 Excel 出处；`workspace.artifacts` 保存真实导出字节、证据版本与依赖、私有 ZIP 来源清单 |
| API | `web.workspace_api` 只适配请求、会话和错误；领域逻辑供 API 与后续任务执行器共用 |
| 开放全文 | `workspace.sources/network` 只解析实际元数据和 PDF；公开 DNS/IP 与 TLS、重定向和预算校验 |
| Zotero | `workspace.zotero/vault` 使用固定官方 API 与版本头；账号加密连接不进入共享数据，双端冲突明确选择 |
| 文献动态 | `workspace.monitoring` 保存问题、已见来源及周期；持久任务执行实际检索，参考关系来自数据库记录 |
| 备份 | `workspace.backup` 保存真实数据库、文件与可选运行账号/配置；私有文件权限 0600；拒绝覆盖非空目标，校验文件哈希 |

## 依赖与许可来源

安装版本及依赖许可证文件路径见 [依赖清单](dependency-licenses.json)，用 `scripts/audit_licenses.py` 从实际安装的包与 npm lock 重建。第三方许可证原文保存在 `frontend/public/brand/THIRD_PARTY_NOTICES.txt`，生产构建复制到本地品牌资源。

| 使用组件 | 上游许可 / 来源 |
| --- | --- |
| PDF.js | Apache-2.0；[Mozilla 仓库](https://github.com/mozilla/pdf.js/blob/master/LICENSE) |
| Tiptap 开源编辑器 | MIT；[Tiptap 仓库](https://github.com/ueberdosis/tiptap/blob/main/LICENSE.md)。未引入其付费协作服务，版本/评论/并发由项目自身实现 |
| PptxGenJS | MIT；[项目仓库](https://github.com/gitbrent/PptxGenJS/blob/master/LICENSE) |
| SQLAlchemy | MIT；[项目仓库](https://github.com/sqlalchemy/sqlalchemy/blob/main/LICENSE) |
| PostgreSQL / pgvector | PostgreSQL License；[PostgreSQL](https://www.postgresql.org/about/licence/)、[pgvector](https://github.com/pgvector/pgvector/blob/master/LICENSE) |
| psycopg / psycopg-binary | LGPL-3.0-only；保留发行包许可，独立安装的 Python 包动态使用，未修改或复制驱动代码；[上游许可](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt) |
| boto3 | Apache-2.0；[项目仓库](https://github.com/boto/boto3/blob/develop/LICENSE) |
| pypdf / pdfplumber | BSD-3-Clause / MIT；[pypdf](https://github.com/py-pdf/pypdf/blob/main/LICENSE)、[pdfplumber](https://github.com/jsvine/pdfplumber/blob/stable/LICENSE.txt) |
| python-docx / ReportLab | MIT / BSD；[python-docx](https://github.com/python-openxml/python-docx/blob/master/LICENSE)、[ReportLab 源码](https://github.com/MrBitBucket/reportlab-mirror) |
| Matplotlib / openpyxl | Matplotlib BSD 许可及历史许可 / MIT；准确文本包含在第三方许可汇总 |
| sentence-transformers 与默认多语言模型 | Apache-2.0；[库](https://github.com/huggingface/sentence-transformers/blob/master/LICENSE)、[模型页](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)。模型默认读取本地缓存，部署需另外准备权重及其许可 |
| SeaweedFS | Apache-2.0；[项目许可](https://github.com/seaweedfs/seaweedfs/blob/master/LICENSE)。用于独立临时 S3 服务实测，产品只连接用户选定的 S3 服务 |

未复制 Open Notebook、Kimi、SlidesCraft 或宿主科学技能代码。`src/workspace/skills/` 的十份科研技能说明为本项目原创，技能目录内 MIT 许可仅适用于这些原创指令；运行时加载版本、说明和白名单契约，不能执行任意代码。十项技能均绑定领域工具；Zotero 读取使用账号专用连接，远端写入仅由同步接口的明确导出触发。

首页内置的 Inter、Inter Tight、JetBrains Mono、Playfair Display 字体来自原设计资源，保留各自 `*-OFL.txt`；前端品牌目录的字体、许可证和第三方通知一并进入生产构建。

依赖清单包括运行包与前端构建依赖；双重许可包使用其 MIT 选项。动态依赖及字体应连同上述第三方文本保留在分发物内。该记录描述本次实际使用和复制情况，不能把某个参考项目的许可当作整个项目的许可。

接口依据：[Zotero v3](https://www.zotero.org/support/dev/web_api/v3/basics)、[版本化写入](https://www.zotero.org/support/dev/web_api/v3/write_requests)、[SeaweedFS S3](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API)。账号集成密钥使用 cryptography Fernet，保留其 Apache-2.0/BSD 许可文本；备份同时保存加密配置与私有解密文件，项目产物包不含连接配置。
