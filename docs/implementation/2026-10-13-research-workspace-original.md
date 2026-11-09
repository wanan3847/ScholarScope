# AI Research Workspace：基于开源 Skills 的科研平台深度改造方案

2026 年 10 月技术调研 · 面向可商业化的科研 Web 产品 · 参考 SciSpace / Elicit / NotebookLM

## 一、先确定技术路线

我建议你的平台采用：

多源学术检索引擎 + 科研证据数据库 + Research Agent + 可插拔 Skills + 文档/PPT 生成引擎。

这五层应当分开设计，而不是依赖一个拥有很多工具的通用大模型。

Research Web App

文献发现 / PDF Reader / Evidence Matrix / Review Writer / PPT Studio

Research Agent Runtime

Planner

Skill Registry

Tool Executor

Task State

Verifier

Artifact Manager

Literature Engine

Federated Search · Ranking · Citation Graph

Scientific Skills

Literature Review · Writing · Analysis · PPTX

Research Data & Evidence Layer

PostgreSQL · Full-text Index · Vector Search · Object Storage · Citation Provenance

这套架构的关键是职责划分：

- 检索引擎负责准确找到文献，而不是让 LLM 猜有哪些论文。
- Agent负责规划和编排跨模块任务。
- Skills负责规范某一类科研任务的执行方法。
- 专用工具负责真实的数据提取、验证、导出等确定性操作。
- 证据数据库保证综述、论文和 PPT 中的内容能够追溯到原始文献。

### 一个必须注意的商业化问题

GitHub 上公开的 Skill 不一定能直接复制到商业产品中。

例如，[Anthropic Skills](https://github.com/anthropics/skills) 里的 `pptx`、`docx` 等文档技能虽然公开了源码，但其许可证并不是普通 MIT 开源许可证，对复制、修改、分发和衍生作品有明确限制。因此，建议借鉴其工作流设计，不要未经许可直接将这些技能源码打包到自己的 SaaS。

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+1



相反，可以优先集成许可证允许商用的研究 Skills、Slidev、PptxGenJS 等工具。

## 二、已经找到的热门 Skills：优先集成哪些？

这里我把真正的 `SKILL.md` 技能、MCP 工具服务、独立科研框架分开。它们虽然都能增强 Agent，但集成方式不同。

### 2.1 最值得研究的三个仓库

[scientific-agent-skills/skills/torch-geometric/SKILL.md at main · K-Dense-AI/scientific-agent-skills · GitHub](https://images.openai.com/static-rsc-4/18zr4c6LYbLUkIP0ufmImFJ_XyA88tXmCKdG5CgGsUipN0tTpLjWLqMJMyPWqdvOv9ThSN3WtwPFBwkfDsXKT0au51xeeetc9N-7D8UCIJ6Eij2O-N0SUYdTSGiqRxO_Idv8pXgP2U15Kd8dvWvOP01DTxoJv8SbNvC4NWZ5YDM?purpose=inline)

[K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills)

&#x20;约 48.7k Stars

科研 Skills 主库

当前仓库列有 177 个科研 Skills，覆盖文献、论文写作、引用、科研 PPT、数据分析和学术审稿；还明确支持 Pi 等兼容 Agent。注意仓库总体使用 MIT，但仍需检查每个 Skill 的独立许可证。

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+1



[Co-STORM - The Rundown AI](https://images.openai.com/static-rsc-4/ys-cGsC_SA5BeEAXozSD5q9YCpmQN3ksm0tM-epU0IKSZAHVfZMQVFxIECYvHAQzWl--rzJAYKCkEP6d9eAP_47h-nDeQqtxxqKD9T2tZJK9FYf7ZDipmJpLWrs6B44D7XipjZAeiYAY7YkHwVyzNH63rNCzs3V1Gjd7vhcnbkY?purpose=inline)

[Stanford STORM](https://github.com/stanford-oval/storm)

&#x20;约 31.6k Stars

综述生成研究框架

并非普通 Skill，而是完整的研究与长文生成框架。值得改造的是多视角问题生成、证据收集、文章大纲和分节写作，而不是直接复制整个应用。

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+1



[Agent Skills – Codex | OpenAI Developers](https://images.openai.com/static-rsc-4/KzQBQ_fK2GX5Xjoe2TQQDZo_s-surGdBSDxlbmxYA9xIaLhZjjTanZoYWDYbbIugfzVd1uSHLKK7Dx0btXfwskEY1TKQtKlqqTXSuB3GZVCMWZd7SIL9GUR-uTvUCHN0UPO6rYhjQ1Vbi_Xbpya_R9sbRUWtYLfeA_y7FsmR-4Q?purpose=inline)

[OpenAI Skills](https://github.com/openai/skills)

&#x20;约 27.8k Stars

Skills 系统参考

适合参考 Skill 发现、加载、版本管理、目录规范与工具链的整合方式。需要按单个 Skill 的许可证判断是否允许移植，不能把整个仓库默认视为可商用组件。

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+1



Star 为检索时 GitHub 展示的近似值，会随时间变化；它代表社区关注度，不代表科研结果正确率或生产环境可靠性。

### 2.2 建议第一批集成的 10 个科研 Skills

以下均可在 [K-Dense 官方仓库](https://github.com/K-Dense-AI/scientific-agent-skills) 中找到实际技能文件。

| Skill                                                                                                                               | 对应产品功能             | 改造优先级 |
| ----------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ----- |
| [paper-lookup](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/paper-lookup)                                 | 多学术 API 检索与论文元数据获取 | P0    |
| [citation-management](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/citation-management)                   | DOI、BibTeX、参考文献核验  | P0    |
| [literature-review](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/literature-review)                       | 系统综述流程与证据综合        | P0    |
| [scientific-writing](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/scientific-writing)                     | 论文草稿、章节写作和内容审查     | P0    |
| [scientific-slides](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/scientific-slides)                       | 组会、开题、答辩 PPT       | P0    |
| [pyzotero](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/pyzotero)                                         | Zotero 文献库对接       | P1    |
| [peer-review](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/peer-review)                                   | 模拟审稿、问题检查、修改建议     | P1    |
| [scientific-visualization](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/scientific-visualization)         | SCI 图表规范与科研绘图      | P1    |
| [scientific-critical-thinking](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/scientific-critical-thinking) | 实验方法、研究结论批判性检查     | P1    |
| [venue-templates](https://github.com/K-Dense-AI/scientific-agent-skills/tree/main/skills/venue-templates)                           | 期刊及会议稿件模板          | P2    |

这些技能的具体功能和依赖，在仓库技能目录与原始 `SKILL.md` 中都有说明。

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+5



重点是 `paper-lookup`：它已经整理了 18 个学术 API 的使用方式，包括 OpenAlex、Crossref、Semantic Scholar、arXiv、PubMed、Europe PMC、CORE 等，而且包含分页、限流、标识符转换和返回值校验经验。很适合直接作为你设计检索适配器的参考。

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub



但是，不能把这 18 个检索调用都交给 LLM 每次自由选择。我的改造方案是：检索能力下沉为可靠的后端 API，Skill 只负责选择和组合这些 API。

### 2.3 补充三个可用的技术项目

| 项目                                                                | 类型                    | 建议用途                         |
| ----------------------------------------------------------------- | --------------------- | ---------------------------- |
| [arxiv-mcp-server](https://github.com/blazickjp/arxiv-mcp-server) | MCP 服务，约 3.2k Stars   | arXiv 论文、LaTeX 章节、文献监测       |
| [llm-for-zotero](https://github.com/ivorpad/llm-for-zotero)       | Zotero Research Agent | 借鉴 PDF 阅读、跨文献比较、技能加载交互       |
| [Slidev](https://github.com/slidevjs/slidev)                      | 演示文稿引擎 + Skill        | Markdown 驱动 PPT、公式、代码、Web 演示 |

其中 `arxiv-mcp-server` 提供本地文献处理服务，使用 Apache-2.0 许可证；Slidev 使用 MIT 许可证。`llm-for-zotero` 更适合作为交互和架构参考，不建议整体移植到 Web。

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+2



## 三、重点：科研网站的后端文献检索到底怎么实现？

先说一个重要区别：

论文数据库 ≠ 搜索引擎 ≠ 全文数据库 ≠ 大模型。

SciSpace、Elicit 这类产品的专有内部检索实现并没有在这里得到可验证的完整公开架构，因此不能声称它们一定使用了某套具体技术。

不过，构建同类平台的可行架构可以明确分成以下步骤。

### 3.1 文献检索的标准数据流

用户研究问题

“近三年测井曲线预测孔渗参数的深度学习模型”

Query Planner

意图识别 · 中英关键词 · 同义词扩展 · 年份/学科条件

OpenAlex

跨领域主检索

Semantic Scholar

相似论文/引用

Crossref

DOI/元数据

arXiv

CS/预印本

Europe PMC

生物医学

Institutional APIs

授权商业数据库

Canonical Paper Registry

DOI 归一化 · 版本关联 · 去重 · 元数据合并

Hybrid Ranking

关键词相关性 · 语义匹配 · 引用关系 · 时效性

Search Results + Evidence Retrieval

论文列表 · 引文关系 · OA 全文 · 项目文献库

这个流程里，LLM 主要参与查询规划和结果解释，而真实论文必须来自数据库的返回结果。

### 3.2 各数据源到底能提供什么？

| 数据源                                                           | 搜索论文   | 引用关系 | 全文获取        | 商业产品中的定位 |
| ------------------------------------------------------------- | ------ | ---- | ----------- | -------- |
| [OpenAlex](https://api.openalex.org)                          | 强      | 支持   | 部分 OA 内容    | 主检索源     |
| [Semantic Scholar](https://api.semanticscholar.org/api-docs/) | 强      | 强    | 部分 OA 链接    | 推荐、引文补充  |
| [Crossref](https://api.crossref.org)                          | 元数据检索  | 非核心  | 不主打         | DOI 核验   |
| [arXiv API](https://info.arxiv.org/help/api/index.html)       | 预印本    | 非核心  | arXiv 原文    | CS、数学、物理 |
| [Europe PMC](https://europepmc.org/RestfulWebService)         | 强      | 部分支持 | OA 子集全文 XML | 生物医学     |
| [Unpaywall](https://data.unpaywall.org/products/api)          | DOI 定位 | 不主打  | OA 位置       | 补充全文链接   |
| [Web of Science API](https://developer.clarivate.com/)        | 授权范围内  | 支持   | 取决于接口与许可    | 高级企业集成   |
| [Elsevier APIs](https://dev.elsevier.com/)                    | 授权范围内  | 产品相关 | 需内容权限       | 出版商授权集成  |

功能范围依据官方 API 文档，而不是假定这些数据库可随意抓取所有全文。

[image](https://www.google.com/s2/favicons?domain=https://help.openalex.org\&sz=32)

OpenAlex Help Center

+7



2026 年这里有两个尤其重要的更新：

- OpenAlex 现在有按调用类型计费的 API：每个账户有每日 1 美元免费额度，普通搜索每 1,000 次约 1 美元，列表过滤每 1,000 次约 0.10 美元。语义检索已由 OpenAlex 自己提供，无须首版自行建立亿级向量索引。

  [image](https://www.google.com/s2/favicons?domain=https://help.openalex.org\&sz=32)

  OpenAlex Help Center

  +2

- Unpaywall 的搜索端点已于 2026 年 9 月 18 日退役；它仍提供基于 DOI 的 OA 查询，但新产品的关键词文献搜索应使用 OpenAlex 等服务。

  [image](https://www.google.com/s2/favicons?domain=https://data.unpaywall.org\&sz=32)

  Unpaywall



这意味着，你第一版完全没必要爬取整个学术互联网，更不需要下载数亿篇论文自己建库。那你的目标应该是做一个 AI Research Workspace（科研智能工作台），定位类似：

- SciSpace：科研全流程 Agent。
- Elicit：文献深度分析和系统综述。
- NotebookLM：基于知识库的跨文献问答、报告及 PPT。
- Zotero：文献资产与引用管理。

我建议不要再做一个普通的 AI 文献搜索网站，而是做一个以科研项目为中心、能够持续积累文献证据并生成多种科研成果的 Web 平台。

## 1. 重点拆解的竞品

| 竞品                                               | 值得复刻的模块                         | 你应该重点研究什么                 |
| ------------------------------------------------ | ------------------------------- | ------------------------- |
| [SciSpace](https://scispace.com/)                | Research Agent、文献阅读、综述、论文写作、PPT | Agent 工作区、任务执行过程、不同工具间的协同 |
| [Elicit](https://elicit.com/)                    | 文献筛选、自动数据提取、系统综述                | 自定义对比列、证据矩阵、原文依据定位        |
| [NotebookLM](https://notebooklm.google.com/)     | 知识库、跨文献问答、报告、PPT                | 来源管理、三栏工作区、同一资料生成多种内容     |
| [ResearchRabbit](https://www.researchrabbit.ai/) | 引文网络、相似论文推荐                     | 文献之间的关系图与探索交互             |
| [Jenni AI](https://jenni.ai/)                    | 学术写作、引用插入                       | 文档编辑器与 AI 的融合方式           |
| [Gamma](https://gamma.app/)                      | AI 演示文稿                         | PPT 排版引擎、模板系统、在线编辑器       |

其中 SciSpace 已经提供可将文献综述转换为 Word/Markdown 和 RIS、由论文生成可编辑 PPTX 的专门 Agent。Elicit 也支持结构化数据提取，以及导出 Word、PDF、CSV、Excel 和参考文献格式。这些能力已经属于直接竞争领域，不能简单作为你的独有创新点。

[image](https://www.google.com/s2/favicons?domain=https://scispace.com\&sz=32)

SciSpace

+2



## 2. 我推荐的产品完整功能结构

Research Workspace

Project-centered · Evidence-grounded · Agent-driven

文献发现

自然语言检索 · 多数据源 · 智能推荐

文献知识库

PDF · Zotero · 标签 · 集合管理

深度阅读

全文问答 · 公式图表 · 原文定位

证据矩阵

批量提取 · 方法对比 · 研究空白

综述与论文

综述大纲 · 章节写作 · 真实引用

科研 PPT

组会汇报 · 开题答辩 · 论文讲解

统一 Research Agent 与证据溯源引擎

搜索、阅读、抽取、分析、写作和输出都共享同一个科研项目上下文

核心设计原则是：用户在“文献发现”中选中的论文，直接进入项目知识库；证据矩阵中的每个实验数据都能返回原始 PDF；综述中的引文能够追踪到真实论文；PPT 则复用这些经过确认的数据、图表和结论。

这条证据链比单独增加十几个 AI 工具更值得优先开发。

## 3. 前端设计：重点参考这三种交互

SciSpace：任务驱动式 Agent

研究目标输入、执行步骤、过程反馈和结果文件，适合作为 Deep Research 页面原型。

Elicit：结构化科研操作

先让用户定义研究问题，再引导筛选和数据提取，适合作为系统综述工作流原型。

SciSpace：研究文件工作区

任务产物以文件形式沉淀，避免研究结果只存在于聊天记录里。

Elicit：文献证据矩阵

按照用户定义的字段提取论文信息，是文献批量分析最值得借鉴的界面。

你的 Web 不建议把 AI 聊天窗口放在所有功能的中央。更高级的方式是根据任务切换工作台：

| 页面                  | 推荐布局                  |
| ------------------- | --------------------- |
| Research Dashboard  | 项目卡片、最近任务、文献动态        |
| Literature Explorer | 顶部搜索、左侧过滤、中部文献结果      |
| PDF Reader          | 左侧章节导航、中间 PDF、右侧 AI   |
| Evidence Matrix     | 全宽可编辑数据表、列级 AI 提取     |
| Review Writer       | 中间富文本编辑器、右侧引用和证据      |
| Presentation Studio | 左侧幻灯片导航、中间画布、右侧布局与 AI |
| Agent Workspace     | 中央任务过程、侧栏工具调用和产物      |

视觉方面建议参考 Linear、Notion、Raycast 的克制风格：灰白中性色、高密度信息、少量强调色、排版精准。科研产品的高级感主要来自专业信息架构和交互细节，而不是玻璃拟态、渐变或大量动画。

## 4. 可以直接复用的开源技术与项目

这是我认为最有实际开发价值的一部分。没必要把文献检索、PDF 解析、Agent、PPT 生成全部从零写起。

| 模块             | 开源项目 / 接口                                                                      | 在你的产品里承担什么          |
| -------------- | ------------------------------------------------------------------------------ | ------------------- |
| 文献检索           | [OpenAlex](https://docs.openalex.org/)                                         | 论文元数据、主题、机构、引用网络    |
| 文献推荐           | [Semantic Scholar API](https://api.semanticscholar.org/api-docs/)              | 相似论文、引文和学术关系        |
| DOI 核实         | [Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | DOI、作者、期刊、出版信息验证    |
| PDF 结构化        | [Docling](https://github.com/docling-project/docling)                          | 提取正文、表格、图表、公式及布局    |
| 学术 PDF 解析      | [GROBID](https://github.com/grobidOrg/grobid)                                  | 论文元数据、章节、参考文献解析     |
| 文献 RAG         | [PaperQA2](https://github.com/Future-House/paper-qa)                           | 有引用依据的跨文献问答         |
| Research Agent | [GPT Researcher](https://github.com/assafelovic/gpt-researcher)                | 任务规划、并行检索、深度报告生成    |
| 综述生成           | [STORM](https://github.com/stanford-oval/storm)                                | 多视角研究、提纲构建、长文生成     |
| PDF 阅读器        | [PDF.js](https://github.com/mozilla/pdf.js)                                    | PDF 显示、选区、页码和标注交互   |
| 论文编辑器          | [Tiptap](https://github.com/ueberdosis/tiptap)                                 | 学术富文本、引用组件、结构化编辑    |
| PPT 导出         | [PptxGenJS](https://github.com/beautifulai/PptxGenJS)                          | 生成真正可编辑的 PowerPoint |
| 幻灯片系统          | [Slidev](https://github.com/slidevjs/slidev)                                   | Markdown 驱动的在线幻灯片   |

上述库各有不同成熟度和许可证，商用前需要分别核对。尤其是一些看似开源的白板 SDK，其生产使用需要授权。

[image](https://www.google.com/s2/favicons?domain=https://help.openalex.org\&sz=32)

OpenAlex Help Center

+11



我倾向于这套技术架构：

Next.js + TypeScript + Tailwind CSS

Web UI · PDF Reader · Writer · Slides · Agent Console

Application API

FastAPI · 用户、项目、文献和任务接口

Agent Runtime

规划执行 · 工具调用 · 人工确认 · 任务恢复

Metadata

OpenAlex / Crossref

Parsing

Docling / GROBID

Storage

Postgres / pgvector / S3

Unified Evidence Store

论文 → PDF 位置 → 提取事实 → 引用 → 综述/PPT

检索接口要特别注意：OpenAlex、Semantic Scholar、Crossref 可以提供大量论文元数据，但元数据访问权限不等于论文全文使用权限。不要把自动下载 Web of Science、ScienceDirect 付费全文作为未经授权的默认能力。优先支持开放获取全文，以及用户自己上传的 PDF。

[image](https://www.google.com/s2/favicons?domain=https://help.openalex.org\&sz=32)

OpenAlex Help Center

+2



## 5. 首版 MVP 到底先做什么？

如果是你自己主导开发，我建议分成三个版本，而不是一次做完全部功能。

| 功能                  | V1 核心闭环       | V2 科研生产力   | V3 平台化        |
| ------------------- | ------------- | ---------- | ------------- |
| 跨源文献搜索              | 完整            | 语义推荐       | 高级检索          |
| 文献库及 PDF            | 完整            | Zotero 同步  | 团队共享          |
| 多文献 AI 问答           | 完整            | 复杂图表理解     | 证据验证          |
| 文献对比矩阵              | 基础字段提取        | 自定义字段、批量提取 | 系统综述审查        |
| 自动生成综述              | 有引用的结构化初稿     | 富文本编辑与引用同步 | 多版本协作         |
| PPT 生成              | 大纲、模板、PPTX 导出 | 在线编辑及图表复用  | 品牌模板与协作       |
| Deep Research Agent | 基础任务编排        | 多阶段任务与审查   | 自定义 Agent 工作流 |

首版最有价值的演示闭环可以是：

用户输入“近三年基于测井曲线预测孔隙度、渗透率的深度学习方法” → 自动检索和筛选 30 篇论文 → 提取方法、数据集、指标和创新点 → 展示可核查的文献对比矩阵 → 生成有真实引文的综述 → 一键生成 12 页组会 PPT。

这样展示出的不是六个独立功能，而是一个真正运行的科研 Agent。

## 6. 怎样与现有产品做出差异化？

我认为最值得投入的是 Evidence-first Research Agent（证据优先的科研 Agent）。

不同于先生成文字、再补参考文献，你的系统可以先建立统一的证据对象，例如一篇论文中的“模型、数据集、样本规模、评价指标、局限性”，每项都有原文页码、表格位置和验证状态。综述与 PPT 只能引用这些可追溯的对象。

这有三个好处：降低编造引用和实验数据的风险；修改一项证据时可以追踪受影响的综述与 PPT；用户能够在不同任务之间反复复用科研成果。

结合你此前在开发的 Agent 架构，Research Agent 可以独立于 Web 前端，把检索、解析、分析、写作、制图作为不同工具暴露给统一运行时。真正需要专门设计的是科研证据模型，而不仅是普通聊天记忆。

最后我想确认一个会直接影响产品架构的定位问题：

你准备做哪一种产品？

综合型科研平台 — 对标 SciSpace，面向各学科用户

科研 Agent 平台 — 强调自主研究、可观察工作流和自动产出

垂直学科平台 — 先做石油、地学或计算机领域

按这个方向深入设计&#x20;