"""Section-directed evidence selection and bounded, verified generation."""
from __future__ import annotations

import re
import time
from workspace.intelligence import ResearchModel, evidence_sources
from workspace.store import normalized

RULES = [
    (r"方法|方案", {"method","population","innovation"},
     r"method|model|network|architecture|train|algorithm|CNN|LSTM|transformer|方法|模型|网络|训练",
     "Explain actual methods, their inputs/targets and comparison conditions; distinguish a proposed method from validated performance."),
    (r"数据|指标|评价|验证", {"dataset","sample_size","metrics"},
     r"dataset|sample|\bwells?\b|field|validat|test|R.?2|RMSE|MAE|accuracy|数据|样本|测试|评价|误差",
     "Describe reported datasets, sample sizes, metrics and validation conditions. Do not infer an unreported detail is absent from the paper."),
    (r"发现|结果", {"finding","metrics","question_answer"},
     r"result|achiev|outperform|improv|R.?2|RMSE|MAE|finding|结果|发现|误差|性能",
     "Report measured findings with their specific conditions. Never compare numbers from different datasets as a controlled comparison."),
    (r"局限|空白|风险|讨论|下一步", {"limitations","innovation"},
     r"limit|however|challenge|future|only|single|robust|noise|generaliz|局限|然而|噪声|泛化|不足",
     "Discuss explicit study limitations and material boundaries. Any next-step recommendation must be explicitly supported; project gaps are not field-wide gaps."),
    (r"贡献|创新", {"innovation","method"},
     r"propos|novel|introduc|contribut|develop|提出|创新|贡献|开发",
     "Describe the actual proposed contribution without asserting novelty or superiority beyond the evidence."),
    (r"背景|引言|相关研究|研究问题", {"population","method","finding"},
     r"predict|problem|important|challenge|research|study|预测|问题|研究",
     "Explain the task and why these supplied studies address the project question. Do not claim exhaustive coverage or invent field consensus."),
]


def section_sources(rows, section, *, limit=12):
    """Use text relevance as well as tags; keep distinct studies in context."""
    rule=next((r for r in RULES if re.search(r[0],section)),None)
    groups={};seen=set()
    ranked=[]
    for order,row in enumerate(rows):
        identity=row.get("paper_id") or row.get("title","")
        key=(identity,normalized(row["text"]))
        if key in seen:continue
        seen.add(key)
        field=(row.get("evidence") or {}).get("data",{}).get("field")
        score=(3 if rule and field in rule[1] else 0)+(2 if rule and re.search(rule[2],row["text"],re.I) else 0)
        ranked.append((score,row.get("scope")=="fulltext",-order,identity,row))
    ranked.sort(key=lambda r:r[:3],reverse=True)
    # Unknown/custom sections may use all valid sources. A wrong field label
    # cannot hide related original text from the entailment check.
    for _,_,_,identity,row in ranked:
        groups.setdefault(identity,[]).append(row)
    result=[]
    while groups and len(result)<limit:
        for key in list(groups):
            result.append(groups[key].pop(0))
            if not groups[key]:del groups[key]
            if len(result)>=limit:break
    return result


def generate_sections(store, pid, actor, candidates, sections, question, *, model=None, purpose="review", budget=110):
    """Generate each requested section under one budget, preserving omissions."""
    root=ResearchModel(model,budget=budget)
    rows=evidence_sources(store,pid,actor,candidates)
    selected={s:section_sources(rows,s) for s in sections}
    attempts=[];claims=[]
    if not root.model:
        return claims,{"status":root.status,"attempts":attempts,"missing_sections":list(sections)},selected
    groups=[sections[i:i+2] for i in range(0,len(sections),2)]

    def run(titles, allocation, retry=False):
        if root.deadline-time.monotonic()<2:return
        engine=ResearchModel(root.model,budget=min(allocation,root.deadline-time.monotonic()))
        # Interleave sections, then ResearchModel balances distinct studies and
        # removes repeated passages before applying its context budget.
        supplied=[]
        for i in range(6):
            for title in titles:
                if i<len(selected[title]):supplied.append(selected[title][i])
        guidance={title:next((r[3] for r in RULES if re.search(r[0],title)),
            "Answer this section using only relevant supplied evidence.") for title in titles}
        task=("Prepare presentation bullets" if purpose=="presentation" else "Write literature review paragraphs")
        task+=" in Chinese, organized by the exact requested sections. Return at least one distinct claim per section WHEN supported. "
        task+="A comparison may cite two studies. Organize reasoning rather than paste quotes. Omit unsupported sections; never invent missing results. "
        if retry:task+="Focus only on these still-missing sections, using narrow factual statements. "
        generated=engine.claims(task,supplied,context={"question":question,"sections":titles,"section_guidance":guidance},limit=4)
        accepted=[c for c in generated if c.get("section") in titles]
        claims.extend(accepted)
        attempts.append({"sections":titles,"status":engine.status,"accepted_sections":list(dict.fromkeys(c["section"] for c in accepted)),"retry":retry})

    for i,titles in enumerate(groups):
        remaining=root.deadline-time.monotonic()
        if remaining<2:break
        # Reserve time for every group and a targeted repair. A slow section
        # cannot consume the budget for all the other chapters.
        run(titles,min(35,remaining/(len(groups)-i+0.5)))
    missing=[s for s in sections if not any(c.get("section")==s for c in claims)]
    for i,section in enumerate(missing):
        remaining=root.deadline-time.monotonic()
        if remaining<5:break
        run([section],min(25,remaining/(len(missing)-i)),True)
    supported={c["section"] for c in claims}
    missing=[s for s in sections if s not in supported]
    status="verified_synthesis" if supported and not missing else "partial_verified_synthesis" if supported else attempts[-1]["status"] if attempts else "budget_exhausted"
    return claims,{"status":status,"attempts":attempts,"missing_sections":missing},selected
