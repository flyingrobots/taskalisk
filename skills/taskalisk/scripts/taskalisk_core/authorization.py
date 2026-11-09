"""Decide issue and editor admission within the trusted repository scope."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .identities import BOT_KEY_PREFIX, normalize_login, parse_codeowners
from .process import run_cmd_checked

# --------------------------------------------------------------------------- #
# Trust (docs/threat-model.md, controls C1-C4 and C18)
# --------------------------------------------------------------------------- #

# OWNER is the only association that implies write access by itself. MEMBER and
# COLLABORATOR include read- and triage-level people, so they go through the
# permission check like everyone else.
TRUSTED_ASSOCIATIONS = {"OWNER"}

# Associations under which a permission lookup can still say "write"; any other
# association means GitHub already reports no collaborator standing.
COLLABORATOR_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}

TRUSTED_PERMISSIONS = {"admin", "maintain", "write"}

CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


class TrustPolicy:
    """Who may be a node. Association counts only inside the repository scope (C2)."""

    def __init__(
        self,
        repo: str,
        home_slug: str,
        owners: list[str],
        repos: list[str],
        logins: list[str],
        codeowners: bool,
        errors: list[dict[str, str]],
    ):
        # GitHub owner, repository and login names are case-insensitive; compare them folded.
        self.repo = repo
        self.owners = {home_slug.split("/", 1)[0].lower(), *(o.lower() for o in owners)}
        self.repos = {r.lower() for r in repos}
        self.logins = {normalize_login(l) for l in logins}
        self.codeowners = codeowners
        self.errors = errors
        self._repo_logins: dict[str, set[str]] = defaultdict(set)
        self._teams: dict[str, list[str]] = {}
        self._codeowners_loaded: set[str] = set()
        self._collaborator_cache: dict[tuple[str, str], tuple[bool, str]] = {}

    def in_scope(self, slug: str) -> bool:
        return slug.lower() in self.repos or slug.split("/", 1)[0].lower() in self.owners

    def describe(self) -> dict[str, Any]:
        return {
            "owners": sorted(self.owners),
            "repos": sorted(self.repos),
            "logins": sorted(self.logins),
            "codeowners": {slug: sorted(v) for slug, v in sorted(self._repo_logins.items())}
            if self.codeowners
            else None,
            "codeowners_teams_not_expanded": dict(sorted(self._teams.items())),
        }

    def login_trusted(
        self,
        slug: str,
        login: str | None,
        association: str | None = None,
        actor_type: str | None = None,
    ) -> tuple[bool, str]:
        """A bot is trusted only by explicit allowlist; a person by allowlist, CODEOWNERS, OWNER association, or write permission."""
        if not login:
            return False, "no login (deleted user)"
        login_key = normalize_login(login, actor_type)
        if login_key in self.logins:
            return True, "allowlisted"
        if login_key.startswith(BOT_KEY_PREFIX):
            return False, "bot actors are trusted only by --trust <login>[bot]"
        if not self.in_scope(slug):
            return False, f"{slug} is outside the trusted repositories"
        self._load_codeowners(slug)
        if login_key in self._repo_logins.get(slug.lower(), set()):
            return True, "CODEOWNERS"
        if association in TRUSTED_ASSOCIATIONS:
            return True, f"association {association}"
        if association is not None and association not in COLLABORATOR_ASSOCIATIONS:
            # GitHub already says this person has no collaborator standing here; no lookup needed.
            return False, f"association {association}"
        return self._collaborator(slug, login)

    def author_trusted(self, slug: str, meta: dict[str, Any]) -> tuple[bool, list[str]]:
        """The author check needs only the REST issue object, so a stranger's issue costs no further query."""
        ok, why = self.login_trusted(
            slug, meta.get("author"), meta.get("association"), meta.get("author_type")
        )
        return ok, [] if ok else [f"author {meta.get('author') or '(none)'}: {why}"]

    def editors_trusted(
        self,
        slug: str,
        author: str | None,
        editors: list[dict[str, Any]],
        author_type: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Every body editor other than the (already trusted) author must be trusted.
        Identities are compared with their actor type, so a bot sharing the author's login is still checked."""
        reasons: list[str] = []
        seen: set[str | None] = {normalize_login(author, author_type) if author else None}
        for editor in editors:
            login = editor.get("login")
            key = normalize_login(login, editor.get("type")) if login else None
            if key in seen:
                continue
            seen.add(key)
            ok, why = self.login_trusted(slug, login, None, editor.get("type"))
            if not ok:
                reasons.append(f"editor {login or '(none)'}: {why}")
        return not reasons, reasons

    def _collaborator(self, slug: str, login: str) -> tuple[bool, str]:
        """Trusted only with write, maintain or admin permission. A lookup that cannot run is a run error (exit 2):
        a silently untrusted collaborator would hide trusted work as opaque blockers."""
        key = (slug.lower(), login.lower())
        if key not in self._collaborator_cache:
            source = f"gh api repos/{slug}/collaborators/{login}/permission"
            ok, raw, err = run_cmd_checked(
                [
                    "gh",
                    "api",
                    f"repos/{slug}/collaborators/{login}/permission",
                    "--jq",
                    ".permission",
                ],
                cwd=self.repo,
            )
            if ok and raw in TRUSTED_PERMISSIONS:
                self._collaborator_cache[key] = (True, f"permission {raw}")
            elif ok:
                self._collaborator_cache[key] = (
                    False,
                    f"permission {raw or 'none'} on {slug} is below write",
                )
            elif "HTTP 404" in err:
                self._collaborator_cache[key] = (False, f"not a collaborator of {slug}")
            else:
                self.errors.append({"source": source, "error": err or "command failed"})
                self._collaborator_cache[key] = (
                    False,
                    "permission lookup failed; see github_errors",
                )
        return self._collaborator_cache[key]

    def _load_codeowners(self, slug: str) -> None:
        """Read CODEOWNERS from the default branch of a scope repository (C18)."""
        slug_key = slug.lower()
        if not self.codeowners or slug_key in self._codeowners_loaded:
            return
        self._codeowners_loaded.add(slug_key)
        for path in CODEOWNERS_PATHS:
            source = f"gh api repos/{slug}/contents/{path}"
            ok, raw, err = run_cmd_checked(
                [
                    "gh",
                    "api",
                    f"repos/{slug}/contents/{path}",
                    "-H",
                    "Accept: application/vnd.github.raw+json",
                ],
                cwd=self.repo,
            )
            if ok:
                logins, teams = parse_codeowners(raw)
                self._repo_logins[slug_key] |= {l.lower() for l in logins}
                if teams:
                    self._teams[slug_key] = teams
                return
            if "HTTP 404" not in err:
                self.errors.append({"source": source, "error": err or "command failed"})
                return
