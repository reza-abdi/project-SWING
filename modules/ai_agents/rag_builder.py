"""Reproducible paths and helpers for the IEGC retrieval corpus."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile

from modules.config import runtime_paths

EMBEDDING_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
IEGC_PDF_SHA256 = "65d15233dd34ecf4d5bc5a898e47034d0349e7c59404de258cc062633fba2e25"


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

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def build_index(self, embeddings=None) -> dict[str, object]:
        """Build a hash-manifested FAISS index from the verified IEGC PDF."""
        from langchain_community.vectorstores import FAISS

        pdf = self.require_pdf()
        pdf_sha256 = self._hash_file(pdf)
        if pdf_sha256 != IEGC_PDF_SHA256:
            raise ValueError("IEGC PDF hash differs from the reviewed source; refusing to index it")
        chunks = self.load_chunks()
        embeddings = embeddings or self.create_embeddings()
        vector_store = FAISS.from_documents(chunks, embeddings)
        self.index_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rag-index-", dir=self.index_dir.parent) as work_dir:
            staged_index = Path(work_dir) / "index"
            vector_store.save_local(str(staged_index))
            staged_index.chmod(0o700)
            for artifact in (staged_index / "index.faiss", staged_index / "index.pkl"):
                artifact.chmod(0o600)
            manifest = {
                "source_pdf": pdf.name,
                "source_sha256": pdf_sha256,
                "embedding_model": EMBEDDING_MODEL_ID,
                "chunk_size": 1000,
                "chunk_overlap": 200,
                "chunk_count": len(chunks),
                "index_faiss_sha256": self._hash_file(staged_index / "index.faiss"),
                "index_pickle_sha256": self._hash_file(staged_index / "index.pkl"),
            }
            (staged_index / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            backup = Path(work_dir) / "previous"
            had_previous = self.index_dir.exists()
            if had_previous:
                os.replace(self.index_dir, backup)
            try:
                os.replace(staged_index, self.index_dir)
            except Exception:
                if had_previous:
                    os.replace(backup, self.index_dir)
                raise
        return {**manifest, "manifest_sha256": self._hash_file(self.index_dir / "manifest.json")}

    def load_index(self, embeddings, *, trusted_manifest_sha256: str | None = None):
        """Load only an explicitly hash-pinned index from a private directory."""
        if trusted_manifest_sha256 is None:
            raise PermissionError("FAISS pickle loading requires an externally pinned manifest hash")
        manifest_path = self.index_dir / "manifest.json"
        faiss_path = self.index_dir / "index.faiss"
        pickle_path = self.index_dir / "index.pkl"
        if not all(path.is_file() for path in (manifest_path, faiss_path, pickle_path)):
            raise FileNotFoundError("FAISS index is incomplete; rebuild it from the verified regulatory PDF")
        if stat.S_IMODE(self.index_dir.stat().st_mode) & 0o077:
            raise PermissionError("FAISS index directory must not be accessible by group or other users")
        manifest_digest = self._hash_file(manifest_path)
        if manifest_digest != trusted_manifest_sha256:
            raise ValueError("FAISS manifest hash mismatch; refusing to deserialize index pickle")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {
            "source_sha256": IEGC_PDF_SHA256,
            "embedding_model": EMBEDDING_MODEL_ID,
            "index_faiss_sha256": self._hash_file(faiss_path),
            "index_pickle_sha256": self._hash_file(pickle_path),
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise ValueError("FAISS artifacts do not match their trusted manifest")
        from langchain_community.vectorstores import FAISS

        return FAISS.load_local(
            str(self.index_dir), embeddings, allow_dangerous_deserialization=True
        )


def corpus_paths() -> tuple[Path, Path]:
    """Return project-root independent source and output paths."""
    builder = RAGBuilder()
    return builder.pdf_path, builder.index_dir
