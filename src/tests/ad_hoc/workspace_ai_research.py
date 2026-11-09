"""Real local model + real Crossref abstracts, isolated from user projects."""
import json
import os
import tempfile
import time
from pathlib import Path
from workspace.store import WorkspaceStore
from workspace.sources import lookup_doi
from workspace import research_tools, writing, presentations, review

model_name=os.getenv("SCHOLARSCOPE_EVAL_MODEL","qwen3.5:4b")
from llm.router import ModelEndpoint,_RoutedLLM
evaluation_model=_RoutedLLM(ModelEndpoint(name="isolated-research-check",model=model_name,base_url="http://127.0.0.1:11434/v1"))
out=Path(__file__).resolve().parents[3]/".cache"/os.getenv("SCHOLARSCOPE_EVAL_OUTPUT","ai-research")
out.mkdir(parents=True,exist_ok=True)
from workspace.intelligence import ResearchModel
original_request=ResearchModel.request
def traced_request(self,task,data,**kwargs):
    result=original_request(self,task,data,**kwargs)
    trace=out/"model-trace.jsonl"
    with trace.open("a") as stream:stream.write(json.dumps({"task":task[:180],"response":result,"status":self.status},ensure_ascii=False)+"\n")
    return result
ResearchModel.request=traced_request
report={"date":"2026-10-14","source":"real Crossref abstracts","model":"local Ollama "+model_name,"stages":{}}
def checkpoint(stage):
    (out/"progress.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"stage":stage,**{k:v for k,v in report["stages"][stage].items() if k not in ("text","citations")}},ensure_ascii=False),flush=True)
with tempfile.TemporaryDirectory(prefix="research-ai-") as directory:
    store=WorkspaceStore("sqlite:///"+str(Path(directory)/"research.db"))
    p=store.create_project("real-source-check","测井曲线孔渗预测：真实模型验收",query="测井曲线深度学习孔隙度与渗透率预测的方法、评价条件及局限性")
    pid=p["id"]
    for doi in ("10.21203/rs.3.rs-8698402/v1","10.2118/235037-ms"):
        store.add_paper(pid,"real-source-check",lookup_doi(doi))
    report["papers"]=[r["data"] for r in store.items(pid,"real-source-check","paper")]
    started=time.monotonic();matrix=research_tools.extract_matrix(store,pid,"real-source-check",model=evaluation_model)
    (out/"matrix.json").write_text(json.dumps(matrix,ensure_ascii=False,indent=2))
    report["stages"]["matrix"]={"seconds":round(time.monotonic()-started,1),"model_cells":sum(c["extraction_mode"]=="verified_model" for r in matrix["rows"] for c in r["cells"].values())}
    checkpoint("matrix")
    started=time.monotonic();answer=research_tools.answer_question(store,pid,"real-source-check","well logs porosity permeability deep learning validation limitations",model=evaluation_model)
    report["stages"]["answer"]={"seconds":round(time.monotonic()-started,1),"status":answer["data"].get("generation_status"),"mode":answer["data"]["mode"],"text":answer["data"]["answer"],"citations":answer["data"]["citations"]}
    checkpoint("answer")
    started=time.monotonic();manuscript=writing.generate_manuscript(store,pid,"real-source-check",model=evaluation_model)
    report["stages"]["manuscript"]={"seconds":round(time.monotonic()-started,1),"mode":manuscript["data"]["generation_mode"],"coverage":manuscript["data"].get("generation_coverage")}
    (out/"manuscript.json").write_text(json.dumps(manuscript,ensure_ascii=False,indent=2))
    checkpoint("manuscript")
    for fmt in ("docx","pdf","md"):
        blob,_=writing.export_manuscript(store,pid,"real-source-check",manuscript["id"],fmt);(out/("review."+fmt)).write_bytes(blob)
    started=time.monotonic();deck=presentations.generate_deck(store,pid,"real-source-check",model=evaluation_model)
    report["stages"]["presentation"]={"seconds":round(time.monotonic()-started,1),"mode":deck["data"]["generation_mode"],"slides":len(deck["data"]["slides"]),"coverage":deck["data"].get("generation_coverage")}
    (out/"presentation.json").write_text(json.dumps(deck,ensure_ascii=False,indent=2))
    checkpoint("presentation")
    blob,_=presentations.export_deck(store,pid,"real-source-check",deck["id"],"pptx");(out/"presentation.pptx").write_bytes(blob)
    report["evidence"]=review.inspect_project(store,pid,"real-source-check")["checks"]
    report["all_sources_valid"]=all(e["valid"] for e in report["evidence"])
    report["semantic_quality_boundary"]="引用与原文匹配只证明来源完整性，语义效果仍需独立人工评测。"
    review_text=(out/"review.md").read_text()
    assert "未提供渗透率" not in review_text and "未报告渗透率" not in review_text, "Unsupported absence inference survived"
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"all_sources_valid":report["all_sources_valid"],"stages":{k:{a:b for a,b in v.items() if a not in ("text","citations")} for k,v in report["stages"].items()}},ensure_ascii=False,indent=2))
