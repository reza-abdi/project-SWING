"""Grounded compliance retrieval primitives for the separate AI service."""

from __future__ import annotations

from dataclasses import dataclass


class RAGUnavailableError(RuntimeError):
    """The regulatory source cannot currently provide verified context."""


@dataclass(frozen=True)
class RetrievedCitation:
    source: str
    page: int


@dataclass(frozen=True)
class ComplianceContext:
    text: str
    citations: tuple[RetrievedCitation, ...]
    verified: bool


def retrieve_compliance_context(
    question: str,
    vector_store,
    *,
    top_k: int = 3,
    max_chunk_chars: int = 1800,
    max_context_chars: int = 5000,
) -> ComplianceContext:
    """Retrieve bounded IEGC excerpts with a page citation for every chunk."""
    if not question.strip():
        raise ValueError("compliance question must not be empty")
    if top_k != 3 or max_chunk_chars < 1 or max_context_chars < 1:
        raise ValueError("retrieval limits are invalid")
    if vector_store is None:
        raise RAGUnavailableError("regulatory vector index is unavailable")
    try:
        documents = vector_store.similarity_search(question, k=top_k)
    except Exception as exc:
        raise RAGUnavailableError("regulatory retrieval failed") from exc
    if not documents:
        raise RAGUnavailableError("no regulatory excerpts were retrieved")

    parts = []
    citations = []
    remaining = max_context_chars
    for document in documents[:top_k]:
        metadata = getattr(document, "metadata", {}) or {}
        source = metadata.get("source")
        page = metadata.get("page")
        if source != "IEGC_Code.pdf" or not isinstance(page, int) or page < 0:
            raise RAGUnavailableError("retrieved excerpt lacks verifiable IEGC page metadata")
        text = str(getattr(document, "page_content", "")).strip()[:max_chunk_chars]
        if not text:
            continue
        citation = RetrievedCitation(source=source, page=page + 1)
        label = f"[{citation.source}, page {citation.page}]"
        excerpt = f"{label}\n{text}"[:remaining]
        if not excerpt:
            break
        parts.append(excerpt)
        citations.append(citation)
        remaining -= len(excerpt) + 2
        if remaining <= 0:
            break
    if not parts:
        raise RAGUnavailableError("retrieved regulatory excerpts contain no usable text")
    return ComplianceContext(text="\n\n".join(parts), citations=tuple(citations), verified=True)
