"""Read complete edit histories with bounded pagination and checked fields."""

from __future__ import annotations

from collections.abc import Generator, Iterable
from contextlib import closing
from dataclasses import dataclass

from .github_history_values import EditHistory, HistoryEditor, HistoryPage, parse_history_page
from .github_json import parse_json
from .issue_refs import IssueRef, node_id
from .process import run_cmd_checked

# A single response binds each page's editor evidence to its returned body.
# Issue #1 owns detecting a body change between different history pages.
EDIT_HISTORY_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!,$after:String){"
    "repository(owner:$owner,name:$name){issue(number:$number){body "
    "userContentEdits(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{editor{login __typename}}}}}}"
)


@dataclass(frozen=True)
class HistoryLimits:
    """Bound aggregate history work even when every individual page is small."""

    max_pages: int = 100
    max_editors: int = 10_000

    def __post_init__(self) -> None:
        """Allow stricter budgets without permitting a disabled global ceiling."""
        for name, value, ceiling in (
            ("pages", self.max_pages, 100),
            ("editors", self.max_editors, 10_000),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                message = f"history {name} limit must be a positive integer at most {ceiling}"
                raise ValueError(message)


def collect_history(pages: Iterable[HistoryPage], limits: HistoryLimits) -> EditHistory:
    """Admit a terminal page within both budgets; never return an incomplete prefix."""
    body: str | None = None
    editors: list[HistoryEditor] = []
    cursors: set[str] = set()
    for count, page in enumerate(pages, start=1):
        if len(editors) + len(page["editors"]) > limits.max_editors:
            message = f"edit history exceeds {limits.max_editors} editors"
            raise ValueError(message)
        if body is None:
            body = page["body"]
        editors.extend(page["editors"])
        cursor = page["next_cursor"]
        if cursor is None:
            return {"body": body, "editors": editors}
        if cursor in cursors:
            message = "edit history repeated a pagination cursor; refusing incomplete history"
            raise ValueError(message)
        cursors.add(cursor)
        if count >= limits.max_pages:
            message = f"edit history exceeds {limits.max_pages} pages"
            raise ValueError(message)
    message = "edit history ended without a terminal page"
    raise ValueError(message)


def _history_pages(repo: str, ref: IssueRef) -> Generator[HistoryPage, None, None]:
    """Yield checked pages until the collector closes on termination or refusal."""
    owner, name = ref[0].split("/", 1)
    after: str | None = None
    while True:
        command = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={EDIT_HISTORY_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={ref[1]}",
        ]
        if after is not None:
            command += ["-f", f"after={after}"]
        ok, raw, error = run_cmd_checked(command, cwd=repo)
        if not ok:
            raise ValueError(error or "command failed")
        problems: list[dict[str, str]] = []
        decoded = parse_json(raw, "edit history", problems)
        if problems:
            raise ValueError(problems[0]["error"])
        page = parse_history_page(decoded)
        after = page["next_cursor"]
        yield page


def gh_issue_edit_history(
    repo: str, ref: IssueRef, errors: list[dict[str, str]], *, limits: HistoryLimits | None = None
) -> EditHistory | None:
    """Read complete history or record a source-specific run error without partial data."""
    source = f"gh api graphql (edit history of {node_id(*ref)})"
    try:
        with closing(_history_pages(repo, ref)) as pages:
            return collect_history(pages, limits or HistoryLimits())
    except (TypeError, ValueError) as error:
        errors.append({"source": source, "error": f"GraphQL edit history: {error}"})
        return None
