"""What the checker reads from the specification: the rule labels and the numbered differences."""
from __future__ import annotations

import pathlib
import re

# A normative statement opens with its label in bold: **C4.**, **E6a. What is new.**
LABEL_RE = re.compile(r"\*\*([A-Z]{1,2}[0-9]+[a-z]?)\.")
SPEC_DOCUMENTS = ("formats/*.md", "profiles/*.md", "contracts/*.md", "versions.md", "corpus/*.md")
NOTE = "notes/python-differences.md"
CLASSIFICATIONS = ("legacy", "defect", "compatibility-exception")
# A row of a differences table: | 9 | situation | ... | rule | classification |
DIFF_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|.*\|\s*([a-z-]+)\s*\|\s*$")


def rule_labels(spec_root: pathlib.Path) -> dict[str, str]:
    """Every label of a normative statement, with the document that states it. A label stated twice is an error."""
    labels: dict[str, str] = {}
    for pattern in SPEC_DOCUMENTS:
        for doc in sorted(pathlib.Path(spec_root).glob(pattern)):
            rel = doc.relative_to(spec_root).as_posix()
            for label in LABEL_RE.findall(doc.read_text(encoding="utf-8")):
                if label in labels and labels[label] != rel:
                    raise ValueError(f"rule label {label} is stated in both {labels[label]} and {rel}")
                labels[label] = rel
    return labels


def differences(spec_root: pathlib.Path) -> dict[int, str]:
    """Each numbered difference of the note, with its classification (the last column of its row)."""
    found: dict[int, str] = {}
    for line in (pathlib.Path(spec_root) / NOTE).read_text(encoding="utf-8").splitlines():
        m = DIFF_ROW_RE.match(line)
        if m:
            found[int(m.group(1))] = m.group(2)
    return found
