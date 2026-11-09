"""Real adaptive retrieval coverage, isolated project, actual count preserved."""
import json,os,tempfile,time
from pathlib import Path
from workspace.store import WorkspaceStore
from workspace.deep_research import research
out=Path('.cache/search-coverage');out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='research-search-') as directory:
    os.environ['SCHOLARSCOPE_WORKSPACE_DIR']=directory
    s=WorkspaceStore('sqlite:///'+str(Path(directory)/'db'))
    query='近三年（2024–2026）基于测井曲线预测孔隙度、渗透率的深度学习方法，目标 30 篇；deep learning well logs porosity permeability prediction'
    p=s.create_project('coverage-check','真实测井检索覆盖验收',query=query);started=time.monotonic()
    r=research(s,p['id'],'coverage-check',query,limit=30,year_from=2024,year_to=2026)
    result={**r['data'],'seconds':round(time.monotonic()-started,1),'papers':[{'title':p['label'],'doi':p['data'].get('doi'),'year':p['data'].get('year'),'authors':p['data'].get('authors'),
        'venue':p['data'].get('venue'),'url':p['data'].get('url'),'abstract':p['data'].get('abstract'),'reason':p['data'].get('recommendation_reason'),'scope_notes':p['data'].get('scope_notes')} for p in s.items(p['id'],'coverage-check','paper')]}
    (out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:result[k] for k in ('message','rounds','actual_count','seconds')},ensure_ascii=False,indent=2))
