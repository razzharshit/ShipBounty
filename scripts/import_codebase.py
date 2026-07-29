#!/usr/bin/env python3
"""Restore a project tree from a CODEBASE_EXPORT.txt created by export_codebase.py."""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
from pathlib import Path, PurePosixPath


FORMAT = b"# CODEBASE_EXPORT_V1\n"
HEADER = re.compile(rb"# FILE: ([^|\r\n]+) \| encoding: (utf-8|base64) \| bytes: (\d+) \| sha256: ([0-9a-f]{64})\r?\n")
END = b"\n# END FILE\n"


def safe_relative_path(value: str) -> Path:
    path = PurePosixPath(value.strip())
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe path in export: {value!r}")
    return Path(*path.parts)


def parse_export(source: Path):
    data = source.read_bytes()
    if not data.startswith(FORMAT):
        raise ValueError("not a CODEBASE_EXPORT_V1 file")
    cursor = data.find(b"\n\n") + 2
    if cursor == 1:
        raise ValueError("missing export preamble")
    seen: set[Path] = set()
    while cursor < len(data):
        match = HEADER.match(data, cursor)
        if not match:
            raise ValueError(f"invalid file header at byte {cursor}")
        raw_path, encoding, byte_count, expected_hash = match.groups()
        relative = safe_relative_path(raw_path.decode("utf-8"))
        if relative in seen:
            raise ValueError(f"duplicate path in export: {relative}")
        seen.add(relative)
        cursor = match.end()
        payload_length = int(byte_count)
        payload = data[cursor:cursor + payload_length]
        if len(payload) != payload_length:
            raise ValueError(f"truncated data for {relative}")
        cursor += payload_length
        if not data.startswith(END, cursor):
            raise ValueError(f"missing end marker for {relative}")
        cursor += len(END)
        if data[cursor:cursor + 1] == b"\n":
            cursor += 1
        original = payload if encoding == b"utf-8" else base64.b64decode(payload, validate=True)
        if hashlib.sha256(original).hexdigest().encode() != expected_hash:
            raise ValueError(f"SHA-256 mismatch for {relative}")
        yield relative, original


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a CODEBASE_EXPORT.txt into a new directory.")
    parser.add_argument("--input", required=True, type=Path, help="Export file created by export_codebase.py")
    parser.add_argument("--output", required=True, type=Path, help="New or empty destination directory")
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output.resolve()
    if not source.is_file():
        parser.error(f"input does not exist: {source}")
    if output.exists() and any(output.iterdir()):
        parser.error(f"output directory must be new or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    for relative, content in parse_export(source):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        count += 1
    print(f"Restored {count} files to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
