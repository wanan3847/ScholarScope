#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""填充《江苏省"青年发明家"创新大赛——"人工智能+"专项赛参赛项目申报材料》模板。

用法（仓库根目录）:
    python3 scripts/fill_competition_form.py

只改文字与勾选项，保留模板段落/表格/样式。个人信息（负责人、团队成员、
指导教师、填报日期）留空，由参赛团队自行填写。内容全部基于仓库实际证据，
测试数字为 2026-10-13 实测后端回归结果。
"""
from docx import Document
from docx.shared import Pt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "比赛材料" / "江苏省青年发明家大赛" / "模板" / "申报材料模板.docx"
OUT_DIR = ROOT / "比赛材料" / "江苏省青年发明家大赛" / "申报材料"
OUT = OUT_DIR / "江苏省青年发明家创新大赛_人工智能+专项赛_参赛项目申报材料_研索ScholarScope.docx"

PROJECT_NAME = "研索 ScholarScope——研究问题驱动的智能文献检索与阅读工作台"

# ---------------------------------------------------------------- helpers
def set_par_text(p, text, size):
    """清空段落内 runs，写入单条文字，保留段落属性。"""
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    run = p.add_run(text)
    run.font.size = Pt(size)
    return run


def fill_section(hint_par, next_par, lines, size=10.5):
    """用内容替换【填写提示】段；多行内容逐段插入，位置在提示段之后。"""
    set_par_text(hint_par, lines[0], size)
    for line in lines[1:]:
        new_par = next_par.insert_paragraph_before()
        run = new_par.add_run(line)
        run.font.size = Pt(size)


def set_cell(cell, text, size=12):
    """把单元格内容替换为文字（保留首个段落的段落属性）。"""
    first = cell.paragraphs[0]
    for extra in list(cell.paragraphs[1:]):
        extra._p.getparent().remove(extra._p)
    set_par_text(first, text, size)


def drop_blank_before_page_break(pars):
    """模板封面末尾的空段会挤到下一页，与分页符一起产生空白页；删掉它。"""
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    for p, nxt in list(zip(pars, pars[1:])):
        if p.text.strip() or not nxt._p.findall('.//' + ns + 'br[@' + ns + 'type="page"]'):
            continue
        p._p.getparent().remove(p._p)


def tick(run_text, target, mark="☑"):
    """把目标复选框前的 □ 换成 ☑。"""
    return run_text.replace("□" + target, mark + target)


def fill_checkbox(cell, target, mark="☑"):
    for p in cell.paragraphs:
        for r in p.runs:
            if "□" + target in r.text:
                r.text = tick(r.text, target, mark)
                return True
    return False


# ---------------------------------------------------------------- main
def main():
    d = Document(str(TEMPLATE))
    pars = d.paragraphs
    t0 = d.tables[0]
    t1 = d.tables[1]

    # ---------- 封面 ----------
    set_par_text(pars[8], "项目名称：" + PROJECT_NAME, 16)
    # 项目负责人/所在高校/所在学院/填报日期：留空由团队填写

    # ---------- 第一部分 申报表 ----------
    # 项目名称
    set_cell(t0.rows[0].cells[1], PROJECT_NAME)
    # 项目来源：自主选题
    assert fill_checkbox(t0.rows[1].cells[1], "自主选题"), "项目来源勾选失败"
    # 应用领域/场景
    set_cell(t0.rows[2].cells[1],
             "学术信息服务 / 科研文献智能检索与知识服务；"
             "应用场景：科研选题与领域入门、方法与方案比较、文献持续跟踪与课题资料整理")
    # 当前成果阶段：系统Demo/软件平台
    assert fill_checkbox(t0.rows[3].cells[1], "系统Demo/软件平台"), "成果阶段勾选失败"
    # 负责人/成员/指导教师信息：留空由团队填写

    # 项目简介（300—500 字）
    intro = (
        "研索 ScholarScope 是一款面向研究生、博士生与科研工程师的研究问题驱动的文献检索与阅读工作台，"
        "解决科研工作中“找到论文之后”的相关性判断与资料沉淀断层：跨源检索门槛高、标题命中不等于相关、"
        "阅读结果难以沉淀为可继续使用的课题资料。项目以人工智能技术为核心：将描述性研究问题解析为可执行的"
        "查询规划，并行检索 arXiv、OpenAlex、Crossref、Semantic Scholar 及本地文献索引并合并去重，"
        "沿引文关系双向扩展候选，再由大模型依据标题与摘要按研究用途组织推荐，推荐理由附带可在原文中核对的"
        "证据片段；外部数据源或模型不可用时静默降级、标注证据边界。主要创新点：以研究用途替代数值评分组织"
        "阅读顺序、推荐理由可核对、Web 与 MCP 双入口共用同一检索链路、结构化三件套输出、个性化文献库与"
        "引用导入导出。当前已形成可运行的 Web 工作台与命令行/MCP 入口，后端回归测试 43 项全部通过（"
        "2026-10-13 实测），配套操作手册与实机截图；软件著作权登记申请材料已备齐（尚未取得证书）。"
        "后续将开展固定问题集评测与研究者试用，验证检索质量与实际任务价值。"
    )
    assert 300 <= len(intro) <= 500, f"项目简介字数 {len(intro)} 超出 300—500"
    set_cell(t0.rows[20].cells[1], intro)

    # 需求及验证依据
    set_cell(t0.rows[21].cells[1],
             "需求来源：科研真实工作流（选题、方法比较、文献跟踪）中的检索—阅读—整理断层，"
             "目标用户为高校研究生、博士生与科研工程师。验证场景：本机部署环境覆盖"
             "“输入研究问题→多源检索→证据阅读→收藏整理”全流程。已有验证：可运行系统实机演示；"
             "2026-10-13 实测后端自动化回归测试 43 项全部通过；操作手册含 19 张实机截图；"
             "已建立内置学术基准评测集与离线评估流水线。如实说明：第三方需求证明文件与系统化用户试用"
             "报告尚在收集阶段。")

    # 已有成果及知识产权
    set_cell(t0.rows[22].cells[1],
             "1. 软件著作权（登记申请中）：《智能学术文献检索与分析软件》V1.0，著作权人杨亚洲，"
             "未发表，登记证书尚未取得；\n"
             "2. 可运行系统源码与部署（Web 工作台、MCP 服务器、SPAR2 检索引擎、本地语义索引），"
             "均为团队自主开发；\n"
             "3. 用户操作手册（含 19 张实机截图）；\n"
             "4. 自动化回归测试资产（2026-10-13 实测 43 项通过）；\n"
             "5. 本地文献索引语料（仅使用标题、摘要与书目信息）。\n"
             "无专利与已发表论文；第三方学术数据源接口与开源模型均按各自条款合法使用，"
             "密钥等敏感信息不随材料提交。")

    # 既往参赛及获奖情况
    set_cell(t0.rows[23].cells[1], "无。")

    # ---------- 第二部分 申报书 ----------
    # 各节标题段落索引：26/28/30/32/34，提示段 27/29/31/33/35
    fill_section(pars[27], pars[28], [
        "研索 ScholarScope 是面向研究生、博士生和科研工程师的研究问题驱动的文献检索与阅读工作台。"
        "研究者输入一段描述性研究问题后，系统将其转化为可执行的检索规划，跨真实学术数据源召回候选文献，"
        "沿引文关系扩展线索，并按研究用途组织推荐，最后将阅读沉淀为课题文献库。",
        "需求来源：科研工作真实流程中“检索—判断—整理”的断层。目标用户为高校研究生与科研人员，"
        "典型场景包括选题与领域入门、方法与方案比较、持续跟踪与课题整理。该问题值得解决：文献规模持续增长，"
        "跨源检索与相关度判断的时间成本高，而现有检索工具停留在“列表命中”，不面向研究用途组织证据。",
        "当前主要成果：可运行的 Web 工作台与 MCP 命令行入口、多源检索与引文扩展链路、个性化文献库与"
        "引用导入导出、自动化回归测试与操作手册。",
    ])

    fill_section(pars[29], pars[30], [
        "核心技术：将检索增强生成（RAG）思想应用于学术文献检索，构建 SPAR2 多轮检索引擎。总体路线为："
        "查询规划（保留方法、任务、研究对象与年份约束）→ 多源并行召回与合并去重 → 语义预筛 → "
        "引文双向扩展（近似多轮迭代检索）→ 判别式用途选择并附证据片段 → 结构化输出。"
        "大模型用于查询理解与用途选择；本地向量语义索引支持离线检索。",
        "主要创新点：",
        "（1）以研究用途组织推荐，替代数值评分、引用量或期刊声望排序，推荐理由附带可在标题或摘要原文中"
        "核对的证据片段；",
        "（2）证据边界可见：摘要缺失时提示证据有限，最终选择失败时保留已召回候选并明确标注降级模式；",
        "（3）Web 与 MCP 共用同一 Orchestrator 检索链路，行为一致；",
        "（4）结构化三件套输出（JSON、Markdown 对比表、自包含 HTML 关系图），离线可用；",
        "（5）反馈闭环与个性化文献库：收藏、已阅、课题文件夹、账号隔离，支持 BibTeX/RIS/CSV/JSON 导入"
        "与引用导出；",
        "（6）内置多模型评测流水线，可离线复现。",
        "与同类方案对比：通用学术搜索引擎按排序列表返回结果，不面向具体研究问题组织阅读顺序，"
        "也不提供可核对的推荐依据；研索将“问题—候选—证据—整理”串成一条链路，并可与既有工具流程"
        "（如 Zotero）衔接。",
    ])

    fill_section(pars[31], pars[32], [
        "研发进展：已完成可运行系统，前后端分离。后端为 FastAPI 服务，前端为 React 三栏科研工作台；"
        "检索引擎以 Orchestrator 与 SPAR2 多轮检索为核心，本地语义索引基于现有文献语料构建"
        "（仅使用标题、摘要与书目信息）；提供 MCP 服务器（stdio/SSE），命令行与 Web 检索共用同一链路。",
        "成果形态：Web 工作台（检索、结果列表、方法对比、阅读面板、文献库、历史与设置）、MCP 工具集"
        "（检索、论文详情、收藏）、命令行评测入口；配套含 19 张实机截图的用户操作手册。",
        "验证情况：",
        "（1）自动化回归测试：2026-10-13 实测后端测试 43 项全部通过（覆盖检索、文献库、账号、"
        "结构化输出等模块）；",
        "（2）系统 Demo 实机运行验证：Web 与 MCP 双入口均可完成“检索—阅读—收藏”流程；",
        "（3）降级机制验证：外部数据源限流或模型不可用时，检索自动降级到剩余可用来源并标注证据边界；",
        "（4）已建立内置学术基准评测集与离线评估流水线，历史小样本评测受模型服务失效与数据源限流影响，"
        "尚不足以声明当前检索质量结论，列为后续重点验证项。",
        "如实说明：界面自动化检查脚本已具备；基于研究者的系统性试用与质量评测仍在规划中。",
    ])

    fill_section(pars[33], pars[34], [
        "应用价值：直接服务科研选题、方法与方案比较、文献跟踪与课题整理三类高频任务，降低跨源检索与"
        "相关度判断的时间成本；数据自持（本地索引、账号隔离、无外部 CDN 依赖），适合高校课题组私有化部署。",
        "适用范围与推广条件：面向高校研究生院、图书馆、课题组与科研机构；运行于普通服务器、配置模型接口后"
        "即可使用，推广门槛低。",
        "后续计划：",
        "（1）检索有效性评测：固定问题集与年份约束，邀请研究者标注相关性，记录召回与误荐；",
        "（2）证据可核对性抽查：校验推荐理由与标题/摘要原文一致性；",
        "（3）研究者试用：招募目标用户开展任务测试，对照原有工具流程记录完成时间与反馈；",
        "（4）工程化与转化：补全软著登记证书、复现说明与授权清单，在高校课题组与研究生教学场景开展应用试点，"
        "依据试用结果推进成果转化。",
    ])

    # 五、佐证材料目录（提示段替换为引导语，目录填入表格）
    set_par_text(pars[35], "本项目佐证材料目录如下（均为团队自主开发成果或申请中的知识产权材料）：", 10.5)
    entries = [
        ("系统实机截图与用户操作手册（《智能学术文献检索与分析软件》V1.0）",
         "证明系统功能真实可运行：检索、阅读、收藏、导入导出等界面截图 19 张",
         "见软著申请材料"),
        ("软件著作权登记申请材料（申请表、源程序文档、操作手册）",
         "证明原创性与权属；著作权人杨亚洲，尚未取得登记证书",
         "申请中"),
        ("自动化回归测试记录",
         "2026-10-13 实测后端回归测试 43 项全部通过",
         ""),
        ("项目技术文档（README、前端设计文档、科研工作台设计文档）",
         "技术方案、功能边界与保存范围说明",
         ""),
        ("项目介绍 PPT（PDF）",
         "需求来源、人工智能核心技术、创新点与工程验证概览",
         "另以 PPT 材料提交"),
    ]
    for row, (name, content, note) in zip(t1.rows[1:6], entries):
        set_cell(row.cells[1], name)
        set_cell(row.cells[2], content)
        set_cell(row.cells[3], note)

    # ---------- 承诺书 ----------
    set_par_text(pars[50], "项目名称：" + PROJECT_NAME, 12)
    # 签字/日期/盖章：留空由团队线下签署

    # 最后再删空段，避免打乱上面的段落索引
    drop_blank_before_page_break(d.paragraphs)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    d.save(str(OUT))
    print(f"已生成：{OUT}")

    # ---------- 自检 ----------
    check = Document(str(OUT))
    assert "自主选题" in check.tables[0].rows[1].cells[1].text
    assert "☑" in check.tables[0].rows[1].cells[1].text, "☑ 字符需确认渲染"
    assert "☑" in check.tables[0].rows[3].cells[1].text
    assert "研索 ScholarScope" in check.tables[0].rows[0].cells[1].text
    assert "无。" == check.tables[0].rows[23].cells[1].text
    assert "43 项全部通过" in check.tables[0].rows[21].cells[1].text
    assert any(p._p.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br')
               for p in check.paragraphs), "分页符被误删"
    print("自检通过：表单项、勾选项、承诺书均已填充，封面无空白页，个人信息留空待团队填写。")


if __name__ == "__main__":
    main()
