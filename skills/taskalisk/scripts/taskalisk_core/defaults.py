"""Own compiler status, ranking and inventory defaults."""

from __future__ import annotations

# Completed = GitHub closed. GitHub treats a closed blocker as satisfied,
# whatever the reason; "not_planned" parents are reported separately.
COMPLETED_STATUSES = {"merged", "closed", "done", "completed"}

IN_FLIGHT_STATUSES = {"ready-to-merge", "in-progress", "active", "wip", "in-review"}

FRONTIER_STATUS = "open-frontier"

BLOCKED_STATUS = "blocked"


MERGED_HINT = "(merged)"

DEFAULT_MIN_CONFIDENCE = 0.7

DENSITY_BAND = (0.01, 0.50)

GH_ISSUE_LIST_LIMIT = 1000

GH_PR_LIST_LIMIT = 500

SHORT_SHA_LEN = 9

MERMAID_TITLE_MAX = 48


PRIORITY_IN_FLIGHT_WEIGHT = 1000

# Parked work has a recoverable branch: resuming it costs less than starting
# fresh, so it ranks above untouched work but below work already in flight.
PRIORITY_PARKED_WEIGHT = 500

PRIORITY_DESCENDANTS_WEIGHT = 100

PRIORITY_DEPTH_WEIGHT = 10


PARKED_STATUS = "parked"
