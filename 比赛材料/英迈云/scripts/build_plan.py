#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《研索 ScholarScope 项目计划书（人工智能应用）》docx。

用法（仓库根目录）:
    .venv/bin/python 英迈云/scripts/build_plan.py

内容全部来自仓库实际实现与当前实测记录，不虚构功能或数据。
生成后由 Word 导出 PDF（见 英迈云/scripts/to_pdf.sh）。
"""
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "英迈云" / "提交材料"
OUT = OUT_DIR / "研索ScholarScope项目计划书（人工智能应用）.docx"

PROJECT = "研索 ScholarScope——研究问题驱动的智能文献检索与阅读工作台"
OWNER = "杨亚洲"
COLLEGE = "计算机与人工智能学院"
TODAY = "2026 年 11 月 3 日"

FIG_ARCH = ROOT / "英迈云/assets/architecture.png"
FIG_FLOW = ROOT / "英迈云/assets/workflow.png"
FIG_UI = ROOT / "英迈云/assets/ui-search.png"

BODY_FONT = "宋体"
HEAD_FONT = "黑体"
GRAY = RGBColor(0x59, 0x59, 0x59)


# ---------------------------------------------------------------- helpers
def font(run, name=BODY_FONT, size=10.5, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    return run


def para(text="", size=10.5, bold=False, align=None, first_indent=True,
         space_after=6, line=1.5, name=BODY_FONT, color=None):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.line_spacing = line
    if first_indent and text:
        pf.first_line_indent = Pt(size * 2)
    if align is not None:
        p.alignment = align
    if text:
        font(p.add_run(text), name, size, bold, color)
    return p


def h1(text, new_page=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(16)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.page_break_before = new_page
    p.paragraph_format.keep_with_next = True
    font(p.add_run(text), HEAD_FONT, 15, True)
    return p


def h2(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    font(p.add_run(text), HEAD_FONT, 12, True)
    return p


def bullets(items, size=10.5, indent=Pt(21)):
    for it in items:
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = indent
        pf.space_after = Pt(3)
        pf.line_spacing = 1.5
        pf.first_line_indent = Pt(-10.5)
        font(p.add_run("· "), BODY_FONT, size)
        font(p.add_run(it), BODY_FONT, size)


def caption(text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(10)
    font(p.add_run(text), BODY_FONT, 9, color=GRAY)


def figure(path, width_cm, cap):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(path), width=Cm(width_cm))
    caption(cap)


def table(headers, rows, widths=None, size=9.5, cap=None):
    if cap:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        font(p.add_run(cap), BODY_FONT, 9, color=GRAY)
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    # 固定布局，避免 Word 按内容重算列宽
    tblPr = t._tbl.tblPr
    layout = tblPr.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"})
    tblPr.append(layout)
    head = t.rows[0]
    head._tr.get_or_add_trPr().append(head._tr.makeelement(qn("w:tblHeader"), {}))
    for i, h in enumerate(headers):
        cell = head.cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True  # 表头不与其后的行分离
        font(p.add_run(h), HEAD_FONT, size, True)
    for row in rows:
        r = t.add_row()
        r._tr.get_or_add_trPr().append(r._tr.makeelement(qn("w:cantSplit"), {}))
        cells = r.cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.25
            font(p.add_run(val), BODY_FONT, size)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


# ---------------------------------------------------------------- document
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.top_margin, sec.bottom_margin = Cm(2.4), Cm(2.2)
sec.left_margin, sec.right_margin = Cm(2.6), Cm(2.6)

style = doc.styles["Normal"]
style.font.name = BODY_FONT
style.font.size = Pt(10.5)
style.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)

# ---- 封面
for _ in range(4):
    doc.add_paragraph()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
font(p.add_run("常州大学第六届“英迈云杯”大学生计算机应用大赛"), HEAD_FONT, 15, True)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(30)
font(p.add_run("应用技术赛道 · 创意组 · “人工智能+”"), BODY_FONT, 12)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
font(p.add_run("项 目 计 划 书"), HEAD_FONT, 34, True)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(24)
font(p.add_run("研索 ScholarScope"), HEAD_FONT, 24, True)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
font(p.add_run("研究问题驱动的智能文献检索与阅读工作台"), HEAD_FONT, 14)

for _ in range(5):
    doc.add_paragraph()
info = [
    ("作品名称", PROJECT),
    ("参赛组别", "应用技术赛道  创意组"),
    ("参赛项目类型", "“人工智能+”"),
    ("项目负责人", f"{OWNER}（{COLLEGE}）"),
    ("指导教师", "韩峰、石林"),
    ("所在学校", "常州大学"),
    ("编制日期", TODAY),
]
for k, v in info:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)
    font(p.add_run(f"{k}："), BODY_FONT, 11, True)
    font(p.add_run(v), BODY_FONT, 11)

doc.paragraphs[-1].add_run().add_break(WD_BREAK.PAGE)

# ---- 一、项目概述
h1("一、项目概述")

h2("1.1 项目背景")
para(
    "科研工作的第一步不是写作，而是把问题变成可检索、可判断、可引用的材料。研究生与科研工程师在这一步上长期"
    "被三处断层消耗：检索结果分散在 arXiv、OpenAlex、Crossref、Semantic Scholar 等互相独立的接口，同一课题要"
    "在多个页面之间反复搬运；检索工具按关键词或引用量排序，不判断一篇论文是否回答了“这个主题、这个方法的、这个"
    "研究对象”的问题；读到的结论停留在 PDF 批注和临时表格里，写综述或做组会汇报时无法定位当时的原文依据。"
)
para(
    "大模型的出现让“读得快”变得容易，却让“靠得住”变得更难：生成式回答容易给出无法在原文中核对的理由，"
    "更危险的是在检索失败时编造不存在的论文。市场主流工具往往在这两点上让步——要么是纯搜索引擎（快但不成体系），"
    "要么是纯写作助手（流畅但证据链断开）。研索的出发点是：把检索、阅读与资料整理做成一条可追溯的链路，"
    "让每一句推荐、每一条结论都能回到具体论文的标题、摘要或页码片段。"
)

h2("1.2 项目目的")
para("研索面向高校课题组、图书馆学科服务与科研机构，提供一条“提出问题—检索判断—证据阅读—整理产出”的完整工作流，具体目标为：")
bullets([
    "把研究问题（主题、方法、研究对象、明确年份约束）转成检索计划，而不是把查询词原样抛给接口；",
    "多源并行召回后按研究用途组织推荐，推荐理由必须落在已检索到的标题或摘要文本上；",
    "把阅读中确认的原文片段固化为带页码与来源哈希的证据，供矩阵、问答、综述和演示复用；",
    "在模型或数据源不可用时降级而不是编造：保留人工流程，保留原文，明确标注证据不足；",
    "支持课题组私有化部署，账号、收藏、已阅与项目资料按角色隔离。",
])

h2("1.3 创新点")
bullets([
    "按研究用途组织推荐，而非按引用量或期刊声望排序。系统先核验标题与摘要是否满足主题、方法、对象与年份约束，"
    "再说明该文献在本次研究中的用途；无可用证据时返回空结果，不生成占位论文。",
    "证据先于结论的工程化约束。证据保存来源哈希、页码位置与片段原文，提交不在原文中的片段会被拒绝；"
    "来源或版本变化后，依赖该证据的矩阵、综述与演示被标记为待复核。",
    "Web 界面与 MCP 工具共用同一条检索链路（Orchestrator / SPAR2），避免“网页能搜、接口不能搜”的两套逻辑。",
    "每个阶段有独立时间预算，单源故障不阻塞整次检索；全源失败时明确提示，而不是返回空壳结果或伪造条目。",
    "原生文件交付：DOCX、PPTX、Excel、BibTeX/RIS 等导出为可继续编辑的真实文件，"
    "演示稿逐页保留出处与备注，成果能进入研究者既有的工作习惯。",
    "面向科研场景的数据治理：账号隔离、项目角色、Zotero 凭据加密保存、备份可校验，适合课题组私有化部署。",
])

h2("1.4 当前成果阶段")
para(
    "已形成可运行的 Beta 版系统：FastAPI 后端 + React 科研工作台 + MCP 工具接口，覆盖检索、阅读、证据、"
    "矩阵、筛选、问答、综述、图表、演示与文献管理全流程，具备 Docker 容器部署、数据库备份恢复与自动化验收方案。"
    "截至 2026 年 11 月 3 日，仓库回归测试 148 项全部通过（耗时 43.62 秒），其中用户流程用例 24 项。"
)

# ---- 二、技术方案
h1("二、技术方案")

h2("2.1 总体架构")
para(
    "系统分为四层：接入层（Web 工作台与 MCP 工具）、能力层（共用检索引擎与课题证据引擎）、服务层（学术来源、"
    "可配置模型服务）、持久化层（本轮 SQLite/本地文件，可选 PostgreSQL + pgvector 与私有 S3）。"
    "接入层只负责交互与权限，能力层沉淀可复用的检索与证据逻辑，外部依赖集中在服务层并可替换。"
)
figure(FIG_ARCH, 15.5, "图 1  总体架构：统一入口、共用检索链路、课题证据引擎与可选部署层")

h2("2.2 功能概述")
table(
    ["模块", "主要功能", "实现状态"],
    [
        ["检索工作台", "研究问题解析、多源并行检索、合并去重、按用途组织推荐并附原文理由", "已实现"],
        ["课题项目", "项目概览、成员与角色权限、资料集合、任务与产物管理", "已实现"],
        ["阅读与证据", "PDF 分页阅读、页码片段取证、OCR 扫描页识别、证据来源哈希校验", "已实现"],
        ["研究矩阵", "跨论文结构化字段提取、列级重跑、人工修订与确认、Excel 导出", "已实现"],
        ["项目问答", "跨论文原文检索增强问答、语义与关键词联合检索、Markdown 导出", "已实现"],
        ["综述写作", "按证据组织章节、在线编辑、版本恢复、Word/PDF/Markdown 导出", "已实现"],
        ["图表与演示", "科研图表核对数值与单位、演示稿生成、原生 PPTX 导出", "已实现"],
        ["文献管理", "收藏/已阅/文件夹、BibTeX/RIS/JSON/CSV 导入导出、Zotero 同步", "已实现（写入需账号授权）"],
        ["研究任务", "工具计划、受限子进程执行、按缺口补检索、中断恢复", "已实现"],
        ["模型与数据源设置", "多端点注册、优先级路由、连通性测试、密钥加密保存", "已实现"],
    ],
    widths=[3.0, 9.6, 4.0],
    cap="表 1  功能模块与实现状态",
)

h2("2.3 关键技术")
para("（1）SPAR2 检索链路。", bold=False)
para(
    "检索不是一次接口调用，而是四个阶段的流水线：①查询规划，把研究问题转成标准学术术语与聚焦短语，保留方法、"
    "任务、研究对象与明确年份约束；②多源召回，并行请求 arXiv、OpenAlex、Crossref、Semantic Scholar、Europe PMC "
    "与本地文献索引，配置授权密钥后启用 Scopus，按 DOI 与 arXiv 别名合并、按标题去重；③引文扩展，由 Agent 沿"
    "已检索文献的参考文献继续扩展候选；④用途选择，依据标题与摘要按研究用途挑选，推荐理由取原文片段。"
    "各阶段设置时间预算，任一源超时或报错只影响该源。",
    first_indent=True,
)
para("（2）证据与来源约束。")
para(
    "证据记录论文标识、页码、片段原文、来源哈希与写入时间；后端校验提交片段确实出现在原文中，否则拒绝写入。"
    "矩阵单元格、问答回答与综述段落都指向证据 ID，因此在预览、导出与备注中始终可以回溯出处。"
    "来源文件或版本变化时，系统把依赖该证据的产物标记为待复核，人工确认后才重新生成。",
)
para("（3）语义与关键词联合检索，无模型时自动降级。")
para(
    "项目问答默认使用本地多语言句向量模型（paraphrase-multilingual-MiniLM-L12-v2）做语义与关键词联合检索，"
    "模型缓存于本机，不在请求中自动下载；模型缺失时保留关键词检索，界面标明当前生成模式与章节覆盖情况。"
    "矩阵提取要求每条概括附实际原文引用并通过第二次语义核对，不符合的单元格回退到原文整理。",
)
para("（4）模型路由与失败降级。")
para(
    "系统支持注册 DeepSeek、Ollama 及 OpenAI 兼容端点，按优先级为检索、问答、综述与演示选择模型；"
    "云端密钥只填表单，加密后落库，接口不回显。模型超时、返回无效引用或核对失败时降级为原文整理，"
    "并把实际生成模式标给研究者，而不是伪造“AI 已完成”的结果。",
)
para("（5）检索失败不生成占位内容。")
para(
    "检索阶段异常统一返回脱敏的服务不可用提示，不把提供商原始异常写入响应或日志；该路径通过故障注入复现、修复并"
    "纳入回归。这一条是产品态度：宁可承认没有结果，也不给出无法核对的论文。",
)
para("（6）原生文件导出与工程化交付。")
para(
    "演示稿通过服务端 PptxGenJS 导出为逐页可编辑的 PPTX，图与表以原生对象嵌入；Word/PDF/Markdown、CSV/Excel、"
    "BibTeX/RIS 导出同理。私有 ZIP 来源清单随任务产物下载，便于组会汇报与存档。",
)

h2("2.4 其他技术与选型")
table(
    ["层次", "选型", "理由"],
    [
        ["后端", "Python 3 + FastAPI + SQLAlchemy", "异步接口与检索并发契合，团队可维护"],
        ["前端", "React + Vite 构建，关键资源本地提供", "不依赖外部 CDN，校园网内可离线使用"],
        ["存储", "SQLite/本地文件（默认）；PostgreSQL 17 + pgvector 与私有 S3（可选）", "单人试用到课题组共享平滑过渡，向量检索与对象存储可扩展"],
        ["文档", "PDF.js 阅读、Tiptap 编辑、PptxGenJS 导出、Poppler/Tesseract OCR", "沿用成熟组件，避免自研渲染"],
        ["部署", "Docker Compose，非 root、只读根文件系统", "降低部署门槛并收敛权限面"],
    ],
    widths=[2.4, 7.4, 6.8],
    cap="表 2  技术选型",
)
para(
    "第三方组件均为开源许可，版本与许可清单见仓库 docs/implementation/dependency-licenses.json；"
    "学术元数据来自各开放接口，本项目未训练基础大模型，模型能力由云端供应方或本机 Ollama 提供。",
)

h2("2.5 实机界面")
para(
    "下图为本机运行时的检索工作台界面：左侧输入研究问题与年份约束，中部按研究用途列出候选文献与原文理由，"
    "右侧可一键转入课题项目继续取证。",
)
figure(FIG_UI, 15.5, "图 2  检索工作台实机界面（本机运行，2026 年 10 月运行截图）")

# ---- 三、项目计划
h1("三、项目计划（可行性分析）")

h2("3.1 技术可行性")
para(
    "系统所依赖的能力均为成熟可控技术：检索侧使用公开学术接口，无需自建爬虫；语义检索使用开源句向量模型；"
    "文档与演示导出使用既有开源库。项目已按模块划分测试边界，当前 28 个测试模块、148 项回归用例覆盖账号安全、"
    "检索召回、工作区存储、写作、演示、图表、备份恢复与用户流程，本轮实际结果为 148 项通过、0 项失败。"
)
figure(FIG_FLOW, 15.0, "图 3  研究工作流与成果追溯方式：来源变化触发过期提示与复核")

h2("3.2 运行适配性、稳定性与容错")
para("对应评分基础分“系统运行适配性”（20 分），项目的具体做法是：")
bullets([
    "环境兼容：单机模式下只需 Python 与 Node 运行时，浏览器访问即可使用；容器模式下 Docker Compose 一条命令启动，"
    "镜像以非 root 用户运行、根文件系统只读，适配常见 Linux/Windows/macOS 开发机与校园服务器。",
    "依赖可控：前端关键资源本地构建，不依赖外部 CDN；语义模型默认读取本地缓存，不在请求中下载，弱网环境仍可用关键词检索。",
    "降级策略：每个检索阶段与模型调用均有时间预算，单源失败不阻塞整次检索；模型不可用时保留人工流程与原文整理。",
    "数据安全：账号接口按会话识别身份，不接受客户端传入用户名；收藏、已阅、文件夹与导入按账号隔离；"
    "文献下载限制 25 MB、校验公开 DNS 地址与每次跳转、固定连接地址并保留 TLS 证书校验。",
    "可恢复：数据库与文件备份为一个权限 0600 的 ZIP，恢复要求空库并校验文件哈希，旧资料不会被覆盖；"
    "长任务支持取消、失败重试与中断恢复，已完成步骤与产物保留。",
])
table(
    ["验证项", "结果", "范围与依据"],
    [
        ["自动化回归", "148 项通过 / 0 失败", "2026-11-03 实测，耗时 43.62 秒；覆盖账号、权限、检索、证据、写作与导出"],
        ["用户流程用例", "24 项通过", "tests/test_user_acceptance.py，含多场景与参数化用例"],
        ["真实文件往返", "通过", "PDF 解析与 OCR、DOCX/PPTX/Excel 生成、BibTeX/RIS/JSON/CSV 导入导出"],
        ["异常与越权", "通过", "拒绝伪造证据与越权访问；检索故障返回脱敏提示，不泄露内部错误"],
        ["容器与存储", "通过", "PostgreSQL 17 + pgvector 与 S3 实测，含真实 PDF、跨语言向量检索、备份恢复"],
    ],
    widths=[3.4, 4.2, 9.0],
    cap="表 3  工程验证记录（如实记录，含未完成项见 3.6）",
)

h2("3.3 进度计划")
table(
    ["阶段", "时间", "主要工作", "交付"],
    [
        ["已完成", "2026.08—2026.10", "检索链路、课题工作台、证据与写作、图表与演示、容器部署", "Beta 版系统、文档与回归用例"],
        ["收口", "2026.11", "浏览器全流程复跑、真实检索与模型质量评测、提交材料整理", "计划书、展示 PPT、演示视频"],
        ["试点", "2026.12—2027.03", "2—3 个课题组真实任务试用，记录耗时与错误", "试用报告与需求修订"],
        ["完善", "2027.04 起", "依据试用结果补齐权限、备份与部署验收，推进软著登记", "可交付版本与许可材料"],
    ],
    widths=[2.2, 3.6, 6.6, 4.2],
    cap="表 4  阶段计划",
)

h2("3.4 风险与应对")
table(
    ["风险", "影响", "应对"],
    [
        ["学术接口限流或变更", "检索结果缺失", "多源并行 + 阶段预算 + 单源降级；接口异常不返回伪造条目"],
        ["大模型生成不可核对内容", "结论不可信", "证据必须落在原文片段并通过二次核对，否则回退原文整理并标注"],
        ["真实检索覆盖率不足", "推荐不完整", "按缺口补检索（共享 210 秒预算、最多八轮），如实记录新增与拒绝数量"],
        ["私有化部署门槛", "推广受限", "默认单机即可试用，课题组可切容器模式；提供部署与备份文档"],
        ["数据与隐私", "合规风险", "账号与项目隔离、密钥加密、下载域名校验、日志脱敏"],
    ],
    widths=[4.0, 3.4, 9.2],
    cap="表 5  风险与应对",
)

h2("3.5 经济与推广可行性")
para(
    "成本结构对使用者友好：软件本体可本地部署，无强制订阅；主要边际成本来自模型调用。"
    "课题组可选择免费的本机模型（如 Ollama 加载的 4B 级模型）完成初筛，再在关键环节调用云端模型，"
    "既控制费用又保留质量。推广路径是先校内（课题组、图书馆学科服务、研究生开题与综述写作），"
    "再向同类高校与科研机构复制，交付形态为私有化部署 + 使用培训，避免与商业数据库正面竞价。",
)

# ---- 四、产业价值
h1("四、产业价值与应用前景")
h2("4.1 行业需求")
para(
    "学术信息服务长期由商业数据库与文献管理工具分割：前者解决“有没有”，后者解决“存不存”，中间的“读并形成判断”"
    "环节缺少可追溯的工具支撑。随着人工智能与科研工作流深度结合，研究者对“可核对的辅助”需求上升——"
    "愿意用 AI 提速，但不接受无法回溯的结论。研索切在这一环节。",
)
h2("4.2 目标市场与定位")
bullets([
    "首要市场：高校课题组与研究生个人，用于开题调研、方法比较、文献跟踪与综述写作；",
    "第二市场：高校图书馆与科研管理部门的学科服务、科研诚信与成果归档场景；",
    "定位：可私有化部署的“证据可核对”研究工作台，与商业数据库互补而非替代。",
])
h2("4.3 社会价值")
para(
    "科研诚信是这类产品最直接的社会价值：系统宁可提示“证据不足”，也不生成无法核对的推荐；"
    "引用与结论始终带出处，评审与导师可复核。数据留在本地或本单位服务器，适合对数据出境敏感的场景。"
    "同时，本机模型路径让经费有限的课题组也能使用，缩小工具层面的资源差距。",
)

# ---- 五、团队
h1("五、团队与协作")
table(
    ["角色", "成员", "分工"],
    [
        ["项目负责人", f"{OWNER}（{COLLEGE}，计算机科学与技术）", "需求定义、检索链路与证据引擎设计、后端实现、测试与文档"],
        ["指导教师", "韩峰（常州大学，讲师）", "研究方向与工程方案指导"],
        ["指导教师", "石林（常州大学，教授）", "学术规范与成果转化指导"],
    ],
    widths=[2.6, 6.0, 8.0],
    cap="表 6  团队分工",
)
para(
    "项目自 2026 年 8 月启动，累计形成完整可运行系统、设计文档、部署与用户验收文档、依赖许可清单，"
    "以及 16 页项目介绍演示材料；软件著作权登记申请材料已备齐（著作权人杨亚洲），尚在申请中。"
)

# ---- 六、如实说明
h1("六、如实说明与待验证事项")
bullets([
    "148 项回归通过是工程验证结果，不等于完整产品验收；正式验收报告中的浏览器用例需要在提交环境复跑。",
    "真实检索覆盖率仍在改进：以测井领域真实任务为例，首轮仅得到 2 篇符合条件文献，补检索后保存 10 个真实候选，"
    "仍未达到 30 篇的目标。系统如实记录这一差距，不通过放宽约束凑数。",
    "云端模型质量、私人 Zotero 库联调与最新容器/存储组合仍需在可联网环境中逐项验证；接口契约通过不等于实际账号同步成功。",
    "当前未开展独立的效果评测与研究者对照试用，工具价值以任务完成度与可复核性呈现，不宣称优于同类商业产品。",
])

# ---- 附录
h1("附录 A  第三方来源说明", new_page=True)
para(
    "学术元数据来自 arXiv、OpenAlex、Crossref、Semantic Scholar、Europe PMC 等公开接口（配置授权密钥后启用 Scopus）；"
    "基础模型由云端供应方或本机 Ollama 所加载模型提供，本项目未训练基础大模型；"
    "使用 React、FastAPI、PDF.js、SQLAlchemy、Tiptap、PptxGenJS 等开源组件，按相应许可条款使用。",
)


h1("附录 B  佐证材料清单")
table(
    ["序号", "材料", "证明内容", "位置"],
    [
        ["1", "系统回归与用户流程用例", "148 项通过、24 项用户流程（2026-11-03）", "src/tests/"],
        ["2", "用户验收方案与记录", "分层验收方式、已完成与受阻项", "docs/testing/user-acceptance.md"],
        ["3", "架构与部署文档", "技术方案、容器部署、备份恢复", "docs/implementation/"],
        ["4", "依赖许可清单", "第三方组件版本与许可", "docs/implementation/dependency-licenses.json"],
        ["5", "软著申请材料", "原创性与权属（申请中）", "软著/"],
        ["6", "实机截图与操作手册", "功能可运行证据", "软著/截图/"],
    ],
    widths=[1.4, 4.6, 6.4, 5.0],
    cap=None,
)

OUT_DIR.mkdir(parents=True, exist_ok=True)
doc.save(OUT)
print(f"written: {OUT}")
