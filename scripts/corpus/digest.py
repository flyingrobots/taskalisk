"""The corpus digest (corpus/README.md, rule CD1): SHA-256 over every file of the corpus directory
except DIGEST, in order of path, each as its path, its length and its bytes."""
from __future__ import annotations

import hashlib
import pathlib
import sys

DIGEST_FILE = "DIGEST"


def corpus_files(corpus: pathlib.Path) -> list[tuple[str, pathlib.Path]]:
    """(relative POSIX path, file) for every regular file, sorted by the path's UTF-8 bytes."""
    found = []
    for path in corpus.rglob("*"):
        if path.is_file():
            rel = path.relative_to(corpus).as_posix()
            if rel != DIGEST_FILE:
                found.append((rel, path))
    return sorted(found, key=lambda item: item[0].encode("utf-8"))


def corpus_digest(corpus: pathlib.Path) -> str:
    h = hashlib.sha256()
    for rel, path in corpus_files(pathlib.Path(corpus)):
        data = path.read_bytes()
        name = rel.encode("utf-8")
        h.update(len(name).to_bytes(8, "big") + name + len(data).to_bytes(8, "big") + data)
    return "sha256:" + h.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: digest.py <corpus-directory>\n")
        return 2
    print(corpus_digest(pathlib.Path(argv[0])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
