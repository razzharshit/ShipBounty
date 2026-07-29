#!/usr/bin/env python3
"""Export this repository into one self-contained, human-readable text file.

Text files are written verbatim under a commented path header. Binary files are
base64 encoded so that static assets can also be restored exactly. Files matched
by any .gitignore below the project root are omitted.
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


FORMAT = "CODEBASE_EXPORT_V1"
DEFAULT_OMITTED_DIRS = {".git", ".next", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv"}
DEFAULT_OMITTED_NAMES = {".DS_Store"}
# These are delivery/archive artifacts rather than files needed to reconstruct
# the runnable codebase. Static application assets (PNG, SVG, ICO, fonts, etc.)
# are still included and restored as base64 where necessary.
DEFAULT_OMITTED_SUFFIXES = {".docx", ".zip"}


class IgnoreRules:
    """A small, dependency-free subset of gitignore matching used for export."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.rules: list[tuple[Path, str, bool, bool]] = []
        for current, dirs, names in os.walk(root, topdown=True):
            dirs[:] = [name for name in dirs if name not in DEFAULT_OMITTED_DIRS]
            if ".gitignore" not in names:
                continue
            ignore_file = Path(current) / ".gitignore"
            for raw in ignore_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                negate = line.startswith("!")
                if negate:
                    line = line[1:]
                directory_only = line.endswith("/")
                line = line.rstrip("/")
                if line:
                    self.rules.append((ignore_file.parent, line, negate, directory_only))

    def ignored(self, path: Path, is_dir: bool = False) -> bool:
        ignored = False
        for base, pattern, negate, directory_only in self.rules:
            try:
                relative = path.relative_to(base).as_posix()
            except ValueError:
                continue
            if self._matches(relative, pattern, directory_only, is_dir):
                ignored = not negate
        return ignored

    @staticmethod
    def _matches(relative: str, pattern: str, directory_only: bool, is_dir: bool) -> bool:
        anchored = pattern.startswith("/")
        pattern = pattern.lstrip("/")
        parts = relative.split("/")
        candidates = [relative] if anchored or "/" in pattern else parts
        if directory_only:
            candidates = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
        return any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates)


def is_text(data: bytes) -> bool:
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def iter_files(root: Path, output: Path):
    rules = IgnoreRules(root)
    for current, dirs, names in os.walk(root, topdown=True):
        current_path = Path(current)
        dirs[:] = [
            name for name in dirs
            if name not in DEFAULT_OMITTED_DIRS
            and not rules.ignored(current_path / name, is_dir=True)
        ]
        for name in sorted(names):
            file_path = current_path / name
            if (name in DEFAULT_OMITTED_NAMES or file_path.suffix.lower() in DEFAULT_OMITTED_SUFFIXES
                    or file_path.resolve() == output.resolve()):
                continue
            if rules.ignored(file_path):
                continue
            yield file_path


def write_export(root: Path, output: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    with output.open("wb") as destination:
        destination.write(f"# {FORMAT}\n# Root: {root.name}\n\n".encode())
        for file_path in iter_files(root, output):
            relative = file_path.relative_to(root).as_posix()
            data = file_path.read_bytes()
            text = is_text(data)
            payload = data if text else base64.b64encode(data)
            encoding = "utf-8" if text else "base64"
            digest = hashlib.sha256(data).hexdigest()
            # This is deliberately a comment so a reader can see each file location.
            header = f"# FILE: {relative} | encoding: {encoding} | bytes: {len(payload)} | sha256: {digest}\n"
            destination.write(header.encode("ascii"))
            destination.write(payload)
            destination.write(b"\n# END FILE\n\n")
            manifest[relative] = digest
    return manifest


def validate(root: Path, export_file: Path, expected: dict[str, str]) -> None:
    importer = Path(__file__).with_name("import_codebase.py")
    with tempfile.TemporaryDirectory(prefix="codebase-roundtrip-") as temporary:
        rebuilt = Path(temporary) / "rebuilt"
        result = subprocess.run(
            [sys.executable, str(importer), "--input", str(export_file), "--output", str(rebuilt)],
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        actual = {
            path.relative_to(rebuilt).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in rebuilt.rglob("*") if path.is_file()
        }
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        changed = sorted(path for path in expected.keys() & actual.keys() if expected[path] != actual[path])
        extra = sorted(set(actual) - set(expected))
        raise RuntimeError(f"round-trip mismatch; missing={missing}, changed={changed}, extra={extra}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create one text export of the non-ignored repository files.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root (default: current directory)")
    parser.add_argument("--output", type=Path, default=Path("CODEBASE_EXPORT.txt"), help="Export file path")
    parser.add_argument("--validate", action="store_true", help="Import into a temporary directory and verify every SHA-256 hash")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output.is_absolute() else (root / args.output).resolve()
    if not root.is_dir():
        parser.error(f"root does not exist: {root}")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = write_export(root, output)
    print(f"Exported {len(manifest)} files to {output}")
    if args.validate:
        validate(root, output, manifest)
        print("Round-trip validation passed: all exported files were restored byte-for-byte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
