"""Coverage is driven by original material, not matrix tag completeness."""
import json
import copy
import pytest
from workspace.store import WorkspaceStore
from workspace.store import WorkspaceError
from workspace import writing,presentations
from workspace.intelligence import ResearchModel


class SectionModel:
    def chat(self,messages,**kwargs):
        prompt=messages[-1].content
        data=json.loads(prompt.split('DATA:\n',1)[1])
        if 'Independently verify' in prompt:
            return json.dumps({'checks':[{'index':c['index'],'supported':True} for c in data['claims']]})
        claims=[]
        for section in data['context']['sections']:
            if section in ('研究贡献','局限性与研究空白','局限性与边界','讨论与下一步'):
                continue
            terms='samples' if any(t in section for t in ('数据','评价')) else 'RMSE' if any(t in section for t in ('发现','结果')) else 'network'
            source=next(s for s in data['sources'] if terms in s['text'])
            refs=[{'id':source['id']}]
            text='该研究使用神经网络预测孔隙度。' if terms=='network' else '数据包含120个样本。' if terms=='samples' else '该研究报告RMSE为0.08。'
            if section=='方法比较':
                other=next(s for s in data['sources'] if s['study']!=source['study'])
                refs.append({'id':other['id']});text='两项研究均使用神经网络预测孔隙度。'
            claims.append({'text':text,'section':section,'references':refs})
        return json.dumps({'claims':claims},ensure_ascii=False)


def setup_project(tmp_path):
    store=WorkspaceStore('sqlite:///'+str(tmp_path/'synthesis.db'))
    p=store.create_project('alice','Neural porosity',query='比较测井预测模型、数据和结果')
    for n in range(2):
        abstract='The study uses a neural network to predict porosity from well logs. The dataset has 120 samples. Results report RMSE of 0.08.'
        paper=store.add_paper(p['id'],'alice',{'title':f'Controlled well-log study {n}','doi':f'10.1000/sections-{n}','abstract':abstract})
        # All passages have an unrecognized/custom tag. Their real content must
        # still be available to dataset/finding/method synthesis.
        store.add_evidence(p['id'],'alice',{'paper_id':paper['id'],'quote':abstract,'field':'custom_note'})
    return store,p['id']


def test_custom_tags_do_not_hide_dataset_results_or_other_studies(tmp_path):
    store,pid=setup_project(tmp_path)
    result=writing.generate_manuscript(store,pid,'alice',model=SectionModel())
    coverage=result['data']['generation_coverage']
    assert {'研究方法比较','数据与评价指标','主要发现'}<=set(coverage['supported_sections'])
    assert '局限性与研究空白' in coverage['missing_sections']
    assert coverage['section_modes']['局限性与研究空白']=='source_text'
    assert set(coverage['reused_sections'])=={'摘要','结论'}
    assert all(c['valid'] for c in result['citations'])
    assert len({c['paper_id'] for c in result['citations']})==2
    assert '未报告' not in writing.plain_text(result['data']['content'])


def test_comparative_slide_retains_both_sources_through_export_edit_and_invalidation(tmp_path):
    import io,re,zipfile
    store,pid=setup_project(tmp_path)
    deck=presentations.generate_deck(store,pid,'alice',model=SectionModel())
    comparison=next(s for s in deck['data']['slides'] if s['title']=='方法比较')
    assert len(comparison['bullets'][0]['evidence_refs'])==2
    assert len({c['paper_id'] for c in comparison['citations']})==2
    assert set(r['evidence_id'] for r in comparison['bullets'][0]['evidence_refs'])<=set(deck['data']['evidence_ids'])
    blob,_=presentations.export_deck(store,pid,'alice',deck['id'],'pptx')
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        slide=z.read('ppt/slides/slide10.xml').decode()
        assert '[1]' in slide and '[2]' in slide
        notes=''.join(z.read(n).decode() for n in z.namelist() if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n))
        assert 'Controlled well-log study 0' in notes and 'Controlled well-log study 1' in notes
    saved=presentations.save_deck(store,pid,'alice',deck['data'],deck['id'],deck['revision'])
    secondary=comparison['bullets'][0]['evidence_refs'][1]['evidence_id']
    e=store.item(pid,'alice',secondary,'evidence')
    store.add_evidence(pid,'alice',{**e['data'],'confirmed':True},e['id'],e['revision'])
    updated=presentations.deck_view(store,pid,'alice',store.item(pid,'alice',saved['id'],'presentation'))
    assert updated['data']['stale'] and updated['validation']['invalid_citations']


def test_duplicate_passages_cannot_starve_the_second_study():
    paragraph='A neural network predicts porosity from well logs. '*25
    class BalanceModel:
        def chat(self,messages,**kwargs):
            data=json.loads(messages[-1].content.split('DATA:\n',1)[1])
            if 'Independently verify' in messages[-1].content:return '{"checks":[{"index":0,"supported":true}]}'
            assert len(data['sources'])==2 and len(data['studies'])==2
            return '{"claims":[{"text":"两项研究使用神经网络预测孔隙度。","references":[{"id":"1"},{"id":"2"}]}]}'
    rows=[{'text':paragraph,'paper_id':'first','title':'First study'} for _ in range(20)]
    rows.append({'text':paragraph,'paper_id':'second','title':'Second study'})
    claims=ResearchModel(BalanceModel()).claims('Compare studies',rows)
    assert {r['source']['paper_id'] for r in claims[0]['references']}=={'first','second'}


def test_all_slide_sources_are_project_scoped_and_one_stale_use_cannot_be_masked(tmp_path):
    store,pid=setup_project(tmp_path)
    evidence=store.items(pid,'alice','evidence')[0]
    def ref(source_hash):
        return {'evidence_id':evidence['id'],'source_hash':source_hash,'evidence_revision':evidence['revision']}
    slides=[{'title':'Earlier use','bullets':[{'text':'Earlier claim','evidence_refs':[ref('old-hash')]}]},
        {'title':'Later use','bullets':[{'text':'Later claim','evidence_refs':[ref(evidence['data']['source_hash'])]}]}]
    deck=presentations.save_deck(store,pid,'alice',{'title':'Mixed versions','slides':slides})
    assert deck['data']['stale'] and deck['validation']['invalid_citations']==1
    foreign=copy.deepcopy(slides)
    foreign[0]['bullets'][0]['evidence_refs'].append({'evidence_id':'foreign'})
    with pytest.raises(WorkspaceError):presentations.save_deck(store,pid,'alice',{'title':'Foreign secondary source','slides':foreign})
