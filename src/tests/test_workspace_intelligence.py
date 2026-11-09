"""Model contract tests: unsupported claims cannot cross into research outputs."""
import json
import pytest
from workspace.intelligence import ResearchModel
from workspace.store import WorkspaceStore, WorkspaceError
from workspace import research_tools, writing, presentations, review


class ContractModel:
    def chat(self,messages,**kwargs):
        prompt=messages[-1].content
        data=json.loads(prompt.split("DATA:\n",1)[1])
        if "Independently verify" in prompt:
            return json.dumps({"checks":[{"index":c["index"],"supported":True} for c in data["claims"]]})
        source=data["sources"][0]
        context=data.get("context") or {}
        section=(context.get("sections") or ["研究方法比较"])[0] if isinstance(context,dict) else "研究方法比较"
        if "presentation bullets" in prompt:section="方法比较"
        return json.dumps({"claims":[{"text":"该研究在测井资料上使用神经网络，评价范围限于一个油田。", "section":section,
            "field":"method","decision":"include","references":[{"id":source["id"],"quote":source["text"]}]}]},ensure_ascii=False)


def test_claim_gate_rejects_fake_sources_numbers_and_failed_review():
    class Bad:
        def chat(self,messages,**kwargs):
            if "Independently verify" in messages[-1].content:return '{"checks":[{"index":0,"supported":false}]}'
            return json.dumps({"claims":[
                {"text":"所有研究证明同一方法有效", "references":[{"id":"1","quote":"The dataset has 12 wells."}]},
                    {"text":"Unsupported causality", "references":[{"id":"1","quote":"The dataset has 12 wells."}]},
                {"text":"99 wells", "references":[{"id":"1","quote":"The dataset has 12 wells."}]},
                {"text":"invented", "references":[{"id":"2","quote":"The dataset has 12 wells."}]},
                    {"text":"invalid quote", "references":[{"id":"1","quote":"The dataset has 15 wells."}]}]})
    model=ResearchModel(Bad())
    assert model.claims("Analyze",[{"text":"The dataset has 12 wells."}])==[]
    assert model.status=="verification_failed"


def test_reference_ids_attach_original_passage_and_keep_study_identity():
    original='A neural network predicts porosity from well logs. Testing is limited to one field.'
    class IDModel:
        def chat(self,messages,**kwargs):
            data=json.loads(messages[-1].content.split('DATA:\n',1)[1])
            if 'Independently verify' in messages[-1].content:
                assert data['claims'][0]['quotes']==[original]
                return '{"checks":[{"index":0,"supported":true}]}'
            assert data['sources'][0]['study']==data['sources'][1]['study']
            return '{"claims":[{"text":"__STUDY_AA__用神经网络从测井曲线预测孔隙度。","references":[{"id":"1"}]}]}'
    engine=ResearchModel(IDModel())
    claims=engine.claims('Analyze',[{'text':original,'paper_id':'actual-paper','title':'Controlled well-log study'},
        {'text':'Testing is limited to one field.','paper_id':'actual-paper','title':'Controlled well-log study'}])
    assert claims[0]['references'][0]['quote']==original
    assert claims[0]['references'][0]['source']['paper_id']=='actual-paper'
    assert '《Controlled well-log study》' in claims[0]['text'] and '__STUDY_' not in claims[0]['text']


def test_study_markers_require_matching_evidence_and_preserve_scientific_abbreviations():
    class MarkerModel:
        def chat(self,messages,**kwargs):
            data=json.loads(messages[-1].content.split('DATA:\n',1)[1])
            if 'Independently verify' in messages[-1].content:
                assert len(data['claims'])==1
                assert data['claims'][0]['text']=='AA表示氨基酸。'
                return '{"checks":[{"index":0,"supported":true}]}'
            return json.dumps({'claims':[
                {'text':'__STUDY_AB__分析氨基酸。','references':[{'id':'1'}]},
                {'text':'__STUDY_ZZ__分析氨基酸。','references':[{'id':'1'}]},
                {'text':'AA表示氨基酸。','references':[{'id':'1'}]}]},ensure_ascii=False)
    engine=ResearchModel(MarkerModel())
    claims=engine.claims('Analyze',[
        {'text':'AA is an abbreviation for amino acids.','paper_id':'amino','title':'Amino acid study'},
        {'text':'A neural network predicts porosity from well logs.','paper_id':'logs','title':'Well-log study'}])
    assert [c['text'] for c in claims]==['AA表示氨基酸。']


def test_semantic_outputs_actual_quotes_exports_and_invalidation(tmp_path):
    store=WorkspaceStore("sqlite:///"+str(tmp_path/"research.db"))
    project=store.create_project("alice","Controlled AI synthesis",query="测井方法与评价范围")
    pid=project["id"]
    paper=store.add_paper(pid,"alice",{"title":"Controlled source", "abstract":"A neural network predicts porosity from well logs. Testing is limited to one field."})
    model=ContractModel()
    result=research_tools.extract_matrix(store,pid,"alice",model=model)
    assert result["rows"][0]["cells"]["method"]["extraction_mode"]=="verified_model"
    question=research_tools.answer_question(store,pid,"alice","well logs porosity",model=model)
    assert question["data"]["mode"].startswith("verified_synthesis")
    assert all(store.verify_evidence(pid,"alice",c["evidence_id"])["valid"] for c in question["data"]["citations"])
    manuscript=writing.generate_manuscript(store,pid,"alice",model=model)
    assert manuscript["data"]["generation_mode"]=="verified_model_synthesis"
    deck=presentations.generate_deck(store,pid,"alice",model=model)
    assert deck["data"]["generation_mode"]=="verified_model_synthesis" and len(deck["data"]["slides"])==12
    reviewed=review.save_review(store,pid,"alice",critical=True,model=model)
    assert any(f["kind"]=="supported_critical_analysis" for f in reviewed["data"]["findings"])
    research_tools.set_screening_criteria(store,pid,"alice",{"include":"神经网络测井预测","exclude":"无测井资料"},store.project(pid,"alice")["revision"])
    suggestions=research_tools.suggest_screening(store,pid,"alice",model=model)
    assert suggestions["data"]["suggestions"][0]["sources"]
    assert not store.items(pid,"alice","screening")
    store.set_member(pid,"alice","bob","viewer")
    with pytest.raises(WorkspaceError):research_tools.suggest_screening(store,pid,"bob",model=model)
    store.add_paper(pid,"alice",{**paper["data"],"abstract":"A corrected unrelated source."})
    assert store.item(pid,"alice",question["id"])["data"]["stale"]
    assert store.item(pid,"alice",manuscript["id"])["data"]["stale"]


def test_omission_and_prescriptive_claims_need_explicit_source_even_if_reviewer_accepts():
    class TooPermissive:
        def chat(self,messages,**kwargs):
            if 'Independently verify' in messages[-1].content:return '{"checks":[{"index":0,"supported":true}]}'
            return json.dumps({'claims':[{'text':'本研究未报告渗透率预测的结果。','references':[{'id':'1','quote':'Porosity prediction uses a neural network.'}]},
                {'text':'现有方法需通过损失函数改进。','references':[{'id':'1','quote':'Porosity prediction uses a neural network.'}]}]},ensure_ascii=False)
    engine=ResearchModel(TooPermissive())
    assert engine.claims('Analyze',[{'text':'Porosity prediction uses a neural network. Permeability RMSE was 0.07.'}])==[]
