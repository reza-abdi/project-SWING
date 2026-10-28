"""Citation provenance must survive retrieval or fail closed."""

from types import SimpleNamespace

import pytest

from modules.ai_agents.agent_core import (
    RAGUnavailableError,
    retrieve_compliance_context,
    safe_compliance_lookup,
)


class Retriever:
    def __init__(self, documents):
        self.documents = documents
        self.request = None

    def similarity_search(self, query, k):
        self.request = (query, k)
        return self.documents


def test_three_excerpts_keep_stable_page_citations_and_text_order() -> None:
    docs = [
        SimpleNamespace(page_content=f"rule {index}", metadata={"source": "IEGC_Code.pdf", "page": index})
        for index in range(3)
    ]
    retriever = Retriever(docs)
    result = retrieve_compliance_context("security", retriever)
    assert retriever.request == ("security", 3)
    assert result.verified is True
    assert [citation.page for citation in result.citations] == [1, 2, 3]
    assert result.text.index("rule 0") < result.text.index("rule 1") < result.text.index("rule 2")
    assert "[IEGC_Code.pdf, page 2]" in result.text


@pytest.mark.parametrize(
    "metadata",
    [{}, {"source": "other.pdf", "page": 1}, {"source": "IEGC_Code.pdf", "page": "3"}],
)
def test_invalid_provenance_is_not_reported_as_verified(metadata) -> None:
    store = Retriever([SimpleNamespace(page_content="unproven text", metadata=metadata)])
    with pytest.raises(RAGUnavailableError, match="metadata"):
        retrieve_compliance_context("security", store)
    result = safe_compliance_lookup("security", store)
    assert result["status"] == "RAG_UNAVAILABLE"
    assert result["citations"] == []
    assert result["decision_allowed"] is False


def test_retrieval_exception_cannot_claim_verified_citations() -> None:
    class BrokenRetriever:
        def similarity_search(self, *_args, **_kwargs):
            raise RuntimeError("index failure")

    result = safe_compliance_lookup("security", BrokenRetriever())
    assert result["status"] == "RAG_UNAVAILABLE"
    assert result["actuation_allowed"] is False
