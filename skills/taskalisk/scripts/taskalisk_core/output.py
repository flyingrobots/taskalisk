"""Hash and emit the CLI result protocol."""

from __future__ import annotations

import hashlib
import json
from enum import Enum, auto

from .graph_results import ArtifactMeta, GraphResult
from .rendering import render_mermaid_flowchart, render_roadmap_block


class OutputView(Enum):
    """The selected successful representation; failures always use JSON."""

    JSON = auto()
    MERMAID = auto()
    ROADMAP = auto()


def write_text(text: str) -> None:
    """Emit the public stdout protocol, including its terminating newline."""
    print(text)  # noqa: T201 -- public CLI protocol; PY-CLI-OUTPUT in exceptions.json


def write_json(value: object, *, indent: int | None = 2) -> None:
    """Serialize a result or refusal with its existing JSON whitespace convention."""
    write_text(json.dumps(value, indent=indent))


def with_artifact_hash(result: GraphResult) -> GraphResult:
    """Attach the SHA-256 of canonical JSON before adding the metadata field."""
    canonical = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    metadata: ArtifactMeta = {"artifact_hash": hashlib.sha256(canonical).hexdigest()}
    result["meta"] = metadata
    return result


def emit(result: GraphResult, view: OutputView) -> int:
    """Render the selected successful view or JSON, returning its success status."""
    if "metrics" in result and view is OutputView.ROADMAP and result["ok"]:
        write_text(render_roadmap_block(result))
    elif "metrics" in result and view is OutputView.MERMAID and result["ok"]:
        write_text(render_mermaid_flowchart(result))
    else:
        write_json(result)
    return 0 if result.get("ok") else 1
