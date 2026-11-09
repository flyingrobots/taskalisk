"""Hash and emit the CLI result protocol."""

from __future__ import annotations

import hashlib
import json

from .graph_results import ArtifactMeta, GraphResult
from .rendering import render_mermaid_flowchart, render_roadmap_block


def with_artifact_hash(result: GraphResult) -> GraphResult:
    """Attach the SHA-256 of canonical JSON before adding the metadata field."""
    canonical = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    metadata: ArtifactMeta = {"artifact_hash": hashlib.sha256(canonical).hexdigest()}
    result["meta"] = metadata
    return result


def emit(result: GraphResult, emit_mermaid: bool, emit_roadmap: bool = False) -> int:
    """Render the selected successful view or JSON, returning its success status."""
    if "metrics" in result and emit_roadmap and result["ok"]:
        print(render_roadmap_block(result))
    elif "metrics" in result and emit_mermaid and result["ok"]:
        print(render_mermaid_flowchart(result))
    else:
        print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1
