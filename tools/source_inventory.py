"""Discover maintained Python files and read bounded regular UTF-8 sources."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from itertools import islice
from pathlib import Path
from typing import NoReturn

SOURCE_ROOTS = ("skills/taskalisk/scripts", "tests", "tools")
MAX_SOURCE_FILES = 1000
MAX_SOURCE_BYTES = 1024 * 1024
MAX_SOURCE_DIRECTORIES = 1000


class SourceKindError(ValueError):
    """The opened source is not a regular file."""


class SourceSizeError(ValueError):
    """The source exceeds the one-MiB input ceiling."""


class SourceDirectoryError(OSError):
    """The source tree contains linked directories or exceeds its traversal ceiling."""


def _enumeration_error(error: OSError) -> NoReturn:
    """Propagate filesystem enumeration errors instead of silently skipping a subtree."""
    raise error


def directory_sources(directory: Path) -> Iterator[Path]:
    """Enumerate both source extensions with explicit errors and bounded directory traversal."""
    tree = os.walk(directory, onerror=_enumeration_error, followlinks=False)
    for count, (parent, directories, files) in enumerate(tree, 1):
        if count > MAX_SOURCE_DIRECTORIES:
            raise SourceDirectoryError
        if any((Path(parent) / name).is_symlink() for name in directories):
            raise SourceDirectoryError
        for name in files:
            if name.endswith((".py", ".pyi")):
                yield Path(parent) / name


def source_paths(root: Path) -> tuple[list[Path], list[str]]:
    """Require every maintained root and stop an oversized inventory before reading files."""
    paths: list[Path] = []
    errors: list[str] = []
    for name in SOURCE_ROOTS:
        directory = root / name
        if directory.is_symlink() or not directory.is_dir():
            errors.append(f"{name}: missing or linked source directory")
            continue
        try:
            candidates = directory_sources(directory)
            paths.extend(islice(candidates, MAX_SOURCE_FILES + 1 - len(paths)))
        except OSError:
            errors.append(f"{name}: cannot enumerate sources")
        if len(paths) > MAX_SOURCE_FILES:
            return [], ["maintained source inventory exceeds 1000 files"]
    if not paths:
        errors.append("no maintained Python sources")
    return sorted(paths), errors


def read_source(path: Path) -> str:
    """Read at most one MiB from a non-symlink regular file; refuse decoding and I/O errors."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SourceKindError
        chunks: list[bytes] = []
        count = 0
        while chunk := os.read(descriptor, min(65536, MAX_SOURCE_BYTES + 1 - count)):
            chunks.append(chunk)
            count += len(chunk)
            if count > MAX_SOURCE_BYTES:
                raise SourceSizeError
        return b"".join(chunks).decode("utf-8")
    finally:
        os.close(descriptor)
