"""Adaptive search stays eligible, persists rounds, and does not invent PDFs."""
import pytest
from workspace.store import WorkspaceStore,WorkspaceError
from workspace import deep_research,skills
from agent.spar2.query_planner import extract_keywords_fallback


def test_followup_search_years_constraints_dedup_and_plan(tmp_path,monkeypatch):
    s=WorkspaceStore("sqlite:///"+str(tmp_path/"db"));p=s.create_project("alice","Well logs")
    calls=[]
    class Engine:
        def __init__(self,**kwargs):pass
        def sync_run(self,query,before):
            calls.append(query)
            return {"papers":[{"title":"Deep learning well logs porosity prediction", "doi":"10.1000/deep", "year":2025,
                "abstract":"A convolutional neural network predicts porosity from well logs."},
                {"title":"Random forest well logs", "doi":"10.1000/wrong", "year":2025},
                {"title":"Deep learning well logs porosity", "doi":"10.1000/old", "year":2010}],"stats":{}}
    monkeypatch.setattr("agent.orchestrator.Orchestrator",Engine)
    r=deep_research.research(s,p["id"],"alice","近三年测井深度学习预测孔隙度",limit=30)
    assert r["data"]["actual_count"]==1 and 4<len(calls)<=8 and r["data"]["year_from"]==2024
    assert r["data"]["complete"] and all(x["new_count"]==0 for x in r["data"]["rounds"][1:])
    assert len(s.items(p["id"],"alice","paper"))==1
    assert not r["data"]["target_met"] and r["data"]["stop_reason"]=="queries_exhausted"
    planned=skills.plan(s,p["id"],"alice",{"search":True,"deep":True,"query":"測井"})
    assert [step["tool"] for step in planned[:2]]==["research","acquire"]
    assert planned[0]["budget_seconds"]>=210
    assert any("well logs" in q for q in extract_keywords_fallback("测井深度学习孔隙度预测")["queries"])
    with pytest.raises(WorkspaceError):deep_research.research(s,p["id"],"bob","private")


def test_no_open_links_keeps_actual_empty_report(tmp_path,monkeypatch):
    s=WorkspaceStore("sqlite:///"+str(tmp_path/"db"));p=s.create_project("alice","Sources")
    paper=s.add_paper(p["id"],"alice",{"title":"Controlled unavailable full text"})
    monkeypatch.setattr(deep_research.sources,"oa_links",lambda *a:{"links":[]})
    r=deep_research.acquire(s,p["id"],"alice")
    assert r["downloaded"]==0 and r["records"][0]["status"]=="no_open_link"
    assert not s.items(p["id"],"alice","document")


def test_architecture_followup_finds_new_study_without_relaxing_original_task(tmp_path,monkeypatch):
    s=WorkspaceStore("sqlite:///"+str(tmp_path/"db"));p=s.create_project("alice","Well logs")
    calls=[];settings=[]
    query="2024–2026 测井深度学习孔隙度预测"
    class Engine:
        def __init__(self,**kwargs):settings.append(kwargs)
        def sync_run(self,q,before):
            calls.append(q)
            if "LSTM" not in q:return {"papers":[],"stats":{}}
            return {"papers":[{"title":"LSTM well logging porosity prediction","doi":"10.1000/lstm","year":2025},
                {"title":"LSTM seismic porosity prediction","doi":"10.1000/seismic","year":2025},
                {"title":"LSTM well logging permeability prediction","doi":"10.1000/other-target","year":2025}]}
    monkeypatch.setattr("agent.orchestrator.Orchestrator",Engine)
    result=deep_research.research(s,p["id"],"alice",query,limit=1,year_from=2024,year_to=2026)
    assert result["data"]["target_met"] and result["data"]["stop_reason"]=="target_met"
    assert s.items(p["id"],"alice","paper")[0]["data"]["doi"]=="10.1000/lstm"
    assert any("LSTM" in q for q in calls)
    assert all(k["research_query"]==query and k["overall_budget_seconds"]<=55 for k in settings)
