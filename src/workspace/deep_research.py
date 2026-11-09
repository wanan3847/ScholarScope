"""Focused follow-up searches and actual public full-text acquisition."""
import time
from workspace.store import WorkspaceError
from workspace.documents import ObjectStore
from workspace.intelligence import ResearchModel
from workspace import sources
from agent.research_intent import matches,scope_notes,year_bounds
from agent.spar2.query_planner import focused_research_queries


def acquire(store, pid, actor, *, paper_ids=None, budget=135):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with store.engine.connect() as conn: store._access(conn,pid,actor,edit=True)
    deadline=time.monotonic()+budget
    existing={d["data"]["paper_id"] for d in store.items(pid,actor,"document")}
    papers=[p for p in store.items(pid,actor,"paper") if not paper_ids or p["id"] in paper_ids][:100]
    def one(paper):
        row={"paper_id":paper["id"],"status":"no_open_link","attempts":0}
        if paper["id"] in existing:return {**row,"status":"already_available"}
        # Budget covers provider lookup, transport and isolated PDF/OCR parsing.
        if deadline-time.monotonic()<125:return {**row,"status":"budget_exhausted"}
        available=sources.oa_links(store,pid,actor,paper["id"])
        for link in available["links"][:1]:
            row["attempts"]+=1
            try:
                document=sources.attach_remote_pdf(store,ObjectStore(),pid,actor,paper["id"],link["url"])
                row.update(status="downloaded",document_id=document["id"],pages=document["data"]["page_count"])
            except WorkspaceError:row["status"]="download_failed"
        return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(one,p):p for p in papers}
        records=[]
        for f in as_completed(futures):
            try:records.append(f.result())
            except Exception:records.append({"paper_id":futures[f]["id"],"status":"download_failed"})
    return {"records":records,"downloaded":sum(r["status"]=="downloaded" for r in records),
        "message":"仅获取数据库报告的公开全文；失败、许可限制及未获全文逐篇保留，可继续获取。"}


def research(store,pid,actor,query,*,limit=30,year_from=0,year_to=0,budget=210):
    with store.engine.connect() as conn:store._access(conn,pid,actor,edit=True)
    from agent.orchestrator import Orchestrator
    from web.app import _get_llm_router
    deadline=time.monotonic()+budget
    year_from,year_to=year_bounds(query,year_from,year_to)
    intelligence=ResearchModel(budget=min(10,max(0,budget/12)))
    plan=intelligence.request('Plan focused academic searches. Return {"queries":[up to 6 queries],'
        '"facets":[method/data/evaluation questions],"rationale":"Chinese explanation"}. '
        'Preserve original method, population and task; vary synonyms rather than scope.',
        {"question":query,"years":[year_from,year_to]},tokens=900)
    variants=[q for q in plan.get("queries",[]) if isinstance(q,str) and 3<=len(q)<=240] if isinstance(plan.get("queries"),list) else []
    fallback=focused_research_queries(query)
    # Deterministic task variants remain reachable even if a model supplies
    # repeated broad phrases. Alternate them with the model's proposals.
    proposed=[]
    for i in range(max(len(fallback),len(variants))):
        if i<len(fallback):proposed.append(fallback[i])
        if i<len(variants):proposed.append(variants[i])
    queries=list(dict.fromkeys([query]+proposed))[:8]
    row=store.put(pid,actor,"search_report",query,{"query":query,"requested_count":limit,"actual_count":0,
        "paper_ids":[],"rounds":[],"plan":plan,"year_from":year_from,"year_to":year_to,"message":"正在按研究问题收集资料"})
    paper_ids,rounds=[],[]
    index=0
    while index<len(queries):
        q=queries[index];remaining=deadline-time.monotonic()
        if remaining<25 or len(paper_ids)>=limit:break
        round_budget=min(55,remaining-5,max(30,(remaining-5)/min(5,len(queries)-index)))
        engine=Orchestrator(llm_chat=_get_llm_router().get(),max_output=50,practical_limit=50,
            deadline_seconds=max(15,round_budget-10),overall_budget_seconds=round_budget,max_rounds=1,
            llm_timeout_seconds=min(12,round_budget/3),max_judge=80,local_top_k=300,year_from=year_from,
            research_query=query)
        result=engine.sync_run(q,str(year_to)+"1231" if year_to else "")
        added=0;rejected=0;duplicates=0
        for paper in result.get("papers",[]):
            try:year=int(paper.get("year") or 0)
            except (ValueError,TypeError):year=0
            if (year_from or year_to) and (not year or year_from and year<year_from or year_to and year>year_to):rejected+=1;continue
            if not matches(query,paper):rejected+=1;continue
            paper["scope_notes"]=scope_notes(query,paper)
            item=store.add_paper(pid,actor,paper)
            if item["id"] not in paper_ids:paper_ids.append(item["id"]);added+=1
            else:duplicates+=1
            if len(paper_ids)>=limit:break
        rounds.append({"query":q,"new_count":added,"returned_count":len(result.get("papers",[])),
            "mode":result.get("stats",{}).get("ranking_mode"),"purpose":"initial" if index==0 else "coverage_followup",
            "rejected_count":rejected,"duplicate_count":duplicates,"budget_seconds":round(round_budget,1)})
        row=store.put(pid,actor,"search_report",query,{**row["data"],"paper_ids":paper_ids,"actual_count":len(paper_ids),"rounds":rounds},row["id"],row["revision"])
        if index==0 and len(paper_ids)<limit and intelligence.model and deadline-time.monotonic()>45:
            reflection=ResearchModel(budget=10).request('Identify a missing research facet and propose ONE follow-up '
                'query preserving original constraints. Return {"query":"...","gap":"..."}.',
                {"question":query,"titles":[p["label"] for p in store.items(pid,actor,"paper") if p["id"] in paper_ids]},tokens=500)
            follow=reflection.get("query")
            if isinstance(follow,str) and 3<=len(follow)<=240 and follow not in queries:queries.insert(3,follow);queries=queries[:8]
            row=store.put(pid,actor,"search_report",query,{**row["data"],"reflection":reflection},row["id"],row["revision"])
        index+=1
    message=f"按原始研究条件保存 {len(paper_ids)} 篇真实文献，执行 {len(rounds)} 轮检索。"
    if len(paper_ids)<limit:message+="实际结果不足目标，未放宽条件或补造论文。"
    stop_reason="target_met" if len(paper_ids)>=limit else "budget_exhausted" if deadline-time.monotonic()<25 else "queries_exhausted"
    return store.put(pid,actor,"search_report",query,{**row["data"],"message":message,"complete":True,
        "target_met":len(paper_ids)>=limit,"stop_reason":stop_reason},row["id"],row["revision"])
