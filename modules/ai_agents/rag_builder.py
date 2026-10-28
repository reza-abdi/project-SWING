"""Reproducible paths and helpers for the IEGC retrieval corpus."""

from __future__ import annotations

from pathlib import Path

from modules.config import runtime_paths


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


def corpus_paths() -> tuple[Path, Path]:
    """Return project-root independent source and output paths."""
    builder = RAGBuilder()
    return builder.pdf_path, builder.index_dir
