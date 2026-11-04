"""Audit tracked source and artifact metadata without deserializing binary assets."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{24,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|password|access[_-]?token)\s*[:=]\s*[\"']?([A-Za-z0-9_./+=-]{20,})"),
)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PLACEHOLDER_EMAILS = {"noreply@github.com", "user@example.com", "name@example.com"}
ALLOWED_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf", ".faiss", ".pkl", ".zip", ".ckpt"}
MAX_BINARY_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 3 * 1024 * 1024 * 1024


def tracked_files() -> list[Path]:
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True, capture_output=True)
    return [ROOT / item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item]


def _check_archive(path: Path) -> list[str]:
    issues = []
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                normalized = Path(member.filename)
                if normalized.is_absolute() or ".." in normalized.parts:
                    issues.append("archive contains an unsafe member path")
                    break
                if member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                    issues.append("archive member exceeds the inspection size limit")
                    break
    except (OSError, zipfile.BadZipFile):
        issues.append("archive metadata is invalid")
    return issues


def audit_file(path: Path) -> list[tuple[str, int | None]]:
    relative = path.relative_to(ROOT).as_posix()
    if path.is_symlink():
        return [("tracked symlink requires manual review", None)]
    if not path.is_file():
        return [("tracked file is missing", None)]
    if path.stat().st_size > MAX_BINARY_BYTES:
        return [("file exceeds the configured inspection limit", None)]
    try:
        with path.open("r", encoding="utf-8") as handle:
            first = handle.read(4096)
            handle.seek(0)
            if "\ufffd" in first:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "replacement character in source")
            findings = []
            for line_number, line in enumerate(handle, start=1):
                if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                    findings.append(("possible credential", line_number))
                for address in EMAIL_PATTERN.findall(line):
                    if (address.lower() not in PLACEHOLDER_EMAILS
                            and not address.lower().endswith(("@example.org", "@example.net", ".local"))):
                        findings.append(("email or account identifier", line_number))
            return findings
    except UnicodeDecodeError:
        if path.suffix.lower() not in ALLOWED_BINARY_SUFFIXES:
            return [("unsupported binary file type", None)]
        if path.suffix.lower() in {".zip", ".ckpt"}:
            return [(issue, None) for issue in _check_archive(path)]
        # Pickle and model files are deliberately treated as opaque bytes.
        return []


def _dependency_check() -> tuple[list[str], str]:
    requirements = ROOT / "requirements.txt"
    issues = []
    for line_number, raw in enumerate(requirements.read_text(encoding="utf-8").splitlines(), start=1):
        entry = raw.split("#", 1)[0].strip()
        if entry and not re.match(r"^[A-Za-z0-9_.-]+==[^=<>!~;\s]+(?:\s*;.*)?$", entry):
            issues.append(f"requirements.txt:{line_number}: dependency is not pinned exactly")
    auditor = shutil.which("pip-audit")
    if not auditor:
        return issues, "advisories not checked: pip-audit is not installed (run pip-audit -r requirements.txt)"
    completed = subprocess.run([auditor, "--requirement", str(requirements), "--format", "json"],
                               cwd=ROOT, capture_output=True, text=True, timeout=120)
    if completed.returncode:
        issues.append("pip-audit reported dependency advisories or could not complete; inspect its output locally")
    return issues, "pip-audit completed" if completed.returncode == 0 else "pip-audit reported issues"


def self_test() -> None:
    fake_value = "ghp_" + ("A" * 28)
    with tempfile.TemporaryDirectory(prefix="swing-audit-") as directory:
        sample = Path(directory) / "fixture.txt"
        sample.write_text("token=" + fake_value, encoding="utf-8")
        original_root = ROOT
        try:
            globals()["ROOT"] = Path(directory)
            if not audit_file(sample):
                raise RuntimeError("self-test failed to catch the fake credential fixture")
        finally:
            globals()["ROOT"] = original_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracked", action="store_true", help="audit every tracked worktree file")
    parser.add_argument("--self-test", action="store_true", help="verify secret detection with a fake credential")
    args = parser.parse_args(argv)
    if not args.tracked and not args.self_test:
        parser.error("choose --tracked and/or --self-test")
    findings = []
    if args.tracked:
        for path in tracked_files():
            for issue, line_number in audit_file(path):
                findings.append((path.relative_to(ROOT).as_posix(), line_number, issue))
        dependency_issues, advisory_status = _dependency_check()
        findings.extend(("requirements.txt", None, issue) for issue in dependency_issues)
        print(advisory_status)
    if args.self_test:
        self_test()
        print("OK fake credential fixture detected")
    for path, line_number, issue in findings:
        location = f"{path}:{line_number}" if line_number is not None else path
        print(f"FINDING {location}: {issue}")
    print(f"Audit findings: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
