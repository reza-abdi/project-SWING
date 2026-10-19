"""Compare a read-only Project SWING archive with destination file bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def eligible(name: str) -> bool:
    path = PurePosixPath(name)
    parts = path.parts
    if not parts or parts[0] != "Project_SWING" or path.is_absolute() or ".." in parts:
        raise ValueError(f"unsafe archive path: {name!r}")
    return not any(part in {".git", "node_modules", "__pycache__", ".ipynb_checkpoints"} for part in parts)


def digest_stream(source) -> str:
    digest = hashlib.sha256()
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def compare(archive: Path, root: Path, transformations: dict[str, str]) -> tuple[list[str], int]:
    lines: list[str] = []
    failures = 0
    with ZipFile(archive) as source:
        for item in sorted(source.infolist(), key=lambda entry: entry.filename):
            if not eligible(item.filename) or item.is_dir():
                continue
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"archive symlink is not allowed: {item.filename!r}")
            relative = Path(*PurePosixPath(item.filename).parts[1:])
            target = root / relative
            if not target.resolve().is_relative_to(root):
                raise ValueError(f"destination path escapes root: {relative.as_posix()!r}")
            note = transformations.get(relative.as_posix())
            if not target.is_file() or target.is_symlink():
                status = "MISSING"
                failures += 1
            else:
                with source.open(item) as original, target.open("rb") as current:
                    same = digest_stream(original) == digest_stream(current)
                status = "MATCH" if same else "TRANSFORMED" if note else "DIFFERENT"
                failures += status == "DIFFERENT"
            lines.append(f"{status}\t{relative.as_posix()}" + (f"\t{note}" if note else ""))
    return lines, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--transformations", type=Path, help="JSON object: destination path to reason for deliberate edits")
    parser.add_argument("--allow-missing", action="store_true", help="Inventory an incomplete reconstruction without failing on absent files")
    args = parser.parse_args()
    transformations = json.loads(args.transformations.read_text()) if args.transformations else {}
    if not isinstance(transformations, dict) or any(not isinstance(key, str) or not isinstance(value, str) or not value for key, value in transformations.items()):
        parser.error("transformations must be a JSON object of path-to-nonempty-reason strings")
    lines, failures = compare(args.archive, args.root.resolve(), transformations)
    for line in lines:
        print(line)
    missing = sum(line.startswith("MISSING\t") for line in lines)
    print(f"Checked {len(lines)} source files; {missing} missing; {failures - missing} unexpected differences.")
    return 1 if failures and (failures != missing or not args.allow_missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
