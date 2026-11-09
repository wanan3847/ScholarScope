"""Shared SPAR2 recall respects intent before finite budgets are consumed."""
from concurrent.futures import TimeoutError
from agent.spar2 import engine as module
from agent.research_intent import matches,year_bounds


def stub_sources(monkeypatch):
    for name in ('search_arxiv','search_openalex','search_local','search_crossref','search_semantic_scholar','search_europe_pmc','search_scopus'):
        monkeypatch.setattr(module.retrievers,name,lambda *a,**k:[])
    monkeypatch.setattr(module.query_planner,'plan_query',lambda *a,**k:{'keywords':['well logs'],'queries':['well logs deep learning porosity']})
    monkeypatch.setattr(module.query_planner,'generate_queries_from_docs',lambda *a,**k:['well logging LSTM porosity'])
    monkeypatch.setattr(module.retrievers,'semantic_scores',lambda q,texts:[0.0]*len(texts))
    monkeypatch.setattr(module,'_enrich_abstracts',lambda docs:None)
    monkeypatch.setattr(module.expand_mod,'expand_citations',lambda *a,**k:[])


def test_later_round_has_its_own_wait_window(monkeypatch):
    stub_sources(monkeypatch)
    actual_time=module.time.time;offset=[0.0];waits=[];rounds=[0]
    monkeypatch.setattr(module.time,'time',lambda:actual_time()+offset[0])
    def followup(*args,**kwargs):
        offset[0]+=35
        return ['well logging LSTM porosity']
    monkeypatch.setattr(module.query_planner,'generate_queries_from_docs',followup)
    class Future:
        def __init__(self,fn,args,kwargs):self.fn=fn;self.args=args;self.kwargs=kwargs
        def result(self,timeout=None):
            waits.append(timeout)
            if timeout is not None and timeout<=0:raise TimeoutError()
            return self.fn(*self.args,**self.kwargs)
    class Pool:
        def __init__(self,**kwargs):pass
        def submit(self,fn,*args,**kwargs):return Future(fn,args,kwargs)
        def shutdown(self,**kwargs):pass
    monkeypatch.setattr(module,'ThreadPoolExecutor',Pool)
    def retrieve(*args,**kwargs):
        rounds[0]+=1
        return [{'title':f'LSTM well logs porosity prediction study {rounds[0]}','doi':f'10.1000/round-{rounds[0]}','year':'2025','abstract':'A neural network predicts porosity from well logs.'}]
    def judge(q,docs,*args,**kwargs):
        offset[0]+=50
        return [0.9]*len(docs)
    monkeypatch.setattr(module.retrievers,'search_openalex',retrieve)
    monkeypatch.setattr(module.judge_mod,'judge_docs',judge)
    result=module.SPAR2Engine(llm_chat=lambda *a,**k:'{}',deadline_seconds=180,max_rounds=2,max_output=30).run('测井深度学习孔隙度预测')
    assert {p['doi'] for p in result['papers']}=={'10.1000/round-1','10.1000/round-2'}
    assert len(waits)==10 and all(t>0 for t in waits[7:])


def test_unrelated_candidates_do_not_consume_the_judge_and_output_limit(monkeypatch):
    stub_sources(monkeypatch)
    unrelated=[{'title':f'Highly ranked seismic transformer porosity {i}','doi':f'10.1000/no-{i}',
        'abstract':'Porosity prediction from seismic data.','year':'2025'} for i in range(80)]
    direct={'title':'LSTM well logging porosity prediction','doi':'10.1000/direct','year':'2025','abstract':'A neural network predicts porosity from well logs.'}
    monkeypatch.setattr(module.retrievers,'search_openalex',lambda *a,**k:unrelated+[direct])
    judged=[]
    def judge(query,docs,*args,**kwargs):
        judged.extend(d['doi'] for d in docs)
        assert query=='测井深度学习孔隙度预测'
        return [0.9]*len(docs)
    monkeypatch.setattr(module.judge_mod,'judge_docs',judge)
    e=module.SPAR2Engine(llm_chat=lambda *a,**k:'{}',deadline_seconds=5,max_rounds=1,max_judge=2,max_output=1)
    e.research_query='测井深度学习孔隙度预测'
    result=e.run('LSTM porosity')
    assert judged==['10.1000/direct'] and [p['doi'] for p in result['papers']]==['10.1000/direct']


def test_single_target_graph_architecture_and_explicit_period():
    assert matches('测井深度学习孔隙度预测',{'title':'Graph neural network borehole logs porosity prediction'})
    assert not matches('测井深度学习渗透率预测',{'title':'LSTM well logs porosity prediction'})
    assert year_bounds('2024–2026 测井深度学习')==(2024,2026)
    assert year_bounds('compare a 2010 dataset and a 2025 dataset')==(0,0)
