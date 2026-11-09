"""Render compiled plans as Mermaid and Markdown."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .defaults import MERMAID_TITLE_MAX
from .issue_refs import id_sort_key


def render_mermaid_flowchart(dag_result: dict[str, Any]) -> str:
    """Render task nodes and reduced edges with neutralized diagram labels."""
    waves: dict[str, list[dict[str, Any]]] = dag_result.get("waves", {})

    def safe_id(raw: str) -> str:
        return "N_" + re.sub(r"[^A-Za-z0-9_]", "_", raw)

    lines = ["flowchart TD"]
    edges: list[tuple[str, str]] = []
    for wave_name, items in waves.items():
        sg = re.sub(r"[^A-Za-z0-9_]", "", wave_name)
        label = (
            f"{wave_name}: Open Frontier (Zero Incomplete Parents)"
            if wave_name == "Wave 0"
            else wave_name
        )
        lines.append(f'  subgraph {sg}["{label}"]')
        for item in items:
            nid = item["id"]
            title = item.get("title", "")
            if len(title) > MERMAID_TITLE_MAX:
                title = title[: MERMAID_TITLE_MAX - 3] + "..."
            safe_label = (
                f"{nid}: {title}".replace('"', "'")
                .replace("<", "(")
                .replace(">", ")")
                .replace("[", "(")
                .replace("]", ")")
            )
            lines.append(f'    {safe_id(nid)}["{safe_label}"]')
            for child in item.get("directly_unlocks", []):
                edges.append((safe_id(nid), safe_id(child)))
        lines.append("  end")
    for s, d in edges:
        lines.append(f"  {s} --> {d}")
    return "\n".join(lines)


ROADMAP_BEGIN = "<!-- BEGIN GENERATED ISSUE DAG (taskalisk --emit-roadmap; do not edit by hand) -->"

ROADMAP_END = "<!-- END GENERATED ISSUE DAG -->"


def _issue_link(nid: str, url: str | None) -> str:
    return f"[{nid}]({url})" if url else nid


def _resources_cell(holds: list[str], meters: list[dict[str, Any]], empty: str) -> str:
    cells = [f"`{_md_cell(k)}`" for k in holds] + [
        "`" + _md_cell(str(m["name"])) + "*" + str(m["slots"]) + "`" for m in meters
    ]
    return ", ".join(cells) or empty


def _md_cell(text: str) -> str:
    """Issue text in a rendered table cell: no pipes, no HTML, no links, no line breaks (C5)."""
    return (
        str(text)
        .replace("|", "\\|")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("\n", " ")
    )


def render_roadmap_block(result: dict[str, Any]) -> str:
    """Render the computed ROADMAP sections. Pure function of the compiled DAG."""
    m = result["metrics"]
    src = result.get("source", {})
    waves: dict[str, list[dict[str, Any]]] = result["waves"]
    by_id = {n["id"]: n for items in waves.values() for n in items}
    out: list[str] = [ROADMAP_BEGIN, ""]
    out += [
        f"Compiled from issue frontmatter (`{src.get('schema', '')}`), home `{src.get('repository', '')}`, roots `{', '.join(src.get('roots') or []) or 'all open home issues'}`. "
        f"Artifact hash `{result.get('meta', {}).get('artifact_hash', '')[:16]}`. "
        "Regenerate with `taskalisk.py --from-github [--root <ref>] --emit-roadmap`.",
        "",
        "## DAG Structural Health",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Open nodes | {m['open_node_count']} |",
        f"| Reduced edges (raw) | {m['reduced_open_edge_count']} ({m['raw_open_edge_count']}) |",
        f"| Edge density | {m['edge_density']} ({'in' if m['edge_density_band_ok'] else 'outside'} band 0.01–0.50) |",
        f"| Max parallel width | {m['max_parallel_width']} |",
        f"| Critical path ({m['critical_path_length']}) | {' → '.join(m['critical_path'])} |",
        f"| Isolated nodes | {m['isolated_open_node_count']} |",
        f"| Containers excluded | {', '.join(c['id'] for c in src.get('containers_excluded', [])) or 'none'} |",
        "",
        "## Ranked Open Frontier (Wave 0)",
        "",
        "| Rank | Score | Issue | Title | Status | Unblocks | Depth | Resources | Directly unlocks |",
        "| ---: | ---: | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for i, n in enumerate(result.get("open_frontier_ranked", []), 1):
        out.append(
            f"| {i} | {n['priority_score']} | {_issue_link(n['id'], n.get('url'))} | {_md_cell(n['title'])} | {n['status']} | "
            f"{n['transitive_unblocks_count']} | {n['critical_path_remaining_depth']} | {_resources_cell(n['holds'], n['meters'], '—')} | "
            f"{', '.join(n['directly_unlocks']) or '—'} |"
        )
    out += ["", "### Conflict-Free git-locks Batch", ""]
    for b in result.get("conflict_free_frontier_batch", []):
        out.append(
            f"- {_issue_link(b['id'], b.get('url'))} {_md_cell(b['title'])} — {_resources_cell(b['holds'], b['meters'], 'no resources')}"
        )
    out += ["", "## Task Checklist by Wave", ""]
    for wname, items in waves.items():
        out += [f"### {wname}", ""]
        for n in items:
            out.append(
                f"- [ ] {_issue_link(n['id'], n.get('url'))} {_md_cell(n['title'])} ({n['status']})"
            )
        out.append("")
    out += ["## Task Checklist by Workstream (`area:*`)", ""]
    streams: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in by_id.values():
        streams[n.get("workstream") or "unassigned"].append(n)
    for ws in sorted(streams):
        out += [f"### {ws}", ""]
        for n in sorted(streams[ws], key=lambda x: id_sort_key(x["id"])):
            out.append(f"- [ ] {_issue_link(n['id'], n.get('url'))} {_md_cell(n['title'])}")
        out.append("")
    out += [
        "## Transitively-Reduced Dependency DAG",
        "",
        "```mermaid",
        render_mermaid_flowchart(result),
        "```",
        "",
    ]
    out += [
        "## Prerequisite Edge Accounting",
        "",
        "| Blocker | Blocked | Evidence |",
        "| --- | --- | --- |",
    ]
    for e in result.get("edges", []):
        out.append(f"| {e['from']} | {e['to']} | {_md_cell(e['evidence'])} |")
    if result.get("transitive_redundant_edges_removed"):
        out += [
            "",
            "Recorded on GitHub but implied by a longer path (kept there as evidence, omitted from the reduced DAG):",
            "",
        ]
        for e in result["transitive_redundant_edges_removed"]:
            out.append(f"- {e['from']} → {e['to']} (via {e['implied_via']})")
    out += ["", ROADMAP_END]
    return "\n".join(out)
