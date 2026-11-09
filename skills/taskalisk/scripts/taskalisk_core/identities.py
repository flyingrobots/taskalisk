"""Normalize actor identities and parse CODEOWNERS names."""

from __future__ import annotations

import re

BOT_KEY_PREFIX = "bot:"


def normalize_login(login: str, actor_type: str | None = None) -> str:
    """Keep one comparison key per identity while separating bots from humans.

    REST names a bot `x[bot]`, GraphQL `x` with `__typename: Bot`, and the CLI
    `app/x`; all become `bot:x`. A human `x` remains `x`. Allowlist a bot as
    `x[bot]` or `app/x` so its name cannot also trust a human account.
    """
    key = login.lower()
    is_bot = actor_type == BOT_TYPENAME
    if key.startswith("app/"):
        key, is_bot = key[len("app/") :], True
    if key.endswith("[bot]"):
        key, is_bot = key[: -len("[bot]")], True
    return BOT_KEY_PREFIX + key if is_bot else key


OWNER_RE = re.compile(r"[A-Za-z0-9_.-]+")

SLUG_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

BOT_TYPENAME = "Bot"


def parse_codeowners(text: str) -> tuple[set[str], list[str]]:
    """Return (logins, teams) named as owners. Email owners are ignored."""
    logins: set[str] = set()
    teams: list[str] = []
    for raw in text.splitlines():
        tokens = raw.split("#", 1)[0].split()
        for token in tokens[1:]:
            if not token.startswith("@"):
                continue
            name = token[1:]
            if "/" in name:
                if name not in teams:
                    teams.append(name)
            elif name:
                logins.add(name)
    return logins, teams
