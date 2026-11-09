#!/usr/bin/env python3
"""Prepare a body-only correction and verify the retained template byte for byte.

Use the Codex primary runtime Python. This builder writes a candidate in .cache;
it never writes the user's source document. Review rendered pages before applying.
"""
from copy import copy, deepcopy
from pathlib import Path
from zipfile import ZipFile
from xml.parsers import expat
import hashlib
import json
import re

from docx import Document
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.text.paragraph import Paragraph
from docx.table import Table
from lxml import etree

from revise_competition_visuals import addp, fmt, picture, table

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / '.cache/competition-body-correction-20261014'
SOURCE = QA / 'before.docx'
CANDIDATE = QA / 'candidate.docx'
NS = {'w': qn('w:p').split('}')[0][1:]}
RELNS = 'http://schemas.openxmlformats.org/package/2006/relationships'


def text(element):
    return ''.join(element.xpath('.//w:t/text()', namespaces=NS))


def spans(xml):
    """Find direct body-child byte offsets without reserializing surrounding XML."""
    parser = expat.ParserCreate()
    depth = 0
    body_depth = None
    result = []
    start = None

    def opening(name, attrs):
        nonlocal depth, body_depth, start
        depth += 1
        if name == 'w:body':
            body_depth = depth
        elif body_depth is not None and depth == body_depth + 1:
            start = parser.CurrentByteIndex

    def closing(name):
        nonlocal depth, body_depth
        if body_depth is not None and depth == body_depth + 1:
            end = parser.CurrentByteIndex
            if xml[end:end + 2] == b'</':
                end = xml.index(b'>', end) + 1
            result.append((start, end))
        if name == 'w:body':
            body_depth = None
        depth -= 1

    parser.StartElementHandler = opening
    parser.EndElementHandler = closing
    parser.Parse(xml, True)
    return result


def replace_text(element, value):
    nodes = list(element.iter(qn('w:t')))
    if not nodes:
        raise ValueError('Expected a text paragraph')
    nodes[0].text = value
    for node in nodes[1:]:
        node.text = ''


def paragraph_format(element, context):
    p = Paragraph(element, context._body)
    value = p.text
    heading = bool(re.match(r'^[一二三四五]、', value))
    label = value in ('主要创新点：', '后续计划：')
    caption = value.startswith(('图 ', '表 '))
    if list(element.iter(qn('w:drawing'))):
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        snap = OxmlElement('w:snapToGrid')
        snap.set(qn('w:val'), '0')
        p._p.get_or_add_pPr().append(snap)
        return
    fmt(p, size=12 if heading else 9 if caption else 10.5,
        bold=heading or label, center=caption, keep=heading or label)
    p.paragraph_format.space_after = Pt(4 if heading else 3)
    p.paragraph_format.space_before = Pt(6 if heading else 0)
    # The template's inherited paragraph-mark size otherwise inflates line height.
    # Set readable leading locally; never alter its shared styles or document grid.
    p.paragraph_format.line_spacing = Pt(19 if heading else 14.5 if caption else 16)
    if value.startswith(('三、工程实现与验证', '四、应用价值与后续计划')):
        p.paragraph_format.page_break_before = True


def proof_format(element, context):
    """Retain every original cell's wording while fitting sensible column widths."""
    t = Table(element, context._body)
    t.autofit = False
    widths = [0.4, 2.15, 2.6, 1.05]
    for col, width in zip(t.columns, widths):
        col.width = Inches(width)
    for i, row in enumerate(t.rows):
        trpr = row._tr.get_or_add_trPr()
        for height in list(trpr.findall(qn('w:trHeight'))):
            trpr.remove(height)
        if trpr.find(qn('w:cantSplit')) is None:
            trpr.append(OxmlElement('w:cantSplit'))
        if i == 0 and trpr.find(qn('w:tblHeader')) is None:
            trpr.append(OxmlElement('w:tblHeader'))
        for cell, width in zip(row.cells, widths):
            cell.width = Inches(width)
            for p in cell.paragraphs:
                fmt(p, size=9.5, bold=i == 0)
                p.paragraph_format.line_spacing = Pt(14.5)
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.first_line_indent = Pt(0)
                p.paragraph_format.keep_with_next = False
            cell.vertical_alignment = 1
    # Retain the existing border style, with more suitable internal whitespace.
    margins = t._tbl.tblPr.find(qn('w:tblCellMar'))
    if margins is None:
        margins = OxmlElement('w:tblCellMar')
        t._tbl.tblPr.append(margins)
    for name, value in [('top', 72), ('bottom', 72), ('left', 80), ('right', 80)]:
        child = margins.find(qn('w:' + name))
        if child is None:
            child = OxmlElement('w:' + name)
            margins.append(child)
        child.set(qn('w:w'), str(value))
        child.set(qn('w:type'), 'dxa')


def build():
    context = Document(str(SOURCE))
    with ZipFile(SOURCE) as source:
        xml = source.read('word/document.xml')
        root = etree.fromstring(xml)
        body = root.find('w:body', NS)
        children = list(body)
        start = next(i for i, e in enumerate(children) if text(e).startswith('一、项目与需求'))
        end = next(i for i, e in enumerate(children[start:], start)
                   if e.xpath('.//w:br[@w:type="page"]', namespaces=NS))
        offsets = spans(xml)
        assert len(offsets) == len(children)
        originals = {text(e): deepcopy(e) for e in children[start:end] if text(e)}

        scratch = Document()
        # One explanatory architecture figure; the existing workflow stays intact.
        picture(scratch, 'architecture', '图 2  共用检索链路、课题证据引擎与外部依赖')
        architecture = [deepcopy(e) for e in scratch.element.body if e.tag != qn('w:sectPr')]
        scratch = Document()
        addp(scratch, '表 1  2026-10-14 工程验证结果与验收边界', size=9, bold=True, keep=True)
        table(scratch, ['验证项目', '结果', '范围与核验依据'], [
            ['自动化回归', '148 项通过\n0 项失败', '耗时 45.13 秒；覆盖账号、权限、证据、写作与导出；JUnit 记录 regression.xml'],
            ['其中用户流程', '24 项通过', '计入上述 148 项，含 21 组场景及参数化用例，不重复累计'],
            ['真实文件与前端', '通过', 'PDF 解析；DOCX、PPTX、图表及四类引文文件往返；生产构建、内联 JS 和 5 组 UI 脚本语法'],
            ['异常与账号隔离', '通过', '拒绝伪造证据和越权；检索故障返回安全提示，不泄露内部错误或生成虚构论文'],
            ['浏览器用户流程', '5 组未执行', '本轮执行环境限制本地端口监听；脚本语法通过不代表浏览器操作通过'],
            ['真实环境联调', '4 类待验证', '真实检索质量、云端模型质量、私人 Zotero、最新版容器与存储联调'],
        ], [1.18, 1.02, 4.0], size=9.5)
        tests = [deepcopy(e) for e in scratch.element.body if e.tag != qn('w:sectPr')]
        # Drop only the helper's final spacer paragraph; not the table content.
        tests = tests[:-1]
        for element in tests:
            for pnode in element.iter(qn('w:p')):
                Paragraph(pnode, scratch._body).paragraph_format.line_spacing = Pt(14.5)
        output = []
        changes = []
        skip = False
        for element in children[start:end]:
            value = text(element)
            if value == '验证情况：':
                output.extend(tests)
                skip = True
                continue
            if skip and value.startswith('如实说明：'):
                skip = False
            if skip:
                continue
            copied = parse_xml(etree.tostring(element))
            # Make only two substantive clarifications, retaining the user's argument.
            if value.startswith('核心技术：'):
                updated = value.replace('按用途组织带原文证据的结果', '按用途组织带标题或摘要依据的结果')
                updated = updated.replace('大模型承担理解与辅助分析，人工确认结论',
                                          '大模型辅助查询理解与证据分析，研究者核对并确认结论')
                replace_text(copied, updated)
                changes.append({'before': value, 'after': updated})
            elif value.startswith('（3）Web 与 MCP'):
                updated = value.replace('行为一致', '复用查询规划、检索与结果组织逻辑')
                replace_text(copied, updated)
                changes.append({'before': value, 'after': updated})
            if copied.tag == qn('w:p'):
                paragraph_format(copied, context)
            elif copied.tag == qn('w:tbl'):
                proof_format(copied, context)
            output.append(copied)
            if value.startswith('核心技术：'):
                output.extend(architecture)

        scratch = Document()
        addp(scratch, '第三方来源：学术元数据由 arXiv、OpenAlex、Crossref、Semantic Scholar 等接口提供；基础模型由云端供应方或 Ollama 所加载的模型提供，本项目未训练基础大模型。使用 React、FastAPI、PDF.js、SQLAlchemy、Tiptap、PptxGenJS 等开源组件。来源、版本与许可见项目依赖清单及架构文档，按相应条款使用。', size=9.5)
        addp(scratch, '复核材料：docs/testing/user-acceptance.md、正式验收的 regression.xml 与 report.json；第三方清单为 docs/implementation/dependency-licenses.json 和 research-platform-architecture.md。', size=9)
        for p in scratch.paragraphs:
            p.paragraph_format.line_spacing = Pt(14.5)
            p.alignment = 0
        output.extend(deepcopy(e) for e in scratch.element.body if e.tag != qn('w:sectPr'))

        relationships = etree.fromstring(source.read('word/_rels/document.xml.rels'))
        used = {r.get('Id') for r in relationships}
        number = max((int(x[3:]) for x in used if re.fullmatch(r'rId\d+', x)), default=0) + 1
        rid = f'rId{number}'
        image_name = 'word/media/scholarscope_architecture_20261014.png'
        if image_name in source.namelist():
            raise RuntimeError('New media name already exists; choose a fresh name')
        rel = etree.SubElement(relationships, '{' + RELNS + '}Relationship')
        rel.set('Id', rid)
        rel.set('Type', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image')
        rel.set('Target', image_name[len('word/'):])
        for element in architecture:
            for blip in element.iter(qn('a:blip')):
                blip.set(qn('r:embed'), rid)
            for pr in element.iter(qn('wp:docPr')):
                existing = [int(x.get('id', '0')) for x in root.iter(qn('wp:docPr'))]
                pr.set('id', str(max(existing, default=0) + 1))
                pr.set('name', 'ScholarScope technical architecture')
        assert b'Extension="png"' in source.read('[Content_Types].xml')
        first, last = offsets[start][0], offsets[end - 1][1]
        new_xml = xml[:first] + b''.join(etree.tostring(e, encoding='utf-8') for e in output) + xml[last:]
        candidate_parts = {
            'word/document.xml': new_xml,
            'word/_rels/document.xml.rels': etree.tostring(relationships, xml_declaration=True, encoding='UTF-8', standalone=True),
        }
        with ZipFile(CANDIDATE, 'w') as target:
            for info in source.infolist():
                target.writestr(copy(info), candidate_parts.get(info.filename, source.read(info.filename)))
            target.writestr(image_name, (ROOT / '比赛材料/江苏省青年发明家大赛/图表源文件/architecture.png').read_bytes())

        with ZipFile(CANDIDATE) as final:
            untouched = [n for n in source.namelist() if n not in candidate_parts]
            assert all(source.read(n) == final.read(n) for n in untouched)
            assert new_xml[:first] == xml[:first]
            assert new_xml.endswith(xml[last:])
            fixed_body = etree.fromstring(new_xml).find('w:body', NS)
            fixed_nodes = list(fixed_body)
            assert all(etree.tostring(a, method='c14n') == etree.tostring(b, method='c14n')
                       for a, b in zip(children[:start], fixed_nodes[:start]))
            assert all(etree.tostring(a, method='c14n') == etree.tostring(b, method='c14n')
                       for a, b in zip(children[end:], fixed_nodes[start + len(output):]))
            # Every non-test paragraph and all original proof cells remain verbatim,
            # except for the two stated clarifications.
            final_texts = [text(e) for e in fixed_nodes[start:start + len(output)]]
            excluded = {c['before'] for c in changes}
            kept = 0
            for value in originals:
                if value in excluded or value == '验证情况：' or value.startswith(('（1）自动化回归', '（2）真实文件验证', '（3）异常与隔离验证', '（4）验收边界')):
                    continue
                assert value in final_texts, value
                kept += 1
            report = {'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                      'candidate_sha256': hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(),
                      'body_start': start, 'body_end': end, 'kept_text_blocks': kept,
                      'outside_body_xml_byte_identical': True,
                      'untouched_zip_parts': len(untouched), 'original_images_unchanged': True,
                      'changes': changes, 'added_architecture_figures': 1,
                      'existing_workflow_preserved': True, 'test_table_rows': 6}
            (QA / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({k: v for k, v in report.items() if k != 'changes'}, ensure_ascii=False))


if __name__ == '__main__':
    build()
