"""Build typed, owned issue fixtures without claiming production admission."""

from __future__ import annotations

from collections.abc import Sequence

from fixture_models import FakeClosingReference, FakeIssue, FakeState, IssueOptions

HOME = "flyingrobots/geordi"
ECHO = "flyingrobots/echo"
BUNNY = "flyingrobots/bunny"
STRANGER = "mallory"


def fm(
    reference: str,
    *,
    kind: str = "task",
    blocked_by: Sequence[str] = (),
    children: Sequence[str] | None = None,
    extra: str = "",
) -> str:
    """Build the original fixture frontmatter and its stable prose suffix."""
    lines = [".dag: issue-dag/2", f".id: {reference}", f".kind: {kind}"]
    if kind == "task":
        lines += [".type: feature", ".blocked_by: [" + ", ".join(blocked_by) + "]"]
    if children is not None:
        lines.append(".children: [" + ", ".join(children) + "]")
    if extra:
        lines.append(extra)
    lines.append("area: notes are free")
    return "```yaml\n" + "\n".join(lines) + "\n```\n\n# Feature\n\nBody text.\n"


def issue(
    identifier: int, title: str, body: str, *, options: IssueOptions | None = None
) -> FakeIssue:
    """Keep fixture defaults and explicitly supplied author/PR fields unchanged."""
    fields = options or {}
    result: FakeIssue = {
        "id": identifier,
        "title": title,
        "body": body,
        "state": fields.get("state", "open"),
        "state_reason": fields.get("reason"),
        "labels": [],
    }
    author, association, editors = (
        fields.get("author"),
        fields.get("association"),
        fields.get("editors"),
    )
    if author is not None:
        result["author"] = author
    if association is not None:
        result["association"] = association
    if editors is not None:
        result["editors"] = editors
    if "author_type" in fields:
        result["author_type"] = fields["author_type"]
    if "is_pr" in fields:
        result["is_pr"] = fields["is_pr"]
    return result


def closing(number: int, slug: str = HOME) -> FakeClosingReference:
    """Build a qualified closing reference with the repository's actual owner."""
    owner, name = slug.split("/")
    return {"number": number, "repository": {"name": name, "owner": {"login": owner}}}


def plan_state() -> FakeState:
    """Home roadmap #9 with children in three repositories; echo#6 blocks nothing at home."""
    return {
        "home": HOME,
        "blocked_by": {},
        "issues": {
            f"{HOME}#9": issue(
                109,
                "Roadmap",
                fm(
                    f"{HOME}#9",
                    kind="container",
                    children=[f"{HOME}#1", f"{HOME}#2", f"{ECHO}#5", f"{ECHO}#6", f"{HOME}#110"],
                ),
            ),
            f"{HOME}#1": issue(101, "Home one", fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5"])),
            f"{HOME}#2": issue(102, "Home two", fm(f"{HOME}#2", blocked_by=[f"{HOME}#1"])),
            f"{HOME}#110": issue(110, "Home 110", fm(f"{HOME}#110", blocked_by=[f"{BUNNY}#110"])),
            f"{ECHO}#5": issue(5005, "Echo five", fm(f"{ECHO}#5", blocked_by=[f"{BUNNY}#7"])),
            f"{ECHO}#6": issue(5006, "Echo six", fm(f"{ECHO}#6", blocked_by=[f"{ECHO}#5"])),
            f"{BUNNY}#110": issue(9110, "Bunny 110, no frontmatter", "Plain body."),
            f"{BUNNY}#7": issue(
                9007,
                "Bunny seven, closed",
                fm(f"{BUNNY}#7"),
                options={"state": "closed", "reason": "completed"},
            ),
        },
    }
