"""Check that runtime imports are explained by requirements or the stdlib."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (ROOT / "main.py", ROOT / "modules", ROOT / "scripts")

# Import names that differ from their distribution names, plus optional packages
# whose features must remain usable when those extras are not installed.
IMPORT_TO_DISTRIBUTION = {
    "dotenv": "python-dotenv",
    "faiss": "faiss-cpu",
    "lightgbm": "lightgbm",
    "pytorch_forecasting": "pytorch-forecasting",
    "sentence_transformers": "sentence-transformers",
    "stable_baselines3": "stable-baselines3",
}
OPTIONAL_IMPORTS = {
    "faiss",
    "lightgbm",
    "pytorch_forecasting",
    "sentence_transformers",
    "stable_baselines3",
    "torch",
}
LOCAL_IMPORTS = {"modules", "scripts"}


def normalize_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_names() -> set[str]:
    names: set[str] = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)", line)
        assert match, f"Cannot parse requirement: {line}"
        names.add(normalize_distribution(match.group(1)))
    return names


def source_files() -> list[Path]:
    files: list[Path] = []
    for source_root in SOURCE_ROOTS:
        files.extend([source_root] if source_root.is_file() else source_root.rglob("*.py"))
    return sorted(path for path in files if path.is_file())


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".", 1)[0])
    return imports


def test_production_imports_are_in_dependency_inventory() -> None:
    dependencies = requirement_names()
    imports = set().union(*(imported_roots(path) for path in source_files()))
    unresolved = set()
    for module in imports:
        if module in sys.stdlib_module_names or module in LOCAL_IMPORTS:
            continue
        distribution = IMPORT_TO_DISTRIBUTION.get(module, module)
        if normalize_distribution(distribution) not in dependencies and module not in OPTIONAL_IMPORTS:
            unresolved.add(module)
    assert not unresolved, f"Imports absent from requirements.txt or optional inventory: {sorted(unresolved)}"


def test_optional_runtime_imports_are_documented() -> None:
    assert OPTIONAL_IMPORTS <= imports_supported_by_policy()


def imports_supported_by_policy() -> set[str]:
    """Optional modules must either be dependencies or have an explicit alias."""
    return set(IMPORT_TO_DISTRIBUTION) | {"torch"}
