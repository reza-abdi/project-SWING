"""Inspect dependencies and artifact availability without loading model payloads."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import os
import sys
from pathlib import Path
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.config import runtime_paths  # noqa: E402


PACKAGES = {
    "fastapi": ("fastapi", True),
    "uvicorn": ("uvicorn", True),
    "numpy": ("numpy", True),
    "pandas": ("pandas", True),
    "pandapower": ("pandapower", True),
    "lightgbm": ("lightgbm", False),
    "torch": ("torch", False),
    "stable-baselines3": ("stable_baselines3", False),
    "pytorch-forecasting": ("pytorch_forecasting", False),
    "langgraph": ("langgraph", False),
    "langchain-core": ("langchain_core", False),
    "sentence-transformers": ("sentence_transformers", False),
    "faiss-cpu": ("faiss", False),
    "pypdf": ("pypdf", False),
}
INPUT_FILES = (
    "raw_data/hourlyLoadDataIndia.csv",
    "raw_data/Northern_Region_Hourly_Weather_2019_2024.csv",
    "processed_data/tft_ready_data.csv",
    "knowledge_base/IEGC_Code.pdf",
    "knowledge_base/faiss_index/index.faiss",
    "knowledge_base/faiss_index/index.pkl",
)
MODEL_FILES = (
    "lightgbm_q_10.txt",
    "lightgbm_q_50.txt",
    "lightgbm_q_90.txt",
    "rl_optimizer_shed_load_39.zip",
    "rl_optimizer_redispatch_gen_39.zip",
    "rl_optimizer_shed_load_118.zip",
    "rl_optimizer_redispatch_gen_118.zip",
    "tft_best_model.ckpt",
    "training_dataset.pkl",
)


def physical_memory_bytes() -> int | None:
    try:
        return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return None


def check_package(name: str, module: str) -> tuple[bool, str]:
    try:
        available = importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        available = False
    try:
        version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        version = "version unavailable"
    return available, version


def inspect_policy_metadata(path: Path) -> str:
    """Read plain-text SB3 metadata from a ZIP without deserializing policy files."""
    try:
        with ZipFile(path) as archive:
            metadata_name = next((name for name in archive.namelist() if name.endswith("system_info.txt")), None)
            if metadata_name is None:
                return "metadata absent"
            content = archive.read(metadata_name).decode("utf-8", errors="replace")
    except (BadZipFile, OSError):
        return "invalid ZIP"
    selected = [line.strip() for line in content.splitlines() if line.lower().startswith(("python:", "pytorch:", "gymnasium:"))]
    return "; ".join(selected) if selected else "metadata present"


def check_files(base: Path, names: tuple[str, ...], *, offline: bool) -> tuple[int, int]:
    present = missing = 0
    for name in names:
        path = base / name
        if path.is_file() and not path.is_symlink():
            present += 1
            detail = f"{path.stat().st_size} bytes"
            if path.suffix == ".zip" and path.name.startswith("rl_optimizer_"):
                detail += "; " + inspect_policy_metadata(path)
            print(f"OK      {path.relative_to(ROOT)} ({detail})")
        else:
            missing += 1
            severity = "INFO" if offline else "MISSING"
            print(f"{severity:<7} {path.relative_to(ROOT)}")
    return present, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Do not access networks; report absent artifacts without failing")
    args = parser.parse_args()
    paths = runtime_paths({})
    missing_required = False
    for package, (module, required) in PACKAGES.items():
        available, version = check_package(package, module)
        print(f"{'OK' if available else 'MISSING':<7} package {package}: {version}")
        if required and not available:
            missing_required = True

    print("Input data and RAG artifacts:")
    _, missing_inputs = check_files(paths.data, INPUT_FILES, offline=args.offline)
    print("Model artifacts:")
    _, missing_models = check_files(paths.models, MODEL_FILES, offline=args.offline)

    total_bytes = sum((base / name).stat().st_size for base, names in ((paths.data, INPUT_FILES), (paths.models, MODEL_FILES)) for name in names if (base / name).is_file())
    memory = physical_memory_bytes()
    if memory is None:
        print(f"Memory budget: artifact footprint {total_bytes} bytes; physical memory unavailable")
    else:
        print(f"Memory budget: artifact footprint {total_bytes} bytes; physical memory {memory} bytes")
        if total_bytes > memory // 4:
            print("WARNING artifact files exceed one quarter of physical memory; inference can require additional RAM")

    if missing_required or (not args.offline and (missing_inputs or missing_models)):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
