"""Run lightweight syntax, notebook, manifest, and local-import checks."""

from __future__ import annotations

import ast
import json
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


def python_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.py")
        if not any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts)
    )


def module_candidates(module: str) -> tuple[Path, ...]:
    parts = module.split(".")
    base = ROOT.joinpath(*parts)
    return base.with_suffix(".py"), base / "__init__.py"


def check_imports(path: Path, tree: ast.Module) -> list[str]:
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
        else:
            continue
        for module in modules:
            top_level = module.split(".", 1)[0]
            if top_level not in {"modules", "scripts", "tests"}:
                continue
            if not any(candidate.is_file() for candidate in module_candidates(module)):
                errors.append(f"{path.relative_to(ROOT)}:{node.lineno}: unresolved local import {module}")
    return errors


def check_python(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with tokenize.open(path) as source:
            tree = ast.parse(source.read(), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        return [f"{path.relative_to(ROOT)}: {exc}"]
    errors.extend(check_imports(path, tree))
    return errors


def check_notebook(path: Path) -> list[str]:
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"{path.relative_to(ROOT)}: invalid notebook JSON: {exc}"]
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        return [f"{path.relative_to(ROOT)}: notebook must contain a cells array"]
    errors: list[str] = []
    for index, cell in enumerate(notebook["cells"]):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        if not isinstance(source, str):
            errors.append(f"{path.relative_to(ROOT)}: cell {index} source must be text")
            continue
        try:
            tree = ast.parse(source, filename=f"{path.relative_to(ROOT)}:cell {index}")
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(ROOT)}: cell {index}: {exc}")
            continue
        errors.extend(check_imports(path, tree))
    return errors


def check_manifests() -> list[str]:
    errors: list[str] = []
    for path in sorted((*ROOT.rglob("*.json"), *ROOT.rglob("*.ipynb"))):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix == ".ipynb":
            errors.extend(check_notebook(path))
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
    return errors


def main() -> int:
    errors: list[str] = []
    files = python_files()
    for path in files:
        errors.extend(check_python(path))
    errors.extend(check_manifests())
    if errors:
        print("\n".join(f"ERROR {error}" for error in errors))
        return 1
    print(f"Static checks passed: {len(files)} Python files and valid JSON/notebook manifests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
