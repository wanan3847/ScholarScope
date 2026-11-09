#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""填写《附件3 作品报名表》，输出到 英迈云/提交材料/。

用法（仓库根目录）:
    .venv/bin/python 英迈云/scripts/fill_form.py

只填文字与勾选项；签名与日期留空，由参赛人本人手写。
模板中的复选框是 Word 内容控件，脚本改为等价的 ☑/☐ 文字（打印与 PDF 效果一致）。
"""
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "英迈云" / "附件 3 作品报名表.docx"
OUT = ROOT / "英迈云" / "提交材料" / "研索ScholarScope-作品报名表.docx"

PROJECT = "研索 ScholarScope——研究问题驱动的智能文献检索与阅读工作台"
COLLEGE = "计算机与人工智能学院"

INTRO = (
    "研索 ScholarScope 是面向研究生与科研工程师的研究问题驱动文献检索、阅读与资料整理工作台。"
    "系统把研究问题中的主题、方法、研究对象与年份约束转成检索计划，并行检索 arXiv、OpenAlex、Crossref、"
    "Semantic Scholar、Europe PMC 与本地索引，合并去重后沿参考文献扩展候选，按研究用途组织推荐，"
    "理由附可核对的标题或摘要原文，检索失败不生成占位论文。课题工作台把阅读中确认的页码片段固化为证据，"
    "贯通研究矩阵、跨论文问答、综述写作、图表与演示稿导出；来源变化时标记相关成果待复核，模型不可用时降级为原文整理。"
    "Web 与 MCP 共用同一条检索链路，支持账号隔离、项目权限与 Zotero 同步，可单机试用或 Docker 部署。"
    "截至 2026 年 11 月 3 日，回归测试 148 项全部通过，其中用户流程用例 24 项。"
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"


def tick(cell, index):
    """勾选单元格里的第 index 个 Word 复选框内容控件（0 起）。

    模板的勾选字形是 Symbol 字体 0xD6，导出 PDF 时会被渲染成字母 Ö；
    这里统一改成 MS Gothic 的 ☑，与模板未勾选的 ☐ 同一字形族。
    """
    sdts = cell._tc.findall(".//{%s}sdt" % W)
    sdt = sdts[index]
    box = sdt.find(".//{%s}checkbox" % W14)
    box.find("{%s}checked" % W14).set("{%s}val" % W14, "1")
    checked = box.find("{%s}checkedState" % W14)
    checked.set("{%s}val" % W14, "2611")
    checked.set("{%s}font" % W14, "MS Gothic")
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        sdt.find(".//{%s}rFonts" % W).set("{%s}%s" % (W, attr), "MS Gothic")
    sdt.find(".//{%s}t" % W).text = "\u2611"


def set_cell(cell, lines, size=12, align=None, bold=False):
    """清空单元格（含内容控件）并写入文字，保留单元格与首个段落的格式。"""
    first = cell.paragraphs[0]
    for p in list(cell.paragraphs[1:]):
        p._p.getparent().remove(p._p)
    for child in list(first._p):
        if child.tag != qn("w:pPr"):
            first._p.remove(child)
    if align is not None:
        first.alignment = align
    for i, line in enumerate(lines):
        p = first if i == 0 else cell.add_paragraph()
        if align is not None:
            p.alignment = align
        run = p.add_run(line)
        run.font.name = "仿宋"
        run.font.size = Pt(size)
        run.bold = bold
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋")


doc = Document(TEMPLATE)
t = doc.tables[0]
C = WD_ALIGN_PARAGRAPH.CENTER
L = WD_ALIGN_PARAGRAPH.LEFT

# 作品名称 / 负责人所在学院
set_cell(t.rows[0].cells[4], [PROJECT], align=C)
set_cell(t.rows[1].cells[4], [COLLEGE], align=C)

# 参赛组别：应用技术赛道 + 创意组（复选框第 1 个勾选）
tick(t.rows[2].cells[6], 0)

# 参赛项目类型：“人工智能+”（复选框第 5 个勾选）
tick(t.rows[3].cells[4], 4)

# 负责人：姓名 / 专业班级 / 学号 / QQ / 手机（学号与 QQ 待补）
set_cell(t.rows[5].cells[3], ["杨亚洲"], align=C)
set_cell(t.rows[5].cells[5], ["Y2615 计算机"], align=C)
set_cell(t.rows[5].cells[6], [""], align=C)
set_cell(t.rows[5].cells[8], [""], align=C)
set_cell(t.rows[5].cells[9], ["18628701126"], align=C)

# 指导教师：韩峰、石林（手机号待补，邮箱见作品简介后的说明）
set_cell(t.rows[12].cells[1], ["韩峰"], align=C)
set_cell(t.rows[12].cells[4], [COLLEGE], align=C)
set_cell(t.rows[12].cells[7], [""], align=C)
set_cell(t.rows[13].cells[1], ["石林"], align=C)
set_cell(t.rows[13].cells[4], [COLLEGE], align=C)
set_cell(t.rows[13].cells[7], [""], align=C)

# 作品简介
set_cell(t.rows[14].cells[1], [INTRO], size=9.5, align=L)

OUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUT)
print(f"written: {OUT}")
