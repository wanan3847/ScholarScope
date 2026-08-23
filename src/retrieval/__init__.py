"""统一检索后端包。"""

from retrieval.base import BaseRetrieval, RawPaper
from retrieval.semantic_scholar import SemanticScholarBackend
from retrieval.openalex import OpenAlexBackend
from retrieval.pubmed import PubMedBackend
from retrieval.arxiv import ArxivBackend
from retrieval.crossref import CrossRefBackend
from retrieval.local_corpus import LocalCorpusBackend

_BACKEND_REGISTRY = {
    "semantic_scholar": SemanticScholarBackend,
    "openalex": OpenAlexBackend,
    "pubmed": PubMedBackend,
    "arxiv": ArxivBackend,
    "crossref": CrossRefBackend,
    "local_corpus": LocalCorpusBackend,
}


def get_retrieval_backend(name: str, use_mock: bool = True) -> BaseRetrieval:
    """
    工厂方法：按名称获取检索后端实例。

    Args:
        name: 后端名称，必须在 _BACKEND_REGISTRY 中。
        use_mock: True 则使用内置 mock 数据，False 则发起真实网络请求。

    Returns:
        BaseRetrieval 子类实例。
    """
    if name not in _BACKEND_REGISTRY:
        raise ValueError(
            f"未知检索后端：{name}，可选：{list(_BACKEND_REGISTRY.keys())}"
        )
    return _BACKEND_REGISTRY[name](use_mock=use_mock)


__all__ = [
    "BaseRetrieval",
    "RawPaper",
    "SemanticScholarBackend",
    "OpenAlexBackend",
    "PubMedBackend",
    "ArxivBackend",
    "CrossRefBackend",
    "LocalCorpusBackend",
    "get_retrieval_backend",
]
