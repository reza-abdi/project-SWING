"""RAG ingestion, embedding identity and index trust-boundary tests."""

import hashlib
import json
import sys
import types

import pytest

from modules.ai_agents.rag_builder import (
    EMBEDDING_MODEL_ID,
    IEGC_PDF_SHA256,
    RAGBuilder,
)


def module_with(name, **values):
    result = types.ModuleType(name)
    for key, value in values.items():
        setattr(result, key, value)
    return result


def test_chunking_uses_1000_200_and_retains_page_provenance(monkeypatch, tmp_path) -> None:
    pdf = tmp_path / "IEGC_Code.pdf"
    pdf.write_bytes(b"fake-pdf")
    calls = {}

    class Loader:
        def __init__(self, path): calls["path"] = path
        def load(self): return [types.SimpleNamespace(page_content="page text", metadata={"page": 0})]

    class Splitter:
        def __init__(self, **kwargs): calls.update(kwargs)
        def split_documents(self, documents): return documents

    monkeypatch.setitem(sys.modules, "langchain_community.document_loaders", module_with("loader", PyPDFLoader=Loader))
    monkeypatch.setitem(sys.modules, "langchain_text_splitters", module_with("splitters", RecursiveCharacterTextSplitter=Splitter))
    chunks = RAGBuilder(pdf_path=pdf).load_chunks()
    assert calls["chunk_size"] == 1000 and calls["chunk_overlap"] == 200
    assert chunks[0].metadata == {"page": 0, "source": "IEGC_Code.pdf"}


def test_embedding_identity_is_fixed_and_cpu_configured(monkeypatch) -> None:
    received = {}

    class Embeddings:
        def __init__(self, **kwargs): received.update(kwargs)

    monkeypatch.setitem(sys.modules, "langchain_community.embeddings", module_with("embeddings", HuggingFaceEmbeddings=Embeddings))
    RAGBuilder.create_embeddings()
    assert received["model_name"] == EMBEDDING_MODEL_ID
    assert received["model_kwargs"] == {"device": "cpu"}


def test_missing_pdf_has_actionable_error(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="IEGC_Code.pdf"):
        RAGBuilder(pdf_path=tmp_path / "missing.pdf").require_pdf()


def test_altered_index_pickle_is_rejected_before_faiss_load(monkeypatch, tmp_path) -> None:
    directory = tmp_path / "faiss_index"
    directory.mkdir(mode=0o700)
    faiss_path = directory / "index.faiss"
    pickle_path = directory / "index.pkl"
    faiss_path.write_bytes(b"faiss data")
    pickle_path.write_bytes(b"trusted pickle bytes")
    manifest = {
        "source_sha256": IEGC_PDF_SHA256,
        "embedding_model": EMBEDDING_MODEL_ID,
        "index_faiss_sha256": hashlib.sha256(faiss_path.read_bytes()).hexdigest(),
        "index_pickle_sha256": hashlib.sha256(pickle_path.read_bytes()).hexdigest(),
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    pinned_manifest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    pickle_path.write_bytes(b"altered pickle")
    called = []
    monkeypatch.setitem(sys.modules, "langchain_community.vectorstores", module_with(
        "vectorstores", FAISS=types.SimpleNamespace(load_local=lambda *a, **k: called.append(True))
    ))

    with pytest.raises(ValueError, match="artifacts do not match"):
        RAGBuilder(index_dir=directory).load_index(object(), trusted_manifest_sha256=pinned_manifest)
    assert called == []


def test_unpinned_index_never_deserializes(tmp_path) -> None:
    with pytest.raises(PermissionError, match="externally pinned"):
        RAGBuilder(index_dir=tmp_path / "missing").load_index(object())
