"""Date filters use supported SDK fields and upstream API constraints."""
from agent.spar2 import retrievers


def test_arxiv_date_is_query_not_invalid_sdk_argument(monkeypatch):
    captured=[]
    class Client:
        def __init__(self,**kwargs):pass
    monkeypatch.setattr(retrievers._arxiv,"Client",Client)
    def results(client,kwargs,timeout):
        # Real installed SDK rejects unsupported constructor arguments.
        retrievers._arxiv.Search(**kwargs)
        captured.append(kwargs["query"])
        return []
    monkeypatch.setattr(retrievers,"_arxiv_results_with_timeout",results)
    retrievers.search_arxiv(["well logs"],["porosity prediction"],start_year=2024,end_date="20261231")
    assert captured and all("submittedDate:[202401010000 TO 202612312359]" in q for q in captured)
    assert 'all:"porosity" AND all:"prediction"' in captured[0]
    captured.clear()
    retrievers.search_arxiv(["well logs"],start_year=2024)
    assert captured and "submittedDate:[202401010000 TO" in captured[0]


def test_crossref_date_filters_and_bounded_requests(monkeypatch):
    captured=[]
    class Response:
        status_code=200
        def json(self):return {"message":{"items":[]}}
    def get(url,**kwargs):
        captured.append(kwargs)
        return Response()
    monkeypatch.setattr(retrievers._REQ_SESSION,"get",get)
    retrievers.search_crossref(["well logs"],start_year=2024,end_date="2026")
    assert captured[0]["params"]["filter"]=="from-pub-date:2024-01-01,until-pub-date:2026-12-31"
    assert captured[0]["timeout"]<=12
