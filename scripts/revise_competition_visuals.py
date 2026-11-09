#!/usr/bin/env python3
"""Create a separate narrative suggestion without writing the user's original.

Run with the Codex primary runtime Python, then render_docx.py for page QA.
The retained source must already contain the completed application form.
"""
from pathlib import Path
from copy import deepcopy
import json
import re
import shutil
import subprocess
import hashlib
import os
from xml.sax.saxutils import escape

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / '比赛材料/江苏省青年发明家大赛/申报材料/江苏省青年发明家创新大赛_人工智能+专项赛_参赛项目申报材料_研索ScholarScope.docx'
OUT = ROOT / '比赛材料/江苏省青年发明家大赛/申报材料/研索ScholarScope_申报书正文图表修订建议_2026-10-14.docx'
ASSETS = ROOT / '比赛材料/江苏省青年发明家大赛/图表源文件'
QA = ROOT / '.cache/competition-visuals'
RUNTIME = Path(os.environ.get('CODEX_ARTIFACT_RUNTIME', str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies')))


def html_diagram(slug, title, desc, width, height, content):
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>{title}</title><style>body{{margin:0;background:#fff;color:#111}}
.diagram-container{{width:100%;overflow-x:auto}}svg{{display:block;width:100%;min-width:{width}px}}
text{{font-family:"PingFang SC","Microsoft YaHei",sans-serif;fill:#111}}
@media print{{.diagram-container{{overflow-x:visible}}svg{{min-width:0}}}}</style>
<div class="diagram-container"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="{slug}-title {slug}-desc">
<title id="{slug}-title">{title}</title><desc id="{slug}-desc">{desc}</desc>
<defs><marker id="{slug}-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="#555"/></marker></defs>
<rect width="{width}" height="{height}" fill="#fff"/>{content}</svg></div></html>'''


def box(x, y, w, h, title, lines=(), focal=False, dashed=False):
    border = ' stroke-dasharray="6 4"' if dashed else ''
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{"#ececec" if focal else "#fff"}" stroke="#555" stroke-width="{2.5 if focal else 1.5}"{border}/>'
    s += f'<text x="{x+w/2}" y="{y+30}" text-anchor="middle" font-size="24" font-weight="600">{escape(title)}</text>'
    for i, line in enumerate(lines):
        s += f'<text x="{x+w/2}" y="{y+56+24*i}" text-anchor="middle" font-size="19">{escape(line)}</text>'
    return s


def figures():
    ASSETS.mkdir(parents=True, exist_ok=True)
    arch = ''
    routes = [
        'M240 136 V200',
        'M600 136 V160 Q600 168 592 168 H368 Q360 168 360 176 V200',
        'M800 136 V200',
        'M172 312 V408',
        'M348 312 V360 Q348 368 356 368 H432 Q440 368 440 376 V408',
        'M612 312 V348 Q612 356 604 356 H528 Q520 356 520 364 V408',
        'M788 312 V408',
    ]
    for j, route in enumerate(routes):
        arch += f'<path d="{route}" fill="none" stroke="#555" stroke-width="2" marker-end="url(#architecture-arrow)"'+(' stroke-dasharray="6 4"' if j in (3,4,5) else '')+'/>'
    arch += box(40,40,400,96,'MCP 工具入口',('stdio / SSE','工具直接调用共用检索链路'))
    arch += box(520,40,400,96,'Web 科研工作台',('React + FastAPI','会话认证 · 项目权限'))
    arch += box(40,200,400,112,'共用检索引擎',('Orchestrator / SPAR2','约束规划 · 多源召回 · 用途选择'),True)
    arch += box(520,200,400,112,'课题与证据引擎',('页码证据 · 矩阵 / 筛选 / 写作','版本关联 · 来源变化提示'),True)
    arch += box(40,408,264,104,'学术来源与本地索引',('arXiv / OpenAlex','Crossref / S2 / 本地'),dashed=True)
    arch += box(348,408,264,104,'可配置模型服务',('云端 API / Ollama','辅助分析 · 人工确认'),dashed=True)
    arch += box(656,408,264,104,'资料持久化',('本轮 SQLite / 本地文件','可选 PostgreSQL / S3'))
    arch += '<path d="M40 544 H76" stroke="#555" stroke-width="2"/><text x="88" y="550" font-size="18">内部调用</text><path d="M260 544 H296" stroke="#555" stroke-width="2" stroke-dasharray="6 4"/><text x="308" y="550" font-size="18">检索或模型调用，受网络及配置影响</text>'
    flow = ''
    # Six stages in two rows. Orthogonal arrows retain reading order.
    for route in ['M280 100 H340','M620 100 H680','M800 160 V180 Q800 188 792 188 H708 Q700 188 700 196 V208','M680 268 H620','M340 268 H280']:
        flow += f'<path d="{route}" fill="none" stroke="#555" stroke-width="2" marker-end="url(#workflow-arrow)"/>'
    flow += box(40,40,240,120,'1 提出研究问题',('主题 / 方法 / 对象','明确年份与约束'))
    flow += box(340,40,280,120,'2 检索与用途判断',('多源召回与去重','标题 / 摘要核对'),True)
    flow += box(680,40,240,120,'3 阅读并记录证据',('真实 PDF / 页码 / 片段','研究者确认'))
    flow += box(680,208,240,120,'4 整理与筛选',('研究矩阵 / 双人筛选','保留人工修订'))
    flow += box(340,208,280,120,'5 辅助写作与制图',('章节与引用关联','核验数值来源'))
    flow += box(40,208,240,120,'6 导出研究成果',('DOCX / PDF / PPTX','CSV / Excel / 引文'))
    flow += '<text x="480" y="364" text-anchor="middle" font-size="20">来源或版本变化 → 提示相关成果过期 → 复核后重新生成</text>'
    for slug,title,desc,h,content in [
        ('architecture','研索技术架构','Web 和 MCP 各有入口并共用检索链路；Web 还调用课题证据引擎，连接模型服务与资料存储。',568,arch),
        ('workflow','从研究问题到可追溯成果','研究者提出问题，经检索、证据确认、整理与辅助写作导出成果；来源变化时重新复核。',392,flow),
    ]:
        html=html_diagram(slug,title,desc,960,h,content)
        (ASSETS/f'{slug}.html').write_text(html)
    renderer=QA/'render-figures.cjs'
    renderer.write_text('''const fs=require('fs');const path=require('path');
const sharp=require(process.argv[2]);
(async()=>{for(const src of process.argv.slice(3)){
const html=fs.readFileSync(src,'utf8');let svg=html.match(/<svg[\\s\\S]*?<\\/svg>/)[0];
svg=svg.replace('<defs>','<style>text{font-family:"PingFang SC","Microsoft YaHei",sans-serif;fill:#111}</style><defs>');
fs.writeFileSync(src.replace('.html','.svg'),svg);
await sharp(Buffer.from(svg),{density:240}).png().toFile(src.replace('.html','.png'));
}})().catch(e=>{console.error(e);process.exit(1)});''')
    subprocess.run([str(RUNTIME/'node/bin/node'),str(renderer),str(RUNTIME/'node/node_modules/sharp'),str(ASSETS/'architecture.html'),str(ASSETS/'workflow.html')],check=True)


def fmt(p, size=10.5, bold=False, center=False, keep=False):
    p.paragraph_format.space_before=Pt(0)
    p.paragraph_format.space_after=Pt(5)
    p.paragraph_format.line_spacing=1.3
    p.paragraph_format.keep_with_next=keep
    p.paragraph_format.widow_control=True
    snap=OxmlElement('w:snapToGrid');snap.set(qn('w:val'),'0');p._p.get_or_add_pPr().append(snap)
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.JUSTIFY
    for r in p.runs:
        r.font.name='宋体'; r.font.size=Pt(size); r.bold=bold;r.font.color.rgb=RGBColor(0,0,0)
        rp=r._r.get_or_add_rPr();f=rp.find(qn('w:rFonts'))
        if f is not None: f.set(qn('w:eastAsia'),'宋体')
    return p


def addp(d,text,size=10.5,bold=False,center=False,keep=False):
    return fmt(d.add_paragraph(text),size,bold,center,keep)


def table(d, headers, rows, widths, size=9.5):
    t=d.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
    for c,w in zip(t.columns,widths):c.width=Inches(w)
    for c,text,w in zip(t.rows[0].cells,headers,widths):c.width=Inches(w);c.text=text
    for row in rows:
        cells=t.add_row().cells
        for c,text,w in zip(cells,row,widths):c.width=Inches(w);c.text=str(text)
    pr=t._tbl.tblPr
    margins=OxmlElement('w:tblCellMar')
    for name,val in [('top',72),('bottom',72),('left',88),('right',88)]:
        e=OxmlElement('w:'+name);e.set(qn('w:w'),str(val));e.set(qn('w:type'),'dxa');margins.append(e)
    pr.append(margins)
    borders=OxmlElement('w:tblBorders')
    for name in ['top','left','bottom','right','insideH','insideV']:
        e=OxmlElement('w:'+name);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'B8B8B8');borders.append(e)
    pr.append(borders)
    rep=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(rep)
    for i,row in enumerate(t.rows):
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for j,c in enumerate(row.cells):
            c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if i==0:
                shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'EAEAEA');c._tc.get_or_add_tcPr().append(shade)
            for p in c.paragraphs:
                fmt(p,size,bold=i==0)
                p.alignment=WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.space_after=Pt(0)
                if j==0 and len(c.text)<16:p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    addp(d,'',size=2).paragraph_format.space_after=Pt(3)
    return t


def picture(d, slug, caption):
    p=d.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after=Pt(2);p.paragraph_format.keep_with_next=True
    p.paragraph_format.line_spacing=1.0
    snap=OxmlElement('w:snapToGrid');snap.set(qn('w:val'),'0');p._p.get_or_add_pPr().append(snap)
    r=p.add_run();r.add_picture(str(ASSETS/f'{slug}.png'),width=Inches(6.25))
    node=r._r.xpath('.//wp:docPr')[0];node.set('descr',caption)
    addp(d,caption,size=9,center=True)


def main():
    QA.mkdir(parents=True,exist_ok=True)
    source=QA/'before-visuals.docx'
    if not source.exists():shutil.copy2(ORIGINAL,source)
    previous_hash=QA/'narrative-output.sha256'
    if OUT.exists() and (not previous_hash.exists() or hashlib.sha256(OUT.read_bytes()).hexdigest()!=previous_hash.read_text().strip()):
        raise RuntimeError('Suggestion file was edited outside this builder; refusing to overwrite it.')
    d=Document(str(source))
    body=d.element.body
    children=list(body)
    start=next(i for i,e in enumerate(children) if ''.join(e.xpath('.//w:t/text()')).startswith('一、项目与需求'))
    end=next(i for i,e in enumerate(children[start:],start) if e.xpath('.//w:br[@w:type="page"]'))
    figures()
    scratch=Document()
    addp(scratch,'研索 ScholarScope 参赛项目申报书正文',size=14,bold=True,center=True,keep=True)
    addp(scratch,'一、项目与需求',size=12,bold=True,keep=True)
    addp(scratch,'研索 ScholarScope 面向研究生与科研人员，将研究问题驱动的检索、证据阅读和课题整理连接起来。针对跨源搜索耗时、推荐依据难核对、阅读结果难复用的需求，系统保留主题、方法、研究对象与年份约束，并把原文依据关联到矩阵、综述和演示稿。')
    picture(scratch,'workflow','图 1  研究工作流与成果追溯方式')
    addp(scratch,'二、人工智能核心技术与创新',size=12,bold=True,keep=True)
    addp(scratch,'技术路线：查询规划 → 多源召回与去重 → 语义预筛 → 引文扩展 → 按研究用途组织带依据的结果。Web 与 MCP 共用 Orchestrator/SPAR2；大模型辅助理解和章节分析，推荐理由以真实标题或摘要为依据。各阶段设置预算，单源失败降级，全源失败不生成占位论文；原文证据与人工编辑保留。')
    picture(scratch,'architecture','图 2  共用检索链路、证据引擎与外部依赖')
    addp(scratch,'表 1  主要创新点与可核验实现',size=9.5,bold=True,keep=True)
    table(scratch,['研究问题','项目实现','核验方式'],[
        ['标题命中不等于适用','保留主题、方法、对象和年份约束，按研究用途组织结果','检索约束与原文片段核对'],
        ['结论与原文容易脱节','文献、页码、片段和版本关联矩阵及文稿','确认引用；拒绝伪造证据'],
        ['资料变动影响既有成果','来源变化标记关联文稿、演示稿与导出产物过期','变更来源后核验失效状态'],
        ['资料分散且多人权限不同','统一课题库、收藏与已阅；角色权限和账号隔离','跨账号及只读成员越权用例'],
    ],[1.25,3.15,1.85])
    addp(scratch,'三、工程实现与验证',size=12,bold=True,keep=True)
    addp(scratch,'后端采用 FastAPI 与 SQLAlchemy，前端采用 React；具备 PDF 阅读、研究矩阵、双人筛选、综述写作、图表与原生文件导出。模型设置接入既有模型路由，提供常用选项；Zotero 支持加密配置、只读检查及授权同步。本轮测试使用隔离账号、SQLite 和本地文件，未调用真实模型或私人文献库。')
    addp(scratch,'表 2  2026-10-14 测试结果与验收边界',size=9.5,bold=True,keep=True)
    table(scratch,['验证项','实测结果','证据与范围'],[
        ['Python 回归','148 通过 / 0 失败','regression.xml；耗时 45.13 秒'],
        ['其中用户流程','24 项通过','包含于上述 148 项；共 21 组场景'],
        ['前端生产构建','通过','production-build.log'],
        ['脚本语法检查','通过','内联 JS 及 5 组 UI 脚本；不等于 UI 执行'],
        ['最新浏览器流程','5 组未执行','执行环境禁止本地监听端口'],
        ['外部与部署联调','4 项待验证','真实检索、模型质量、私人 Zotero、最新版容器存储'],
    ],[1.35,1.45,3.45])
    addp(scratch,'文件核验覆盖 PDF 解析、DOCX/PPTX 内容、图表与四类引文文件往返；异常用例覆盖伪造引用、越权、修订冲突和来源变更。已修复检索故障返回内部错误的问题。测试通过证明受控环境内的功能与数据约束有效，不能据此宣称真实 AI 质量达标或完整产品验收完成。',size=10)
    addp(scratch,'复核入口：docs/testing/user-acceptance.md；运行 .venv/bin/python src/tests/run_acceptance.py，生成逐项日志与 JUnit 记录。固定问题集的检索有效性评测与研究者试用仍需完成。',size=9)
    addp(scratch,'四、应用价值与后续计划',size=12,bold=True,keep=True)
    addp(scratch,'适用于科研选题、方法比较、文献跟踪与综述整理。资料可本地保存，关键前端资源不依赖 CDN，适合课题组私有化部署。减少重复搬运和核对的实际收益，需通过目标研究者任务测试与现有流程对照评估。',keep=True)
    addp(scratch,'表 3  后续验证与应用计划',size=9.5,bold=True,keep=True)
    table(scratch,['下一步','验证目标'],[
        ['真实检索与模型评测','固定问题集，人工标注相关性，抽查依据与章节完整性'],
        ['系统联调验收','完成浏览器、真实 API、Zotero 和容器存储测试'],
        ['研究者试用与试点','记录任务耗时、错误及反馈；完善备份、授权和部署说明'],
    ],[1.65,4.6])
    addp(scratch,'五、佐证材料与第三方来源',size=12,bold=True,keep=True)
    addp(scratch,'表 4  已有材料、来源与状态',size=9.5,bold=True,keep=True)
    table(scratch,['材料 / 资源','来源与可核验位置','当前状态'],[
        ['源码与技术文档','本项目业务流程；README 及 docs/implementation/','可复现，验收未完成'],
        ['测试与操作手册','本项目测试脚本和日志；历史实机截图 19 张','148 项回归通过'],
        ['软件著作权材料','《智能学术文献检索与分析软件》V1.0；杨亚洲','申请中，未取得证书'],
        ['学术数据与模型','arXiv、OpenAlex、Crossref、Semantic Scholar；各模型供应方','按配置调用；注明依据'],
        ['开源组件与本地模型','React / FastAPI / PDF.js / SQLAlchemy / Tiptap / PptxGenJS 等','依赖及许可清单可核对'],
    ],[1.35,3.35,1.55],size=9)
    addp(scratch,'第三方来源清单：docs/implementation/dependency-licenses.json 与 research-platform-architecture.md；模型权重、数据源接口和组件各按其条款使用。无专利与已发表论文。个人账号、私有文献及密钥不随材料提交；第三方需求证明和系统化研究者试用报告尚未形成。',size=9)
    # Images belong to scratch's relationships; transplant through the retained package.
    for el in list(scratch.element.body):
        if el.tag==qn('w:sectPr'):continue
        for blip in el.xpath('.//a:blip'):
            old_id=blip.get(qn('r:embed'))
            image=scratch.part.related_parts[old_id]
            new_id=d.part.relate_to(image,'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image')
            blip.set(qn('r:embed'),new_id)
    nodes=[deepcopy(e) for e in scratch.element.body if e.tag!=qn('w:sectPr')]
    # Deliver only the proposed narrative; the retained original is never saved.
    for e in children:
        if e.tag!=qn('w:sectPr'):body.remove(e)
    for i,e in enumerate(nodes):body.insert(i,e)
    d.save(str(OUT))
    previous_hash.write_text(hashlib.sha256(OUT.read_bytes()).hexdigest())
    check=Document(str(OUT))
    assert len(check.inline_shapes)==2
    assert len(check.tables)==4
    (QA/'structure-check.json').write_text(json.dumps({'figures':2,'tables':4,'scope':'narrative_only','original_never_written':True,'source':str(source),'output':str(OUT)},ensure_ascii=False,indent=2))
    print(OUT)
    print('Narrative-only suggestion: 2 figures, 4 editable tables; original not written.')


if __name__=='__main__':main()
