"""Reproducible paths and helpers for the IEGC retrieval corpus."""

from __future__ import annotations

from pathlib import Path

from modules.config import runtime_paths

EMBEDDING_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"


class RAGBuilder:
    """Resolve the source PDF and persistent index under configured paths."""

    def __init__(self, pdf_path: str | Path | None = None, index_dir: str | Path | None = None) -> None:
        paths = runtime_paths()
        self.pdf_path = Path(pdf_path) if pdf_path is not None else paths.data / "knowledge_base" / "IEGC_Code.pdf"
        self.index_dir = Path(index_dir) if index_dir is not None else paths.faiss

    def require_pdf(self) -> Path:
        """Return the configured regulatory PDF or raise an actionable error."""
        if not self.pdf_path.is_file():
            raise FileNotFoundError(
                f"IEGC regulatory source PDF is missing: {self.pdf_path}. "
                "Place IEGC_Code.pdf in data/knowledge_base or set SWING_DATA_DIR."
            )
        return self.pdf_path

    def load_chunks(self):
        """Load PDF pages and split them into deterministic overlapping chunks."""
        from langchain_community.document_loaders import PyPDFLoader
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        pdf = self.require_pdf()
        pages = PyPDFLoader(str(pdf)).load()
        if not pages:
            raise ValueError(f"IEGC PDF contains no readable pages: {pdf}")
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_documents(pages)
        for chunk in chunks:
            page = chunk.metadata.get("page")
            chunk.metadata["source"] = pdf.name
            if page is not None:
                chunk.metadata["page"] = int(page)
        if not chunks or any(not chunk.page_content.strip() for chunk in chunks):
            raise ValueError("IEGC PDF produced empty or no text chunks")
        return chunks

    @staticmethod
    def create_embeddings():
        """Create the shared, CPU-safe embedding model used by indexing and search."""
        from langchain_community.embeddings import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_ID,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )


def corpus_paths() -> tuple[Path, Path]:
    """Return project-root independent source and output paths."""
    builder = RAGBuilder()
    return builder.pdf_path, builder.index_dir
