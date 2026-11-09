#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复用项目介绍课件作为参赛作品展示 PPT。

用法（仓库根目录）:
    .venv/bin/python 英迈云/scripts/prep_deck.py

只做两件事：另存为参赛命名，并在首页页脚补一行赛事信息。
正文 16 页内容保持不变（内容与仓库实际实现一致）。
"""
import shutil
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Cm, Pt

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "scholarscope-competition-deck-v4.pptx"
OUT = ROOT / "英迈云" / "提交材料" / "研索ScholarScope-作品展示PPT.pptx"

FOOTER = "常州大学第六届“英迈云杯”大学生计算机应用大赛 · 应用技术赛道 创意组 · “人工智能+”"

OUT.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(SRC, OUT)

prs = Presentation(OUT)
slide = prs.slides[0]

# 首页副标题文本框过窄，导出 PDF 时被折行；加宽并保持居中
for sh in slide.shapes:
    if sh.has_text_frame and sh.text_frame.text == "面向研究者的科研工作台":
        center = sh.left + sh.width // 2
        sh.width = Cm(7.0)
        sh.left = center - sh.width // 2
box = slide.shapes.add_textbox(Cm(3.9), Cm(13.36), Cm(19.0), Cm(0.44))
p = box.text_frame.paragraphs[0]
p.alignment = PP_ALIGN.LEFT
run = p.add_run()
run.text = FOOTER
run.font.name = "PingFang SC"
run.font.size = Pt(7)
run.font.color.rgb = RGBColor(0x5A, 0x54, 0x48)

prs.save(OUT)
print(f"written: {OUT} ({len(prs.slides)} slides)")
