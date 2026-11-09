"""Local inference has bounded contexts and per-call timeouts, including Docker."""
from llm.router import ModelEndpoint,_RoutedLLM


def test_native_ollama_schema_context_vision_timeout(monkeypatch):
    import llm.router as router
    captured={}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'message':{'content':'{"ok":true}'},'eval_count':4}
    class Client:
        def __init__(self,**kwargs):captured['timeout']=kwargs['timeout']
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):captured['payload']=kwargs['json'];return Response()
    monkeypatch.setattr(router.httpx,'Client',Client)
    model=_RoutedLLM(ModelEndpoint(name='local',model='local-model',base_url='http://host.docker.internal:11434/v1'))
    assert model._is_ollama()
    schema={'type':'object','properties':{'ok':{'type':'boolean'}}}
    assert model.chat_vision('Read actual image','controlled-base64',max_tokens=200,structured_json=True,json_schema=schema,timeout_seconds=12)
    assert 11 < captured['timeout'] <= 12 and model.timeout==30
    assert captured['payload']['options']['num_ctx']==8192
    assert captured['payload']['format']==schema
    assert captured['payload']['messages'][-1]['images']==['controlled-base64']
    assert captured['payload']['keep_alive']=='90s'


def test_research_context_bound_and_per_request(monkeypatch):
    from workspace.intelligence import ResearchModel,research_context_size
    captured={}
    class Model:
        def chat(self,messages,**kwargs):captured.update(kwargs);return '{"ok":true}'
    monkeypatch.delenv('SCHOLARSCOPE_RESEARCH_CONTEXT',raising=False)
    assert ResearchModel(Model()).request('Read sources',{})=={'ok':True}
    assert captured['num_ctx']==8192
    monkeypatch.setenv('SCHOLARSCOPE_RESEARCH_CONTEXT','262144')
    assert research_context_size()==32768
    monkeypatch.setenv('SCHOLARSCOPE_RESEARCH_CONTEXT','invalid')
    assert research_context_size()==8192


def test_local_inference_queue_counts_against_timeout(monkeypatch):
    import llm.ollama_transport as transport
    import pytest
    class Occupied:
        def acquire(self,timeout):return False
        def release(self):raise AssertionError('Unacquired gate released')
    monkeypatch.setattr(transport,'_gate',Occupied())
    with pytest.raises(TimeoutError):transport.chat_response('http://localhost:11434/api/chat',{}, {},1)
