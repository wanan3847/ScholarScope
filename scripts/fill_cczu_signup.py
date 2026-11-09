#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""填写常州大学首届智能体创新大赛报名表（附件3）：只填作品与赛道信息，个人信息留空。

用法（仓库根目录）：python3 scripts/fill_cczu_signup.py
模板不动，输出到 比赛材料/常州大学智能体大赛/提交材料/。
"""
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "比赛材料" / "常州大学智能体大赛" / "赛事文件" / "附件3-报名表.docx"
OUT = ROOT / "比赛材料" / "常州大学智能体大赛" / "提交材料" / "附件3-报名表（研索ScholarScope）.docx"

WORK_NAME = "研索 ScholarScope——研究问题驱动的科研文献 Agent 工作台"
COLLEGE = "计算机与人工智能学院"
TRACK = 1  # 0=通用智能体创意应用, 1=工具调度与自主任务智能体, 2=AI+跨学科融合创新
SUMMARY = (
    "研索 ScholarScope 是面向研究生与科研工程师的科研文献智能体工作台。用户输入带方法、研究对象"
    "与年份约束的研究问题，系统自动拆解检索步骤，并行检索 arXiv、OpenAlex、Crossref、"
    "Semantic Scholar、Europe PMC 与本地索引，合并去重后沿引文关系扩展候选，按研究用途组织推荐"
    "并给出可在原文中核对的证据片段。文献进入课题后可生成带页码出处的研究矩阵、跨论文原文问答、"
    "综述草稿与可编辑 Word/PPTX 产物；来源变化会把依赖它的产物标记为待复核。单源故障按预算降级、"
    "全源失败不生成占位论文，模型不可用时保留原文与人工流程。Web 与 MCP 共用同一条执行链路。"
    "2026-11-03 实测 148 项自动化回归通过，Web 与 MCP 均可运行。"
)


def fill(cell, text, size=12, bold=False):
    """写入单元格：清空原有空段落，保留段落属性，中文用宋体。"""
    first = cell.paragraphs[0]
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    for run in list(first.runs):
        run._r.getparent().remove(run._r)
    run = first.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    return run


def tick(track_cell, index):
    """勾选第 index 个 Word 复选框（w14:checkbox），并把显示字符改成 ☑。"""
    for i, par in enumerate(track_cell.paragraphs):
        for sdt in par._p.findall(qn("w:sdt")):
            checkbox = sdt.find(".//" + qn("w14:checkbox"))
            if checkbox is None:
                continue
            on = i == index
            checkbox.find(qn("w14:checked")).set(qn("w14:val"), "1" if on else "0")
            for t in sdt.iter(qn("w:t")):
                t.text = "☑" if on else "☐"
                rpr = t.getparent().find(qn("w:rPr"))
                if rpr is not None:
                    for tag in ("w:ascii", "w:hAnsi", "w:eastAsia"):
                        rpr.find(qn("w:rFonts")).set(qn(tag), "宋体")


def main():
    doc = Document(TEMPLATE)
    table = doc.tables[0]
    fill(table.rows[0].cells[-1], WORK_NAME, size=12, bold=True)
    fill(table.rows[1].cells[-1], COLLEGE)
    tick(table.rows[2].cells[-1], TRACK)
    fill(table.rows[13].cells[-1], SUMMARY, size=10.5)

    # 自检：作品信息已写入、仅勾选一个赛道、个人信息保持空白
    assert table.rows[0].cells[-1].text.strip() == WORK_NAME
    assert table.rows[1].cells[-1].text.strip() == COLLEGE
    boxes = [t.text for sdt in table.rows[2].cells[-1]._tc.iter(qn("w:sdt")) for t in sdt.iter(qn("w:t")) if t.text and t.text in "☐☑"]
    assert boxes.count("☑") == 1 and len(boxes) == 3, boxes
    blanks = [c.text for c in table.rows[4].cells[3:]]
    blanks += [c.text for row in table.rows[6:11] for c in row.cells]
    blanks += [c.text for row in table.rows[11:13] for c in row.cells[1:]]
    labels = {"团队成员", "团队主要成员", "负责人", "姓名", "所在学院", "专业班级", "学号", "手机号", "手机号码", "指导老师\n（可不填）"}
    filled = [t for t in blanks if t.strip() and t.strip() not in labels]
    assert not filled, filled

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print("已生成：", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
