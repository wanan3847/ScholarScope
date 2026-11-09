#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 pandoc 生成的计划书 DOCX 整理为可直接提交的 Word 版。

- 副标题换行（pandoc 把 YAML 中的换行合并成空格）
- 表格加全框线、表头行重复、表头浅底
- 页边距与页码

用法（仓库根目录）：python3 scripts/polish_cczu_plan_docx.py
"""
import shutil
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "比赛材料" / "常州大学智能体大赛" / "源文件" / "项目计划书.docx"
OUT = ROOT / "比赛材料" / "常州大学智能体大赛" / "提交材料" / "研索ScholarScope项目计划书（智能体创新大赛）.docx"
SUBTITLE_BREAK = "常州大学首届智能体创新大赛"


def split_subtitle(doc):
    """把副标题在赛事名之前断行，避免标题块挤成一行。"""
    for p in doc.paragraphs:
        if p.style.name != "Subtitle" or SUBTITLE_BREAK not in p.text:
            continue
        for run in p.runs:
            if SUBTITLE_BREAK in run.text:
                head, tail = run.text.split(SUBTITLE_BREAK, 1)
                run.text = head.rstrip()
                run.add_break()
                run.add_text(SUBTITLE_BREAK + tail)
                return


def add_borders(table):
    """全框线 + 表头重复 + 表头浅底。"""
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:color"), "808080")
        borders.append(el)
    tbl_pr.append(borders)

    header = table.rows[0]
    tr_pr = header._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:tblHeader"))
    for cell in header.cells:
        cell._tc.get_or_add_tcPr().append(_shading("F2F2F2"))


def _shading(fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    return shd


def add_page_number(doc):
    """页脚居中页码。"""
    for section in doc.sections:
        par = section.footer.paragraphs[0]
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = par.add_run()
        run.font.size = Pt(9)
        for kind, text in (("begin", None), (None, " PAGE "), ("end", None)):
            if kind:
                fld = OxmlElement("w:fldChar")
                fld.set(qn("w:fldCharType"), kind)
                run._r.append(fld)
            else:
                instr = OxmlElement("w:instrText")
                instr.set(qn("xml:space"), "preserve")
                instr.text = text
                run._r.append(instr)


def add_body_indent(doc):
    """正文首行缩进 2 字符，符合中文文档习惯。"""
    for name in ("Body Text", "First Paragraph", "Compact"):
        try:
            style = doc.styles[name]
        except KeyError:
            continue
        p_pr = style.element.get_or_add_pPr()
        ind = p_pr.find(qn("w:ind"))
        if ind is None:
            ind = OxmlElement("w:ind")
            p_pr.append(ind)
        ind.set(qn("w:firstLineChars"), "200")
        ind.set(qn("w:firstLine"), "420")


def number_captions(doc):
    """图注加“图 N：”，与正文引用一致（docx 没有 LaTeX 式自动编号）。"""
    n = 0
    for p in doc.paragraphs:
        if p.style.name != "Image Caption" or not p.text.strip():
            continue
        n += 1
        run = next((r for r in p.runs if r.text), None) or p.add_run()
        run.text = f"图 {n}：" + run.text.lstrip()
    assert n == 4, f"图注数量异常：{n}"


def main():
    doc = Document(SRC)
    split_subtitle(doc)
    add_body_indent(doc)
    number_captions(doc)
    for table in doc.tables:
        add_borders(table)
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Cm(2.2)
        section.left_margin = section.right_margin = Cm(2.4)
    add_page_number(doc)

    assert doc.tables and all(t._tbl.tblPr.find(qn("w:tblBorders")) is not None for t in doc.tables)
    assert any("常州大学首届智能体创新大赛" in p.text for p in doc.paragraphs)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print("已生成：", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
