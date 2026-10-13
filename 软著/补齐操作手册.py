#!/usr/bin/env python3
"""补齐《智能学术文献检索与分析软件_操作手册》，并把实际截图插入文档。

原则：只在原文档基础上增删文字与插图，不改动既有段落/表格的样式与格式。
所有新段落都从原文档已有的 Normal / Heading 2 段落克隆而来，字体字号与原文档一致。
"""

from __future__ import annotations

import shutil
import sys
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches
from docx.table import Table
from docx.text.paragraph import Paragraph

BASE = Path(__file__).resolve().parent
DOCX = BASE / "正式资料" / "智能学术文献检索与分析软件_操作手册.docx"
SHOTS = BASE / "截图"
FIG_W = Inches(5.6)

doc = Document(str(DOCX))
body = doc.element.body


# --------------------------------------------------------------------- #
# 基础工具：克隆已有段落来新建段落，保证字体/字号/缩进与原文一致
# --------------------------------------------------------------------- #
def _find_para(text_head: str) -> Paragraph:
    for p in doc.paragraphs:
        if p.text.strip().startswith(text_head):
            return p
    raise SystemExit(f"未找到锚点段落：{text_head}")


def _find_heading(text_head: str) -> Paragraph:
    for p in doc.paragraphs:
        if p.style.name.startswith("Heading") and p.text.strip().startswith(text_head):
            return p
    raise SystemExit(f"未找到标题：{text_head}")


SAMPLE_NORMAL = _find_para("智能学术文献检索与分析软件 V1.0适用于")
SAMPLE_HEADING = _find_heading("二、说明")
SAMPLE_RPR = deepcopy(SAMPLE_NORMAL.runs[0]._element.find(qn("w:rPr")))


def P(text: str) -> Paragraph:
    """按原文档 Normal 段落格式新建一段。"""
    el = deepcopy(SAMPLE_NORMAL._element)
    for r in el.findall(qn("w:r")):
        el.remove(r)
    para = Paragraph(el, SAMPLE_NORMAL._parent)
    run = para.add_run(text)
    run._element.insert(0, deepcopy(SAMPLE_RPR))
    return para


def H(text: str) -> Paragraph:
    """按原文档 Heading 2 格式新建标题。"""
    el = deepcopy(SAMPLE_HEADING._element)
    for r in el.findall(qn("w:r")):
        el.remove(r)
    para = Paragraph(el, SAMPLE_HEADING._parent)
    run = para.add_run(text)
    if SAMPLE_HEADING.runs:
        rpr = SAMPLE_HEADING.runs[0]._element.find(qn("w:rPr"))
        if rpr is not None:
            run._element.insert(0, deepcopy(rpr))
    return para


def IMG(filename: str, caption: str):
    """插图 + 图题（居中），返回两个段落。"""
    path = SHOTS / filename
    if not path.exists():
        raise SystemExit(f"缺图：{path}")
    holder = doc.add_paragraph()
    holder.alignment = WD_ALIGN_PARAGRAPH.CENTER
    holder.add_run().add_picture(str(path), width=FIG_W)
    pic_el = holder._element
    body.remove(pic_el)

    cap = P(caption)
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return pic_el, cap._element


def insert_after(anchor: Paragraph, elements) -> None:
    el = anchor._element
    for e in elements:
        el.addnext(e)
        el = e


def insert_before(anchor: Paragraph, elements) -> None:
    el = anchor._element
    for e in elements:
        el.addprevious(e)


def insert_figs(anchor: Paragraph, figs) -> None:
    """在 anchor 之后按顺序插入 图片+图题（锚点随插入往后移，保证顺序）。"""
    el = anchor._element
    for name, caption in figs:
        pic, cap = IMG(name, caption)
        el.addnext(pic)
        pic.addnext(cap)
        el = cap


def set_text(para: Paragraph, text: str) -> None:
    """整段改字：保留第一段的字符格式，其余 run 删除。"""
    runs = para.runs
    if not runs:
        raise SystemExit("段落没有 run，无法改字")
    rpr = deepcopy(runs[0]._element.find(qn("w:rPr")))
    for r in runs[1:]:
        r._element.getparent().remove(r._element)
    first = runs[0]
    for t in first._element.findall(qn("w:t")):
        first._element.remove(t)
    run = para.add_run(text)
    run._element.insert(0, rpr)
    first._element.getparent().remove(first._element)


# --------------------------------------------------------------------- #
# 1) 标题重新编号
# --------------------------------------------------------------------- #
RENUMBER = {
    "六、命令行与编程数据通道：检索、评测与收藏": "七、命令行与编程数据通道：检索、评测与收藏",
    "七、典型使用流程": "九、典型使用流程",
    "八、常见问题解答": "十、常见问题解答",
    "九、术语表": "十一、术语表",
}
for old, new in RENUMBER.items():
    h = _find_heading(old)
    set_text(h, new)
    print(f"标题改号：{old} → {new}")

# --------------------------------------------------------------------- #
# 2) 四、系统要求：补一行浏览器要求（沿用原表格行格式）
# --------------------------------------------------------------------- #
table = doc.tables[1]
row = deepcopy(table.rows[-1]._element)
table._tbl.append(row)
new_row = table.rows[-1]
for cell, val in zip(new_row.cells, ["浏览器", "支持现代浏览器（Chrome / Edge / Safari / Firefox）",
                                     "建议使用 Chrome 或 Edge 最新版本"]):
    for p in cell.paragraphs:
        for r in p.runs:
            r._element.getparent().remove(r._element)
    cell.paragraphs[0].add_run(val)
print("系统要求表：新增“浏览器”行")

# --------------------------------------------------------------------- #
# 3) 二、说明 末尾补首页截图
# --------------------------------------------------------------------- #
anchor = _find_para("本手册用于说明软件的用途、功能特点、运行要求和页面操作流程")
insert_after(anchor, IMG("01_首页.png", "图 2-1 软件首页"))

# --------------------------------------------------------------------- #
# 4) 三、功能特点：补齐六项主要功能与账号功能
# --------------------------------------------------------------------- #
anchor = _find_para("在命令行与编程数据通道：检索、评测与收藏页面中")
insert_after(anchor, [P(t)._element for t in [
    "复杂学术查询理解与查询规划：软件把用户输入的一段描述性学术问题解析为关键词检索词与语义短语，形成可执行的查询规划，并在结果页给出意图、改写查询与关键词等规划信息。",
    "多渠道文献检索与语义预排：软件并发访问 arXiv、OpenAlex、CrossRef、Semantic Scholar 等真实学术数据源，并配合本地语义语料检索，随后按语义相关性对候选论文做预排序。",
    "迭代式引文双向扩展：软件对命中论文网络同时查看其参考文献与被引用情况（RefChain 双向扩展），逐层扩大相关文献范围，接近多轮迭代检索的效果。",
    "结构化三件套结果输出：软件把一次查询与其检索结果整理为 JSON 明细、Markdown 对比表与自包含 HTML 关系图，可离线打开查看。",
    "检索反馈闭环与个性化收集：软件记录用户对结果的已阅、收藏、引用、跳过等反馈事件，支持收藏夹、已阅标记、文件夹归类与批量导入导出，沉淀为个人文献库。",
    "多模型评测与离线复现：软件内置学术基准评测集与可离线运行的评测流水线，支持多模型对照，输出检索指标与失败样例；无外部服务时仍可复现基础结果。",
    "账号与权限管理：软件支持注册、登录、修改密码与会话保持，收藏夹、已阅与个人库按账号隔离；管理员账号可维护内置帮助文档与数据源配置。",
]])

# --------------------------------------------------------------------- #
# 5) 五、Web 端检索与结果页：补操作说明、修正描述、插入截图
# --------------------------------------------------------------------- #
anchor = _find_para("用户在Web 端检索与结果页")
insert_after(anchor, [P(t)._element for t in [
    "页面顶部工具栏依次提供我的收藏夹、搜索历史、配置大模型、使用文档与设置入口；页面右上角显示当前登录账号，未登录时显示登录入口。",
    "结果区左侧为结果列表，每张论文卡片显示标题、发表信息、来源数据通道、相关度与摘要速览，并提供已阅、收藏、引用（导出 BibTeX）、速读、相似文献与跳过按钮；右侧为运行统计与文献星图。",
    "文献星图把命中的论文按相似度连成图，节点大小与颜色对应当前相关度高低，便于观察主题簇与关键文献。",
    "配置区支持登记大模型与数据源：可查看预设模型、已注册模型与当前使用模型，也可自定义名称、模型、接口地址与密钥，并先测试连通性再保存。",
]])

set_text(_find_para("使用该功能时，用户先在输入区输入一段学术问题"), (
    "使用该功能时，用户先在输入区输入一段学术问题，随后如需真实检索或调用大智能服务，"
    "先在配置区登记并选择可用的数据源和智能服务供应商，接着点击发起检索，等待系统完成查询规划、多路召回与引文扩展，"
    "之后在结果区查看命中结果：论文卡片按相关性排序，卡片上可展开摘要速览并查看相似文献，右侧文献星图展示论文之间的关联，"
    "再打开单篇论文可查看详情并可沿参考文献或被引继续扩展，最后对满意的记录收藏并对结果给出反馈；查看反馈汇总了解使用效果。"
))
set_text(_find_para("页面会按照使用真实数据源需网络可用"), (
    "页面会按照使用真实数据源需网络可用；离线/未配密钥时软件可进入离线复现模式，部分数据通道不同步和智能服务供应商与密钥按页面登记后保存生效，"
    "登记前仅使用离线演示能力等规则限制或提示用户。处理结束后，用户可以看到页面显示检索状态与查询规划；"
    "结果以论文卡片列表、运行统计与文献星图呈现；配置/登记成功与失败均有明确提示。"
))

placeholder = _find_para("【截图预留：截图预留：Web 检索主界面与结果关系图。】")
insert_figs(placeholder, [
    ("02_检索主界面.png", "图 5-1 检索主界面"),
    ("08_检索进行中.png", "图 5-2 检索进行中（多通道并行检索与判分）"),
    ("10_查询规划与意图理解.png", "图 5-3 查询规划与意图理解"),
    ("09_检索结果列表.png", "图 5-4 检索结果列表"),
    ("12_单篇论文卡片与摘要速览.png", "图 5-5 单篇论文卡片与摘要速览"),
    ("11_文献星图关系图.png", "图 5-6 文献星图（论文关系图）"),
    ("15_运行统计面板.png", "图 5-7 运行统计面板"),
])
placeholder._element.getparent().remove(placeholder._element)

# --------------------------------------------------------------------- #
# 6) 新增 六、账号与个人文献库
# --------------------------------------------------------------------- #
anchor = _find_heading("七、命令行与编程数据通道")
sec6 = [H("六、账号与个人文献库")._element] + [
    P(t)._element for t in [
        "软件支持注册与登录：点击右上角登录入口，可在登录与注册页签之间切换，注册成功后当前账号显示在右上角；登录状态下可以修改密码或退出登录。",
        "我的收藏夹按账号隔离保存用户收藏的论文，支持按文件夹查看，并可新增、重命名、删除文件夹以及设置默认收藏文件夹。",
        "导入支持 BibTeX (.bib)、RIS、CSV、Zotero JSON 与 EndNote XML：在文献管理软件中导出后，把文件拖入导入框或点击选择文件即可，导入的论文进入当前账号的收藏夹。",
        "导出支持 BibTeX（Zotero / LaTeX）、RIS（EndNote / NoteExpress）、CSV（Excel 表格）与 JSON（Mendeley 兼容），可限定导出全部收藏或某个文件夹。",
        "已阅标记与搜索历史：点击论文卡片上的已阅按钮即可标记已读；搜索历史记录每一次查询与命中数量，并支持一键恢复上一次的检索结果。",
    ]
]
insert_before(anchor, sec6 + [
    el for name, cap in [
        ("07_账号登录注册.png", "图 6-1 账号登录与注册"),
        ("13_我的收藏夹.png", "图 6-2 我的收藏夹"),
        ("16_收藏夹文件夹管理.png", "图 6-3 收藏夹文件夹管理"),
        ("17_收藏导入导出.png", "图 6-4 收藏导入与导出"),
        ("14_搜索历史.png", "图 6-5 搜索历史"),
    ]
    for el in IMG(name, cap)
])

# --------------------------------------------------------------------- #
# 7) 七、命令行：补 MCP 说明，替换截图预留
# --------------------------------------------------------------------- #
anchor = _find_para("如果不满足此模式下未配置智能服务")
insert_after(anchor, [P(
    "软件同时提供 MCP（Model Context Protocol）服务，把上述能力暴露为标准工具，支持 MCP 的客户端可直接调用："
    "search_papers（多通道检索）、get_paper（论文详情）、get_references（参考文献）、get_citations（被引文献）、"
    "save_favorite / list_favorites（收藏与个人库）、run_eval（基准评测）。"
)._element])

placeholder = _find_para("【截图预留：截图预留：命令行调用检索/评测的输出。】")
insert_figs(placeholder, [
    ("18_命令行检索输出.png", "图 7-1 命令行调用检索的输出"),
    ("19_命令行评测输出.png", "图 7-2 命令行调用评测的输出"),
])
placeholder._element.getparent().remove(placeholder._element)

# --------------------------------------------------------------------- #
# 8) 新增 八、内置帮助文档与数据源配置
# --------------------------------------------------------------------- #
anchor = _find_heading("九、典型使用流程")
sec8 = [H("八、内置帮助文档与数据源配置")._element] + [
    P(t)._element for t in [
        "内置帮助文档：点击工具栏的文档入口可查看使用说明、常见问题与数据源配置说明；管理员登录后可直接在弹窗中编辑并保存，保存后的内容对所有用户生效。",
        "大模型配置：在配置大模型弹窗中可查看预设模型、已注册模型与当前使用模型，也可以自定义模型名称、模型标识、接口地址与密钥，并先测试连通性再保存。",
        "数据源与检索后端配置：在设置抽屉中可登记 OpenAlex 与 Semantic Scholar 的密钥与邮箱，密钥保存后脱敏显示（仅管理员可修改），并可查看各检索后端与创新模块的开关状态。",
    ]
]
insert_before(anchor, sec8 + [
    el for name, cap in [
        ("06_内置帮助文档.png", "图 8-1 内置帮助文档"),
        ("03_大模型配置.png", "图 8-2 大模型配置"),
        ("04_数据源与检索后端设置.png", "图 8-3 数据源与检索后端设置"),
        ("05_创新模块面板.png", "图 8-4 创新模块面板"),
    ]
    for el in IMG(name, cap)
])

# --------------------------------------------------------------------- #
# 9) 十、常见问题解答：补两条
# --------------------------------------------------------------------- #
anchor = _find_para("解决方法：软件统一生成 JSON、Markdown 对比表与关系图")
insert_after(anchor, [P(t)._element for t in [
    "问题：怎么把检索结果导入到 Zotero 等文献管理软件？",
    "解决方法：在结果卡片上点“引用”可复制该论文的 BibTeX；也可以先把论文收藏，再到收藏夹的“导入 / 导出”页按 BibTeX、RIS、CSV 或 JSON 导出。",
    "问题：为什么有的结果没有相关度数值或摘要？",
    "解决方法：外部数据源未返回摘要时卡片会显示“暂无摘要”；相关度由本地语义预排与判分结果综合给出，未配置可用的大模型时会退化为离线判分，数值偏低属正常现象。",
]])

# --------------------------------------------------------------------- #
# 保存（先备份）
# --------------------------------------------------------------------- #
backup = DOCX.with_name(DOCX.stem + "_备份.docx")
if not backup.exists():
    shutil.copy2(DOCX, backup)
doc.save(str(DOCX))
print("已保存：", DOCX)
print("备份：", backup)
