#!/usr/bin/env python3
"""parley_emit: a writer for the Parley output protocol (spec v0.2), in one vendorable file.

A tool conforms by defining itself with `define_tool` and running its handler under `main`; the
writer owns everything the protocol asks of a program that is not the program's own result: the
bootstrap line, the receipt and where it goes, the single sequence across streams, `inv`,
redaction, sidecars, hygiene, retention, discovery, the `--human` renderer, the top-level handler
and the exit status.

Standard library only, Python 3.9 or later. Vendor it by copying this one file; pin the copy by
the digest `python3 parley_emit.py --vendor-info` prints. The draft schemas it ships are embedded
below, byte for byte, pinned by commit and digest (spec section 4.5).

This file is the Python twin of the TypeScript writer `@flyingrobots/parley-emit` in the same
repository; where the two differ, `packages/parley-emit-py/README.md` names the difference.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import traceback
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

__version__ = "0.3.0"
SPEC_VERSION = "0.2.1"

REDACTED = "[redacted]"
SIDECAR_THRESHOLD = 65_536
CODE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+\Z")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*\Z")
_ENVELOPE_KEYS = ("t", "seq", "run", "_schema")
# Incomplete receipts (no end line) older than this may be deleted by retention; younger ones may
# still be in flight.
_INCOMPLETE_GRACE_MS = 24 * 60 * 60 * 1000

# Writer-owned string fields never scrubbed in a writer-built record: digests, which a secret cannot
# occur in except by coincidence of hex, and the public identity a writer-built record carries (the
# tool's name and version, a command's name, a schema's id and version, and the code of a diagnostic
# the writer itself raises). A tool's own diagnostic is not writer-built; its code is scrubbed.
#
# `op` is the same kind of thing: a bookkeeping entry's operation is one of the protocol's own
# tokens (`create`, `append`, `delete`), which `parley.command` enumerates. A declared secret whose
# value is `create` is a coincidence with a public word, and replacing the word would publish a
# line the released schema rejects.
#
# `error` is an input descriptor's diagnostic code, whose pattern `parley.receipt.inputs` states:
# the writer's own `input.unreadable` or `input.unread`, or a code the tool gave
# `input_unreadable`, which is replaced by the writer's token there if it carries a declared secret
# value. No other writer-built record has a field of that name.
#
# What a writer-built record's scrub leaves alone, in full: the string under each key here; its
# numbers and booleans; its field names (`rename_keys`); the head's `redacted` object and a
# `schema` line's document (`verbatim`); and the envelope. Every other string in it is scrubbed.
DIGEST_KEYS = frozenset(["sha256", "inv", "tool", "v", "name", "id", "version", "code", "op", "error"])
_INPUT_UNREADABLE = "input.unreadable"

SCHEMA_IDS: Dict[str, Dict[str, str]] = {
    "bootstrap": {"id": "parley.run.bootstrap", "version": "1.1.1"},
    "head": {"id": "parley.receipt.head", "version": "2.0.0"},
    "step": {"id": "parley.receipt.step", "version": "1.0.0"},
    "inputs": {"id": "parley.receipt.inputs", "version": "1.0.0"},
    "error": {"id": "parley.error", "version": "2.0.0"},
    "warning": {"id": "parley.warning", "version": "1.0.0"},
    "end": {"id": "parley.end", "version": "1.0.0"},
    "startup_failed": {"id": "parley.startup.failed", "version": "1.0.0"},
    "sidecar": {"id": "parley.sidecar", "version": "1.0.0"},
    "redaction": {"id": "parley.redaction", "version": "1.0.0"},
    "command": {"id": "parley.command", "version": "1.0.0"},
    "schema": {"id": "parley.schema", "version": "1.0.0"},
    "page": {"id": "parley.page", "version": "1.0.0"},
}
# Every message type this writer can emit, so `--schema` lists exactly these (spec section 4.2).
# It writes no `parley.history.transform`: the shared history stream is not implemented here.
WRITER_SCHEMAS: Tuple[Dict[str, str], ...] = tuple(SCHEMA_IDS.values())
# The error types every command can produce unless it declares its own: a structured error, and the
# startup failure a run that cannot bootstrap emits instead (spec section 3.2).
DEFAULT_ERRORS: Tuple[Dict[str, str], ...] = (SCHEMA_IDS["error"], SCHEMA_IDS["startup_failed"])

_OWN_FLAGS = frozenset(["--human", "--humanize", "--dry-run", "--schema", "--help", "-h"])

Json = Any
Record = Dict[str, Any]
SchemaRef = Union[Tuple[str, str], Mapping[str, str]]


class ParleyClosed(RuntimeError):
    """Raised by any emission after `end`: nothing may follow it (spec section 3.3)."""

    def __init__(self) -> None:
        super().__init__("the run has ended; nothing may follow end (spec section 3.3)")


# The code of the error a writer reports in place of a record redaction made invalid
# (spec section 5.3, flyingrobots/parley#131).
REDACTION_CONFLICT_CODE = "redaction.schema_conflict"


class ParleyRedactionConflict(RuntimeError):
    """Raised by an emission whose record redaction made invalid under its declared schema (spec
    section 5.3, flyingrobots/parley#131). By the time it is raised the writer has already
    reported the structured error, written nothing of the record and taken no `seq` for it, and
    the run will end with status 4. It is raised, like every other refusal to emit, because the
    call has no record to return a `seq` for and the handler should not carry on as though its
    answer had been delivered; `main` does not report it a second time. A handler may catch it
    and continue: the status stays 4.

    The message names the fields by JSON Pointer and the schema pair. It never carries a value, a
    validator's message or any part of the schema, and its message and `pointers` are scrubbed
    exactly as the published error line's `problem` and `detail.at` are, so it is safe to log: a
    pointer can name a property the scrub renamed, and that name can be the secret. `schema` is
    the declared pair as `{"id", "version"}` and `pointers` the JSON Pointer of each field that no
    longer validates."""

    def __init__(self, schema: Mapping[str, str], pointers: Sequence[str], message: str) -> None:
        super().__init__(message)
        self.schema: Dict[str, str] = {"id": schema["id"], "version": schema["version"]}
        self.pointers: List[str] = list(pointers)


# The code of the error a writer reports in place of a record redaction changed whose schema
# document it holds and cannot evaluate (spec section 5.3, flyingrobots/parley#144).
REDACTION_UNCHECKED_CODE = "redaction.schema_unchecked"


class ParleyRedactionUnchecked(ParleyRedactionConflict):
    """Raised by an emission whose record redaction changed, under a schema document the writer
    holds and cannot evaluate: one that uses a construct outside the bounded checker. The writer
    cannot show the redacted record is valid under its declared schema, so it withholds it exactly
    as it withholds a conflict (spec section 5.3, flyingrobots/parley#144): the structured error
    `redaction.schema_unchecked` is already reported, nothing of the record was written, no `seq`
    was taken and the run will end with status 4.

    It is a `ParleyRedactionConflict`, so a handler that already treats the conflict needs no
    second branch; `pointers` is empty, because no field was shown to be invalid. `redacted` is
    the JSON Pointer of each value the scrub replaced. `construct` names the first thing in the
    schema the checker does not implement, as `schema_subset_gap` reports it; it is in this
    exception and its message only, never on the error line, which carries no part of the schema.
    It is None, and absent from the message, if it would carry a declared secret value. The
    message never carries a value."""

    def __init__(self, schema: Mapping[str, str], redacted: Sequence[str], construct: Optional[str], message: str) -> None:
        super().__init__(schema, [], message)
        self.redacted: List[str] = list(redacted)
        self.construct: Optional[str] = construct


# ---- the embedded schemas ------------------------------------------------------------------
# Generated by scripts/sync_schemas.py from schemas/ at the repository root. Do not edit by hand.
# BEGIN SCHEMAS
SCHEMA_SOURCE: Dict[str, Any] = {"commit": "a2e902472f588416624717afcb4ef1e93b9857fd", "files": {
    "parley.cache.hit.schema.json": "d5b5b7a8571a3c74f99d49de1fb75b6ce056f18438d7a9f83e976dd82178c4e8",
    "parley.command.schema.json": "b496c818c7025cecb878dc50f7b97693692787609fc6da39eebd5a9da49c9782",
    "parley.end.schema.json": "bebd27748368241cef9bdbc6bff3efa48ec82a5798c246a967cf73d338318bab",
    "parley.error.schema.json": "66970cbe1a245947bbec234cf8f4cd2146a7c69fecd4f555bec3b1174f874b51",
    "parley.history.transform.schema.json": "36b03c4c80fa55f2584f61b0e2c1a3453fc2c742da8720510cb99fafd6861fcf",
    "parley.lens.schema.json": "31e5f262da10026abaee92f34f5d21a1697afc94c505e5794e216c96215aff25",
    "parley.page.schema.json": "86ef95b18e7ec1cddba6d337c99e8538da179ba69b000aecd6b683531a0594a6",
    "parley.query.schema.json": "b7220369904ce9187b8cecc64078ba445e179c6b206b6f9f4720a2e935ed13dc",
    "parley.receipt.head.schema.json": "5728ae69c9b5abcce318bc86ecf2850936e9f09122a8f05453096b7878de79cd",
    "parley.receipt.inputs.schema.json": "dbc16f662e82e8eb5024cb1454c80fc01aae8554c918427559564f91191727f7",
    "parley.receipt.step.schema.json": "4bd32d020ec12f3ad5dba70031bbc70f5e5dc3f04dc20da7241b5103f112c3af",
    "parley.redaction.schema.json": "8e9ab89f468456d27ad2eea0a5a366c4ff4de96471d87914af7f48715ae82d54",
    "parley.run.bootstrap.schema.json": "bb565c59c45363e35820b77ed2bff68a34634b43b5892bb9092b401e56fce6a1",
    "parley.schema.schema.json": "c3049368c90686b3f6cf5a32d10851a457f229b46dd2788471828a5f364b243f",
    "parley.sidecar.schema.json": "fa159ce26f619a4bcb49275e2e9993b85ac75d3c8e5c28fb30917db92292fa1a",
    "parley.startup.failed.schema.json": "59dc383258e3ac62e717553497fe8a6a0b7e02ccb4bec44160242a0ef4c70ef1",
    "parley.warning.schema.json": "15f11264c7233c15d89f69c748d78adbe30fa7268a359a071c401950404ef619",
}}
_SCHEMA_TEXT: Dict[str, str] = {
    "parley.cache.hit.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.cache.hit/1.0.0\",\n  \"title\": \"parley cache hit\",\n  \"description\": \"Emitted when a program answers from a prior receipt instead of recomputing (spec \\u00a72.3).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"inv\",\n    \"served_run\",\n    \"receipt\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"cache.hit\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1).\"\n    },\n    \"inv\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"served_run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The run whose receipt supplied the answer.\"\n    },\n    \"receipt\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"That receipt's path.\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.cache.hit\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.command.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.command/1.0.0\",\n  \"title\": \"parley command\",\n  \"description\": \"A command's description: name, intent, declared effects, declared secrets and the message types it can emit (spec \\u00a74.1 to \\u00a74.3). Emitted by --schema and --help.\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"name\",\n    \"intent\",\n    \"effects\",\n    \"secrets\",\n    \"emits\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"command\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1).\"\n    },\n    \"name\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"intent\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"One line: what question the command answers.\"\n    },\n    \"effects\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"reads\",\n        \"writes\",\n        \"network\",\n        \"idempotent\",\n        \"bookkeeping\"\n      ],\n      \"properties\": {\n        \"reads\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          }\n        },\n        \"writes\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"description\": \"Subject-matter writes only (spec \\u00a74.3).\"\n        },\n        \"network\": {\n          \"type\": \"boolean\"\n        },\n        \"idempotent\": {\n          \"type\": \"boolean\"\n        },\n        \"bookkeeping\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"object\",\n            \"required\": [\n              \"op\",\n              \"scope\"\n            ],\n            \"properties\": {\n              \"op\": {\n                \"enum\": [\n                  \"create\",\n                  \"append\",\n                  \"delete\"\n                ]\n              },\n              \"scope\": {\n                \"type\": \"string\",\n                \"minLength\": 1\n              }\n            }\n          },\n          \"description\": \"Evidence writes: receipts, sidecars, the local ignore file, retention (spec \\u00a74.3).\"\n        }\n      }\n    },\n    \"secrets\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"string\",\n        \"minLength\": 1\n      },\n      \"description\": \"Arguments by flag, environment variables by name, and credential sources by logical name, whose values are secrets (spec \\u00a74.3, \\u00a75.3).\"\n    },\n    \"emits\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"object\",\n        \"required\": [\n          \"id\",\n          \"version\"\n        ],\n        \"properties\": {\n          \"id\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"version\": {\n            \"type\": \"string\",\n            \"pattern\": \"^(0|[1-9][0-9]*)\\\\.(0|[1-9][0-9]*)\\\\.(0|[1-9][0-9]*)$\"\n          }\n        }\n      },\n      \"description\": \"Message types this command can emit, by exact (id, version).\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.command\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.end.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.end/1.0.0\",\n  \"title\": \"parley end\",\n  \"description\": \"The terminal event of a run that bootstrapped: written to stdout and to the receipt as one event. Its seq is the run's final sequence number (spec \\u00a73.3).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"status\",\n    \"receipt\",\n    \"redacted\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"end\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1).\"\n    },\n    \"status\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"maximum\": 255,\n      \"not\": {\n        \"const\": 3\n      },\n      \"description\": \"The exit status the process is about to exit with (spec \\u00a73.4); never 3, since a run that could not bootstrap has no end.\"\n    },\n    \"receipt\": {\n      \"type\": \"string\",\n      \"pattern\": \"^/\",\n      \"minLength\": 2,\n      \"description\": \"The receipt path, absolute, as the bootstrap line declared it.\"\n    },\n    \"redacted\": {\n      \"type\": \"boolean\",\n      \"description\": \"True exactly when the head carries redacted or any redaction event was emitted (spec \\u00a73.3).\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.end\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.error.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.error/2.0.0\",\n  \"title\": \"parley error\",\n  \"description\": \"Errors are data. measured, limit and remedy are what make an error actionable in one step rather than several.\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"code\",\n    \"problem\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"error\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter; 0 is the bootstrap line (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to. Required on every line so a detached line can still be attributed (spec \\u00a71.3).\"\n    },\n    \"code\": {\n      \"type\": \"string\",\n      \"pattern\": \"^[a-z0-9_]+(\\\\.[a-z0-9_]+)+$\",\n      \"description\": \"Stable identifier: two or more dot-separated segments of lowercase letters, digits and underscores (spec \\u00a76). Never a prose message.\"\n    },\n    \"problem\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"What is wrong, in one sentence.\"\n    },\n    \"measured\": {\n      \"description\": \"The value observed, when the failure is a threshold.\"\n    },\n    \"limit\": {\n      \"description\": \"The threshold that was not met.\"\n    },\n    \"remedy\": {\n      \"type\": \"string\",\n      \"description\": \"The lever to pull. Omit rather than invent one.\"\n    },\n    \"remedy_target\": {\n      \"type\": \"string\",\n      \"description\": \"What the remedy applies to.\"\n    },\n    \"retryable\": {\n      \"type\": \"boolean\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.error\"\n        },\n        \"version\": {\n          \"const\": \"2.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.history.transform.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.history.transform/1.0.0\",\n  \"title\": \"parley history transform\",\n  \"description\": \"The opening line of a projected copy of a run on the shared history stream: every line of this run that follows on this stream is a projection of the receipt copy by the named transform, so a reader can tell a projected copy from a whole one and by what (spec \u00a78, informative). Stream only: the receipt copy is never projected and never carries this line.\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"name\",\n    \"sha256\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"history.transform\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \u00a71.3). This line takes a seq of its own and reaches no other sink, so the receipt copy has no line at this seq.\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution whose copy on this stream is a projection (spec \u00a72.1).\"\n    },\n    \"name\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"What the transform is called: the name its configuration gave it, or the function's own name.\"\n    },\n    \"sha256\": {\n      \"type\": \"string\",\n      \"pattern\": \"^[0-9a-f]{64}$\",\n      \"description\": \"SHA-256, hex, of the transform's source text as the runtime renders it. It tells two projections apart and pins which one wrote this copy; it is not a build identity, and nothing fetches it.\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.history.transform\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \u00a74.5, \u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.lens.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.lens/1.1.0\",\n  \"title\": \"parley lens\",\n  \"description\": \"The lens a result carries: the asker, the view, the budget and the window that produced it, the query it answers, a stated bound on what the view loses, and the records it was built from by (run, seq) (spec \u00a79, informative; decided in flyingrobots/parley#46). One lens line precedes the result it describes, so a later reader knows what it is looking at and can get back to the records.\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"query\",\n    \"asker\",\n    \"view\",\n    \"budget\",\n    \"window\",\n    \"loss\",\n    \"records\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"lens\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to: the read itself, not the runs being read (spec \u00a72.1).\"\n    },\n    \"session\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"Working period spanning runs. Supplied by the caller or inherited; never invented (spec \u00a72.1).\"\n    },\n    \"query\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"run\",\n        \"seq\"\n      ],\n      \"properties\": {\n        \"run\": {\n          \"type\": \"string\",\n          \"minLength\": 1\n        },\n        \"seq\": {\n          \"type\": \"integer\",\n          \"minimum\": 1\n        }\n      },\n      \"description\": \"The recorded query this result answers, by (run, seq). Required: \u00a79 records every query, and a result whose query was not recorded cannot be audited.\"\n    },\n    \"asker\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"tool\"\n      ],\n      \"properties\": {\n        \"tool\": {\n          \"type\": \"string\",\n          \"minLength\": 1\n        },\n        \"cwd\": {\n          \"type\": \"string\",\n          \"pattern\": \"^/\",\n          \"minLength\": 2\n        },\n        \"task\": {\n          \"type\": \"string\",\n          \"minLength\": 1\n        }\n      },\n      \"description\": \"Echoed from the query: who the result is for.\"\n    },\n    \"view\": {\n      \"enum\": [\n        \"what-ran\",\n        \"what-failed\",\n        \"what-changed\",\n        \"how-it-decided\",\n        \"everything\"\n      ],\n      \"description\": \"The view this result is. Echoed from the query, from the same closed set.\"\n    },\n    \"budget\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"records\"\n      ],\n      \"properties\": {\n        \"records\": {\n          \"type\": \"integer\",\n          \"minimum\": 1\n        },\n        \"bytes\": {\n          \"type\": \"integer\",\n          \"minimum\": 1\n        },\n        \"ms\": {\n          \"type\": \"integer\",\n          \"minimum\": 1\n        }\n      },\n      \"description\": \"The budget actually applied, including a default the query did not supply. Constitutive, not decoration: two results computed under different budgets are not comparable, so a lens without it does not identify the view that produced the result.\"\n    },\n    \"window\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"from\",\n        \"to\"\n      ],\n      \"properties\": {\n        \"from\": {\n          \"type\": \"integer\",\n          \"minimum\": 0\n        },\n        \"to\": {\n          \"type\": \"integer\",\n          \"minimum\": 0\n        }\n      },\n      \"description\": \"The stretch of history the result covers, echoed from the query.\"\n    },\n    \"fold\": {\n      \"type\": \"boolean\",\n      \"description\": \"Echoed from the query, present exactly when the query states it (flyingrobots/parley#133). false: the read folded nothing, so loss.folded is 0 and no runs section carries folded because none was allowed to, not because no runs repeated. Two results over one window, one folded and one not, are not comparable, so a lens says which it is.\"\n    },\n    \"loss\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"bound\",\n        \"excluded\"\n      ],\n      \"properties\": {\n        \"bound\": {\n          \"enum\": [\n            \"none\",\n            \"count-only\"\n          ],\n          \"description\": \"What kind of statement the loss is. none: nothing in the window was left out, so the result and the window hold the same records and excluded must be 0. Not restricted to the identity view: a view orders a result and filters none of it (flyingrobots/parley#49), so any view whose result reached the end of its order lost nothing. count-only: the excluded count is all that is known, which is a weak proxy. A measured distortion bound needs a translator to measure it and is a later version of this schema.\"\n        },\n        \"excluded\": {\n          \"type\": \"integer\",\n          \"minimum\": 0,\n          \"description\": \"How many records in the window the view did not name, whatever left them out: the budget, or a fold (folded). A proxy and a weak one: one withheld record can matter more than fifty, so this count cannot bound what the view loses.\"\n        },\n        \"folded\": {\n          \"type\": \"integer\",\n          \"minimum\": 0,\n          \"description\": \"How many of excluded were left out because their run was folded into another run of the same invocation and the same result, rather than by the budget (flyingrobots/parley#79): the records of every run the fold left out. A runs section's folded.records counts those its own run stands for, so the sections' folded.records sum to this number unless the budget left a run that stands for others out of records; that run has no section, so the sum is then smaller and this count is all the lens says of its fold. It depends on the window, the view and fold, never on the budget, so excluded minus folded is what the budget cut. At most excluded, which a schema cannot check; a reader can. Optional so that lines written under the earlier drafts still validate; parley-read always writes it, 0 included.\"\n        }\n      },\n      \"description\": \"What the view loses against the records it was built from, so a later reader knows which questions this result can still answer and cannot mistake a digest for the whole. A digest that folded runs names fewer records than it stands for, and says how many in folded.\"\n    },\n    \"runs\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"object\",\n        \"required\": [\n          \"run\"\n        ],\n        \"properties\": {\n          \"run\": {\n            \"type\": \"string\",\n            \"minLength\": 1,\n            \"description\": \"The run this section is about: one that records names.\"\n          },\n          \"tool\": {\n            \"type\": \"string\",\n            \"minLength\": 1,\n            \"description\": \"The run's receipt head's tool (spec \u00a75), as the loader read it.\"\n          },\n          \"v\": {\n            \"type\": \"string\",\n            \"minLength\": 1,\n            \"description\": \"The run's receipt head's v (spec \u00a75), as the loader read it.\"\n          },\n          \"argv\": {\n            \"type\": \"array\",\n            \"items\": {\n              \"type\": \"string\"\n            },\n            \"description\": \"The run's receipt head's argv (spec \u00a75), already redacted there (spec \u00a75.3). Never cut part-way: when it does not fit the section's bound it is dropped whole and named in dropped.\"\n          },\n          \"resolved\": {\n            \"type\": \"object\",\n            \"description\": \"The run's receipt head's resolved (spec \u00a75): its interpretation after defaults, environment and path resolution, copied whole and already redacted there (spec \u00a75.3), so a reader can tell, say, which commits a run compared without opening the head (flyingrobots/parley#90). Its shape is the tool's; the reader chooses none of its keys. Never cut part-way: when it does not fit the section's bound it is dropped whole, first of all fields, and named in dropped. Absent when the window does not hold the head or the head's resolved is not an object.\"\n          },\n          \"inv\": {\n            \"type\": \"string\",\n            \"minLength\": 1,\n            \"description\": \"The run's inv (spec \u00a72.2): the head's, or else the window's receipt.inputs for the run. Absent when neither carries one; never a placeholder.\"\n          },\n          \"outcome\": {\n            \"enum\": [\n              \"failed\",\n              \"undetermined\",\n              \"succeeded\"\n            ],\n            \"description\": \"What the records in the window establish about the run: failed for an error, a startup failure or a non-zero end; succeeded for an end of 0 and nothing against it; undetermined otherwise (spec \u00a71.2a). It is the window's verdict, not the digest's: a run whose end the bound cut is still succeeded. Absent when the reader established none.\"\n          },\n          \"reason\": {\n            \"enum\": [\n              \"no_end_in_window\",\n              \"end_status_unusable\"\n            ],\n            \"description\": \"Why the outcome is undetermined, present exactly when it is. no_end_in_window: the window holds no end for the run, which cannot say whether the run ended later or never did. end_status_unusable: the window holds an end whose status is not a number.\"\n          },\n          \"head\": {\n            \"const\": \"not_in_window\",\n            \"description\": \"Present when the window does not hold the run's receipt head, so tool, v and argv are not known from it. Absent when it does.\"\n          },\n          \"folded\": {\n            \"type\": \"object\",\n            \"required\": [\n              \"others\",\n              \"records\"\n            ],\n            \"properties\": {\n              \"others\": {\n                \"type\": \"integer\",\n                \"minimum\": 1,\n                \"description\": \"How many other runs this section stands for, this run excluded: the section reads as this run plus others like it, so it stands for others + 1 runs (flyingrobots/parley#100).\"\n              },\n              \"records\": {\n                \"type\": \"integer\",\n                \"minimum\": 0,\n                \"description\": \"How many records of those other runs, in the window, the fold left out of records, this run's own excluded; each is counted in loss.excluded and loss.folded.\"\n              },\n              \"stands_for\": {\n                \"type\": \"array\",\n                \"minItems\": 1,\n                \"items\": {\n                  \"type\": \"string\",\n                  \"minLength\": 1\n                },\n                \"description\": \"The run ids of the other runs this section stands for, this run excluded, most recent first by the rule that makes this run the most recent of them: the latest t among each run's records in the window, then the greater run id, a run with no dated record last (flyingrobots/parley#133). It names runs, not records: the others' seq numbers are not listed and need not be this run's, so their records are read under a window that holds them with fold false, or opened by (run, seq) once their seq is known. As many as others, which a schema cannot check; a reader can. Optional, as every field a minor version adds is (spec \u00a74.5); parley-read always writes it, never shortens it, never drops it to fit the section's bound and does not count it against that bound. It is part of the line budget.bytes bounds: when the line cannot hold it whole, no record of this run is named and this section is absent, and loss.folded still counts the fold.\"\n              }\n            },\n            \"description\": \"Present when this run stands for other runs of the same invocation and the same result (flyingrobots/parley#79): runs with an equal inv (spec \u00a72.2) whose outcome, reason, end status, error, warning and startup-failure codes and head's resolved are equal too, and whose result records are equal one for one in seq order: the tool's own records and any other record the protocol does not define, each page, each sidecar by its bytes and sha256, and a read's own lens without its session and the query it names, compared without the envelope's t, seq and run (flyingrobots/parley#133). A top-level session on a record of the tool's own or on a page is that record's own field and is compared (flyingrobots/parley#146). Under a view whose surface holds decision records those are equal as well, compared the same way: receipt.step under how-it-decided and everything, cache.hit under those two and what-ran. A decision record of a kind the view's surface does not hold is not compared, so runs that differ only in such records still stand for one another. Every comparison here is of the records the window holds: two runs whose results in the window differ are a divergence (spec \u00a72.3) and do not stand for one another, and a run only partly inside the window is compared by the part the window holds, so runs that stand for one another under one window can differ under a wider one. A section marks a run the window did not hold whole in two cases: head not_in_window when the window does not hold the run's head, and outcome undetermined with reason no_end_in_window when it holds no end for the run and no failure either; a run the window shows to have failed is failed with or without its end, so its section does not say whether the window holds the end. This run is the most recent of them, by the latest t among each run's records in the window and, where those are equal, the greater run id; the others' records are not named, and stands_for lists the others' run ids. A run with no inv in the window, a run the window shows to be redacted (its head carries redacted, an end in the window states redacted true, or the window holds a redaction event of the run), and a run the window does not show to be unredacted, because it holds neither the run's receipt head nor an end that states redacted false, do not stand for another (spec \u00a71.2a, \u00a72.3). A run that stands for no other has no folded. Never dropped to fit the section's bound.\"\n          },\n          \"dropped\": {\n            \"type\": \"array\",\n            \"minItems\": 1,\n            \"items\": {\n              \"enum\": [\n                \"resolved\",\n                \"argv\",\n                \"inv\",\n                \"v\",\n                \"tool\"\n              ]\n            },\n            \"description\": \"The fields left out, whole, to bound the section's serialised JSON, in the order they were dropped, each at most once: resolved, then argv, then inv, then v, then tool. The bound is the reader's to state (parley-read: 512 UTF-8 bytes); a string or an object is never cut part-way.\",\n            \"maxItems\": 5\n          }\n        },\n        \"if\": {\n          \"type\": \"object\",\n          \"required\": [\n            \"outcome\"\n          ],\n          \"properties\": {\n            \"outcome\": {\n              \"const\": \"undetermined\"\n            }\n          }\n        },\n        \"then\": {\n          \"type\": \"object\",\n          \"required\": [\n            \"reason\"\n          ],\n          \"properties\": {\n            \"reason\": {\n              \"enum\": [\n                \"no_end_in_window\",\n                \"end_status_unusable\"\n              ]\n            }\n          }\n        },\n        \"else\": {\n          \"not\": {\n            \"type\": \"object\",\n            \"required\": [\n              \"reason\"\n            ],\n            \"properties\": {\n              \"reason\": {\n                \"enum\": [\n                  \"no_end_in_window\",\n                  \"end_status_unusable\"\n                ]\n              }\n            }\n          }\n        }\n      },\n      \"description\": \"One section per run that records names, in the order records first names it, and none for any other run (flyingrobots/parley#83). It states once what is true of every record of the run \u2014 which invocation it was and what became of it \u2014 rather than on each entry. Read off the window's records when the lens is built, so it cannot drift from the head it summarises. Part of the line budget.bytes bounds. Optional so that lines written under the earlier drafts still validate; parley-read always writes it.\"\n    },\n    \"records\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"object\",\n        \"required\": [\n          \"run\",\n          \"seq\"\n        ],\n        \"properties\": {\n          \"run\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"seq\": {\n            \"type\": \"integer\",\n            \"minimum\": 0,\n            \"description\": \"0 for a bootstrap or startup-failure line (spec \u00a71.3).\"\n          },\n          \"event\": {\n            \"type\": \"string\",\n            \"minLength\": 1,\n            \"description\": \"The named record's event token as the loader read it, a tool's own token included verbatim (flyingrobots/parley#77). Absent when the record carries none; never filled in.\"\n          },\n          \"t\": {\n            \"type\": \"integer\",\n            \"minimum\": 0,\n            \"description\": \"The named record's POSIX time in milliseconds (spec \u00a71.3) as the loader read it. Absent when the record has no usable t; never a made-up one.\"\n          },\n          \"code\": {\n            \"type\": \"string\",\n            \"pattern\": \"^[a-z0-9_]+(\\\\.[a-z0-9_]+)+$\",\n            \"description\": \"On an error or warning entry, the record's code (spec \u00a76), so failures of one case read as one without opening them (flyingrobots/parley#83). Absent on any other record, and on a code that is not spec \u00a76's shape; never filled in.\"\n          }\n        }\n      },\n      \"description\": \"The records this result was built from, by (run, seq), never more than budget.records of them. Stored rather than recomputed: projecting down to a result is cheap and expanding back up may be impossible within a budget, so the way back has to be written here. A result is built from records, never from another result. Each entry may also carry a fixed summary of the record it names \u2014 event, t and, on an error or warning, its code \u2014 so a reader can choose what to open without opening it (flyingrobots/parley#77, flyingrobots/parley#83). What is true of the entry's whole run, its identity and outcome, is stated once in runs. The summary is read off the record when the lens is built and is part of the line budget.bytes bounds.\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.lens\"\n        },\n        \"version\": {\n          \"const\": \"1.1.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \u00a74.5, \u00a74.6).\"\n        }\n      }\n    }\n  },\n  \"if\": {\n    \"type\": \"object\",\n    \"required\": [\n      \"loss\"\n    ],\n    \"properties\": {\n      \"loss\": {\n        \"type\": \"object\",\n        \"required\": [\n          \"bound\"\n        ],\n        \"properties\": {\n          \"bound\": {\n            \"const\": \"none\"\n          }\n        }\n      }\n    }\n  },\n  \"then\": {\n    \"type\": \"object\",\n    \"properties\": {\n      \"loss\": {\n        \"type\": \"object\",\n        \"properties\": {\n          \"excluded\": {\n            \"const\": 0\n          },\n          \"folded\": {\n            \"const\": 0\n          }\n        }\n      }\n    }\n  }\n}\n",
    "parley.page.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.page/1.0.0\",\n  \"title\": \"parley page\",\n  \"description\": \"One page of unbounded output; cursor required when has_more is true (spec \\u00a77.2).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"has_more\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"page\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1).\"\n    },\n    \"cursor\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"Opaque to the caller.\"\n    },\n    \"has_more\": {\n      \"type\": \"boolean\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.page\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  },\n  \"if\": {\n    \"type\": \"object\",\n    \"properties\": {\n      \"has_more\": {\n        \"const\": true\n      }\n    }\n  },\n  \"then\": {\n    \"type\": \"object\",\n    \"required\": [\n      \"cursor\"\n    ],\n    \"properties\": {\n      \"cursor\": {\n        \"type\": \"string\",\n        \"minLength\": 1\n      }\n    }\n  }\n}\n",
    "parley.query.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.query/1.1.0\",\n  \"title\": \"parley query\",\n  \"description\": \"A read against the history, recorded as an event: the asker it is for, the view it wants, the budget it will accept and the window it covers (spec \u00a79, informative; the representation is decided in flyingrobots/parley#46 and read against the observer-geometry treatment in docs/topics/related-work/observer-geometry.md). The envelope's run is the read's own run; asker is who the read is for. A drill-down, which opens records a lens named, is the same message with records stating which.\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"asker\",\n    \"view\",\n    \"budget\",\n    \"window\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"query\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to: the read itself, not the runs being read (spec \u00a72.1).\"\n    },\n    \"session\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"Working period spanning runs. Supplied by the caller or inherited; never invented (spec \u00a72.1).\"\n    },\n    \"asker\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"tool\"\n      ],\n      \"properties\": {\n        \"tool\": {\n          \"type\": \"string\",\n          \"minLength\": 1,\n          \"description\": \"The calling program, named as in spec \u00a72.1. Established from the caller's own identity or supplied as one argument; never invented, so a read that cannot establish it is refused.\"\n        },\n        \"cwd\": {\n          \"type\": \"string\",\n          \"pattern\": \"^/\",\n          \"minLength\": 2,\n          \"description\": \"Absolute POSIX working directory the read was made from. Inferred from the process; omitted when it is not meaningful.\"\n        },\n        \"task\": {\n          \"type\": \"string\",\n          \"minLength\": 1,\n          \"description\": \"The caller's current task id, supplied by the caller and never inferred (flyingrobots/parley#61); omitted when the caller does not state it. Not the session: a session is a working period, a task is a unit of work inside one.\"\n        }\n      },\n      \"description\": \"Who the read is for, and the context the budget is inferred from. The asker is not the view: two askers requesting the same view under the same budget get the same answer.\"\n    },\n    \"view\": {\n      \"enum\": [\n        \"what-ran\",\n        \"what-failed\",\n        \"what-changed\",\n        \"how-it-decided\",\n        \"everything\"\n      ],\n      \"description\": \"The shape of the answer, one token from a closed set. Never inferred: there is no privileged view, so a missing view is refused rather than guessed. Adding a token is a version of this schema.\"\n    },\n    \"budget\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"records\"\n      ],\n      \"properties\": {\n        \"records\": {\n          \"type\": \"integer\",\n          \"minimum\": 1,\n          \"description\": \"The most records the answer may name. Required: a view with no bound collapses into \\\"return every record\\\".\"\n        },\n        \"bytes\": {\n          \"type\": \"integer\",\n          \"minimum\": 1,\n          \"description\": \"The most bytes the answer may occupy.\"\n        },\n        \"ms\": {\n          \"type\": \"integer\",\n          \"minimum\": 1,\n          \"description\": \"The most wall-clock milliseconds the read may spend.\"\n        }\n      },\n      \"description\": \"The size of answer the asker will accept. One documented default applies when it is not supplied, and the applied budget is carried verbatim by the result's lens, so a default is never invisible.\"\n    },\n    \"window\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"from\",\n        \"to\"\n      ],\n      \"properties\": {\n        \"from\": {\n          \"type\": \"integer\",\n          \"minimum\": 0,\n          \"description\": \"Inclusive lower bound of the window, POSIX time in milliseconds. 0 means \\\"from the start of the history\\\".\"\n        },\n        \"to\": {\n          \"type\": \"integer\",\n          \"minimum\": 0,\n          \"description\": \"Inclusive upper bound of the window, POSIX time in milliseconds. Never below from.\"\n        }\n      },\n      \"description\": \"The stretch of history the read covers, always stated as two timestamps and echoed by the result's lens.\"\n    },\n    \"note\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"Free text from the asker, recorded and never parsed. Nothing in the answer branches on it.\"\n    },\n    \"fold\": {\n      \"type\": \"boolean\",\n      \"description\": \"Whether the read may fold runs it judges to be repeats of one invocation with one result into the most recent of them (flyingrobots/parley#79). false: nothing is folded, so every run in the window keeps its own records and the budget alone decides what the answer names (flyingrobots/parley#133). true or absent: the reader folds, and the result's lens names the runs a fold stands for in the section of the run that stands for them (parley.lens runs.folded.stands_for). The budget can leave that run out of the answer, and its section with it; the lens then reports that fold as a count alone (parley.lens loss.folded). Never inferred: the reader records it only when the asker states it, and the lens echoes it. It selects nothing on a drill-down.\"\n    },\n    \"records\": {\n      \"type\": \"array\",\n      \"minItems\": 1,\n      \"items\": {\n        \"type\": \"object\",\n        \"required\": [\n          \"run\",\n          \"seq\"\n        ],\n        \"properties\": {\n          \"run\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"seq\": {\n            \"type\": \"integer\",\n            \"minimum\": 0,\n            \"description\": \"0 for a bootstrap or startup-failure line (spec \u00a71.3).\"\n          }\n        }\n      },\n      \"description\": \"Present only on a drill-down: the records the read asks for by (run, seq), the identity a parley.lens names them by, in the order asked (flyingrobots/parley#51). A drill-down answers with exactly these records in full, a sidecar's stored record included, and an outcome per id; the view and window are recorded and select nothing, budget.records is the number of ids asked, and budget.bytes, when stated, bounds the records opened: whole records in the order asked while their summed size stays within it, and an over_budget outcome with no contents for each id past it (flyingrobots/parley#78). Absent on a read that answers with a digest.\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.query\"\n        },\n        \"version\": {\n          \"const\": \"1.1.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \u00a74.5, \u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.receipt.head.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.receipt.head/2.0.0\",\n  \"title\": \"parley receipt head\",\n  \"description\": \"First line of a receipt file. Carries what the bootstrap line deliberately omitted, so stdout stays small while the record stays complete.\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"tool\",\n    \"v\",\n    \"argv\",\n    \"resolved\",\n    \"inputs\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"receipt.head\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter continues from the bootstrap line, which is seq 0 (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1). ULID or equivalent: unique per execution and lexicographically sortable.\"\n    },\n    \"tool\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The program that wrote this receipt, so a receipt read alone says what produced it (spec \\u00a75).\"\n    },\n    \"v\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"That program's own version; with tool, a component of the inv preimage (spec \\u00a72.2) that a receipt read alone must carry.\"\n    },\n    \"inv\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"Content-addressed identity of the question (spec \\u00a72.2); never includes a declared secret. Optional in v0.2: supplied when the tool documents its derivation and the identity is known at this point; never a placeholder (spec \\u00a72.2).\"\n    },\n    \"session\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"argv\": {\n      \"type\": \"array\",\n      \"items\": {\n        \"type\": \"string\"\n      },\n      \"description\": \"As received, after \\u00a75.3 redaction: a declared secret appears as the literal [redacted].\"\n    },\n    \"resolved\": {\n      \"type\": \"object\",\n      \"description\": \"After defaults, environment and path resolution. The gap between this and argv is where bugs live.\"\n    },\n    \"inputs\": {\n      \"type\": \"array\",\n      \"description\": \"Every declared input as a descriptor: its path, its role when the tool distinguishes roles, and a content digest once read. A digest that arrives later is carried by receipt.inputs (spec \\u00a72.2). Credential files are never inputs (\\u00a72.2).\",\n      \"items\": {\n        \"type\": \"object\",\n        \"required\": [\n          \"path\"\n        ],\n        \"properties\": {\n          \"path\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"role\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"sha256\": {\n            \"type\": \"string\",\n            \"pattern\": \"^[0-9a-f]{64}$\"\n          },\n          \"error\": {\n            \"type\": \"string\",\n            \"pattern\": \"^[a-z0-9_]+(\\\\.[a-z0-9_]+)+$\",\n            \"description\": \"Why the input could not be read; no digest then.\"\n          }\n        },\n        \"not\": {\n          \"type\": \"object\",\n          \"required\": [\n            \"sha256\",\n            \"error\"\n          ],\n          \"properties\": {\n            \"sha256\": {\n              \"type\": \"string\"\n            },\n            \"error\": {\n              \"type\": \"string\"\n            }\n          }\n        }\n      }\n    },\n    \"effects\": {\n      \"type\": \"object\",\n      \"properties\": {\n        \"reads\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"string\"\n          }\n        },\n        \"writes\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"string\"\n          }\n        },\n        \"network\": {\n          \"type\": \"boolean\"\n        },\n        \"idempotent\": {\n          \"type\": \"boolean\"\n        }\n      }\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.receipt.head\"\n        },\n        \"version\": {\n          \"const\": \"2.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    },\n    \"redacted\": {\n      \"type\": \"object\",\n      \"minProperties\": 1,\n      \"description\": \"Present and non-empty whenever a declared secret was supplied to the run; absent otherwise (spec \\u00a75.3). Lists where the head carries a replaced value, and which credential sources were present.\",\n      \"properties\": {\n        \"argv\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"integer\",\n            \"minimum\": 0\n          },\n          \"description\": \"Indexes into argv.\"\n        },\n        \"resolved\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"string\",\n            \"format\": \"json-pointer\",\n            \"minLength\": 1\n          },\n          \"description\": \"JSON Pointers (RFC 6901) into resolved.\"\n        },\n        \"env\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"description\": \"Names of declared environment variables that were present.\"\n        },\n        \"inputs\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"integer\",\n            \"minimum\": 0\n          },\n          \"description\": \"Indexes into inputs whose path carried a replaced value.\"\n        },\n        \"sources\": {\n          \"type\": \"array\",\n          \"items\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"description\": \"Logical names of declared credential sources that were present (spec \\u00a75.3).\"\n        }\n      },\n      \"anyOf\": [\n        {\n          \"type\": \"object\",\n          \"required\": [\n            \"argv\"\n          ],\n          \"properties\": {\n            \"argv\": {\n              \"type\": \"array\",\n              \"minItems\": 1\n            }\n          }\n        },\n        {\n          \"type\": \"object\",\n          \"required\": [\n            \"resolved\"\n          ],\n          \"properties\": {\n            \"resolved\": {\n              \"type\": \"array\",\n              \"minItems\": 1\n            }\n          }\n        },\n        {\n          \"type\": \"object\",\n          \"required\": [\n            \"inputs\"\n          ],\n          \"properties\": {\n            \"inputs\": {\n              \"type\": \"array\",\n              \"minItems\": 1\n            }\n          }\n        },\n        {\n          \"type\": \"object\",\n          \"required\": [\n            \"env\"\n          ],\n          \"properties\": {\n            \"env\": {\n              \"type\": \"array\",\n              \"minItems\": 1\n            }\n          }\n        },\n        {\n          \"type\": \"object\",\n          \"required\": [\n            \"sources\"\n          ],\n          \"properties\": {\n            \"sources\": {\n              \"type\": \"array\",\n              \"minItems\": 1\n            }\n          }\n        }\n      ]\n    },\n    \"dry_run\": {\n      \"type\": \"boolean\",\n      \"description\": \"True when the run performed no subject-matter writes, no mutating remote action and no retention deletion (spec \\u00a74.3). Absent means false.\"\n    }\n  }\n}\n",
    "parley.receipt.inputs.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.receipt.inputs/1.0.0\",\n  \"title\": \"parley receipt inputs\",\n  \"description\": \"The metadata-finalisation record: late input digests and, when known, inv; emitted once inputs are settled and before end (spec \\u00a72.2).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"inputs\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"receipt.inputs\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1).\"\n    },\n    \"inputs\": {\n      \"type\": \"array\",\n      \"description\": \"Every declared input as a descriptor: its path, its role when the tool distinguishes roles, and a content digest once read. A digest that arrives later is carried by receipt.inputs (spec \\u00a72.2). Credential files are never inputs (\\u00a72.2).\",\n      \"items\": {\n        \"type\": \"object\",\n        \"required\": [\n          \"path\"\n        ],\n        \"properties\": {\n          \"path\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"role\": {\n            \"type\": \"string\",\n            \"minLength\": 1\n          },\n          \"sha256\": {\n            \"type\": \"string\",\n            \"pattern\": \"^[0-9a-f]{64}$\"\n          },\n          \"error\": {\n            \"type\": \"string\",\n            \"pattern\": \"^[a-z0-9_]+(\\\\.[a-z0-9_]+)+$\",\n            \"description\": \"Why the input could not be read; no digest then.\"\n          }\n        },\n        \"not\": {\n          \"type\": \"object\",\n          \"required\": [\n            \"sha256\",\n            \"error\"\n          ],\n          \"properties\": {\n            \"sha256\": {\n              \"type\": \"string\"\n            },\n            \"error\": {\n              \"type\": \"string\"\n            }\n          }\n        }\n      }\n    },\n    \"inv\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"Present when the identity could be computed (spec \\u00a72.2).\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.receipt.inputs\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.receipt.step.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.receipt.step/1.0.0\",\n  \"title\": \"parley receipt step\",\n  \"description\": \"One decision the program made while working, with its reason; receipt only (spec \\u00a75).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"decision\",\n    \"because\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"receipt.step\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1).\"\n    },\n    \"decision\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"because\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"detail\": {\n      \"type\": \"object\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.receipt.step\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.redaction.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.redaction/1.0.0\",\n  \"title\": \"parley redaction\",\n  \"description\": \"A receipt line recording a redaction not covered by the head's redacted field: in the head itself (in: 1) or in any later record or sidecar (spec \\u00a75.3).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"in\",\n    \"at\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"redaction\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1).\"\n    },\n    \"in\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The seq of the affected record: the head, a result, an error, a reasoning line, or the stored record a sidecar holds (its source).\"\n    },\n    \"at\": {\n      \"type\": \"string\",\n      \"format\": \"json-pointer\",\n      \"minLength\": 1,\n      \"description\": \"JSON Pointer (RFC 6901) within that record.\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.redaction\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.run.bootstrap.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.run.bootstrap/1.1.1\",\n  \"title\": \"parley run bootstrap\",\n  \"description\": \"First line of stdout, emitted before work begins so a crashed run still names its receipt.\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"tool\",\n    \"v\",\n    \"run\",\n    \"paths\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"run\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"const\": 0,\n      \"description\": \"The bootstrap line is always the first line the run emits, so it is the only line with a pinned seq.\"\n    },\n    \"tool\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"v\": {\n      \"type\": \"string\",\n      \"description\": \"The program's own version, distinct from _schema.version on the same line (spec \\u00a73).\",\n      \"minLength\": 1\n    },\n    \"inv\": {\n      \"type\": \"string\",\n      \"description\": \"Content-addressed identity of the question: tool, version, normalised args, and the bytes of every declared input; never a declared secret (spec \\u00a72.2, \\u00a75.3). Optional in v0.2: supplied when the tool documents its derivation and the identity is known at this point; never a placeholder (spec \\u00a72.2).\",\n      \"minLength\": 1\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"Unique, lexicographically sortable identity of this execution.\"\n    },\n    \"session\": {\n      \"type\": \"string\",\n      \"description\": \"Working period spanning runs. Supplied by the caller or inherited.\",\n      \"minLength\": 1\n    },\n    \"paths\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"receipt\"\n      ],\n      \"properties\": {\n        \"receipt\": {\n          \"type\": \"string\",\n          \"pattern\": \"^/\",\n          \"minLength\": 2,\n          \"description\": \"Absolute path of the receipt file for this run (spec \\u00a75). The only path the protocol defines; a program may add others it documents.\"\n        }\n      },\n      \"description\": \"Files this run writes.\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.run.bootstrap\"\n        },\n        \"version\": {\n          \"const\": \"1.1.1\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    },\n    \"dry_run\": {\n      \"type\": \"boolean\",\n      \"description\": \"True when the run performed no subject-matter writes, no mutating remote action and no retention deletion (spec \\u00a74.3). Absent means false.\"\n    }\n  }\n}\n",
    "parley.schema.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.schema/1.0.0\",\n  \"title\": \"parley schema\",\n  \"description\": \"One message schema, carried by --schema and --help (spec \\u00a74.1, \\u00a74.2).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"id\",\n    \"version\",\n    \"schema\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"schema\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1).\"\n    },\n    \"id\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"version\": {\n      \"type\": \"string\",\n      \"pattern\": \"^(0|[1-9][0-9]*)\\\\.(0|[1-9][0-9]*)\\\\.(0|[1-9][0-9]*)$\"\n    },\n    \"schema\": {\n      \"type\": \"object\",\n      \"description\": \"The JSON Schema document for that exact (id, version).\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.schema\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.sidecar.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.sidecar/1.0.0\",\n  \"title\": \"parley sidecar\",\n  \"description\": \"A receipt line standing in for a record stored beside the receipt because it exceeded the inline threshold (spec \\u00a75).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"source\",\n    \"path\",\n    \"bytes\",\n    \"sha256\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"sidecar\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to (spec \\u00a72.1).\"\n    },\n    \"source\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The seq of the record the sidecar holds.\"\n    },\n    \"path\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"pattern\": \"^(?!/)(?!.*(^|/)\\\\.\\\\.(/|$)).+$\",\n      \"description\": \"Relative to the receipt's directory; never absolute, never escaping it.\"\n    },\n    \"bytes\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"Length of the stored bytes.\"\n    },\n    \"sha256\": {\n      \"type\": \"string\",\n      \"pattern\": \"^[0-9a-f]{64}$\",\n      \"description\": \"SHA-256 of the stored bytes; not the semantic digest of \\u00a77.1.\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.sidecar\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.startup.failed.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.startup.failed/1.0.0\",\n  \"title\": \"parley startup failed\",\n  \"description\": \"The single line a run emits, on stderr, when it cannot reach the bootstrap line; exit status 3 (spec \\u00a73.2).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"tool\",\n    \"v\",\n    \"code\",\n    \"problem\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"startup.failed\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0\n    },\n    \"seq\": {\n      \"const\": 0,\n      \"description\": \"The only line the run emits (spec \\u00a71.3, \\u00a73.2).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"tool\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"v\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"code\": {\n      \"type\": \"string\",\n      \"pattern\": \"^startup\\\\.[a-z0-9_]+(\\\\.[a-z0-9_]+)*$\",\n      \"description\": \"A \\u00a76 code in the startup namespace.\"\n    },\n    \"problem\": {\n      \"type\": \"string\",\n      \"minLength\": 1\n    },\n    \"remedy\": {\n      \"type\": \"string\"\n    },\n    \"remedy_target\": {\n      \"type\": \"string\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.startup.failed\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
    "parley.warning.schema.json": "{\n  \"$schema\": \"https://json-schema.org/draft/2020-12/schema\",\n  \"$id\": \"https://flyingrobots.dev/parley/schemas/parley.warning/1.0.0\",\n  \"title\": \"parley warning\",\n  \"description\": \"A recovered condition: the same shape as an error, on stderr and in the receipt, never changing the exit status (spec \\u00a76.1).\",\n  \"type\": \"object\",\n  \"required\": [\n    \"event\",\n    \"t\",\n    \"seq\",\n    \"run\",\n    \"code\",\n    \"problem\",\n    \"_schema\"\n  ],\n  \"properties\": {\n    \"event\": {\n      \"const\": \"warning\"\n    },\n    \"t\": {\n      \"type\": \"integer\",\n      \"minimum\": 0,\n      \"description\": \"POSIX time in milliseconds (spec \\u00a71.3).\"\n    },\n    \"seq\": {\n      \"type\": \"integer\",\n      \"minimum\": 1,\n      \"description\": \"The run's single counter; 0 is the bootstrap line (spec \\u00a71.3).\"\n    },\n    \"run\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"The execution this line belongs to. Required on every line so a detached line can still be attributed (spec \\u00a71.3).\"\n    },\n    \"code\": {\n      \"type\": \"string\",\n      \"pattern\": \"^[a-z0-9_]+(\\\\.[a-z0-9_]+)+$\",\n      \"description\": \"Stable identifier: two or more dot-separated segments of lowercase letters, digits and underscores (spec \\u00a76). Never a prose message.\"\n    },\n    \"problem\": {\n      \"type\": \"string\",\n      \"minLength\": 1,\n      \"description\": \"What is wrong, in one sentence.\"\n    },\n    \"measured\": {\n      \"description\": \"The value observed, when the failure is a threshold.\"\n    },\n    \"limit\": {\n      \"description\": \"The threshold that was not met.\"\n    },\n    \"remedy\": {\n      \"type\": \"string\",\n      \"description\": \"The lever to pull. Omit rather than invent one.\"\n    },\n    \"remedy_target\": {\n      \"type\": \"string\",\n      \"description\": \"What the remedy applies to.\"\n    },\n    \"_schema\": {\n      \"type\": \"object\",\n      \"required\": [\n        \"id\",\n        \"version\"\n      ],\n      \"additionalProperties\": false,\n      \"properties\": {\n        \"id\": {\n          \"const\": \"parley.warning\"\n        },\n        \"version\": {\n          \"const\": \"1.0.0\",\n          \"description\": \"Full validation is against the schema for this exact id and version (spec \\u00a74.5, \\u00a74.6).\"\n        }\n      }\n    }\n  }\n}\n",
}
# END SCHEMAS


def _load_schemas() -> List[Dict[str, Any]]:
    out = []
    for name in sorted(_SCHEMA_TEXT):
        doc = json.loads(_SCHEMA_TEXT[name])
        pin = doc["properties"]["_schema"]["properties"]
        out.append({"file": name, "id": pin["id"]["const"], "version": pin["version"]["const"], "schema": doc})
    return out


SCHEMAS: List[Dict[str, Any]] = _load_schemas()


def schema_text_digests() -> Dict[str, str]:
    """The SHA-256 of each embedded schema's text, to compare against `SCHEMA_SOURCE['files']`."""
    return {name: sha256(text.encode("utf-8")) for name, text in _SCHEMA_TEXT.items()}


def schema_for(pair: SchemaRef) -> Optional[Dict[str, Any]]:
    """The embedded schema document for an exact `(id, version)` pair, or None."""
    sid, ver = _pair(pair)
    for s in SCHEMAS:
        if s["id"] == sid and s["version"] == ver:
            return s["schema"]
    return None


# ---- small helpers -------------------------------------------------------------------------


def sha256(data: Union[bytes, str]) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _pair(ref: SchemaRef) -> Tuple[str, str]:
    if isinstance(ref, tuple):
        return ref[0], ref[1]
    return ref["id"], ref["version"]


def _now_ms() -> int:
    return max(0, int(time.time() * 1000))


def _dumps(obj: Any) -> str:
    """One JSON document, no whitespace, no NaN. A lone surrogate falls back to an escape, so the
    line is always valid UTF-8."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = json.dumps(obj, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return text


def _json_scalar(v: Any) -> str:
    """The decimal form a scalar takes in JSON, which is how a reader would see it."""
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e21:
        return str(int(v))
    return str(v)


def _json_key(k: Any) -> str:
    if isinstance(k, str):
        return k
    if k is None:
        return "null"
    if isinstance(k, (bool, int, float)):
        return _json_scalar(k)
    raise TypeError(f"a record key must be a string, not {type(k).__name__}")


# ---- run ids -------------------------------------------------------------------------------

_ENC = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(ms: Optional[int] = None) -> str:
    """A ULID: 10 characters of millisecond time and 16 of randomness, Crockford base32, so run ids
    sort lexicographically by creation time (spec section 2.1)."""
    t = max(0, int(_now_ms() if ms is None else ms))
    head = ""
    for _ in range(10):
        head = _ENC[t % 32] + head
        t //= 32
    return head + "".join(_ENC[b & 31] for b in os.urandom(16))


# ---- inv (spec section 2.2) ----------------------------------------------------------------
# This writer's derivation, which is the TypeScript writer's, byte for byte:
#
#   inv = SHA-256 over the canonical JSON (keys sorted, no whitespace, UTF-8) of
#     { tool, v, command, resolved, inputs: [{ path, role?, sha256 }] }
#
# `resolved` is the redacted interpretation, so a declared secret enters by name and never by
# value; the input descriptors are the redacted ones for the same reason. If any declared input
# could not be read there is no inv.


def canonical(v: Any) -> str:
    if isinstance(v, dict):
        keys = sorted(_json_key(k) for k in v)
        by = {_json_key(k): val for k, val in v.items()}
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonical(by[k]) for k in keys) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(canonical(x) for x in v) + "]"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e21:
        return str(int(v))
    return json.dumps(v, ensure_ascii=False, allow_nan=False)


def compute_inv(tool: str, v: str, command: str, resolved: Any, inputs: Sequence[Mapping[str, Any]]) -> Optional[str]:
    if any("sha256" not in i for i in inputs):
        return None
    pre_inputs = []
    for i in inputs:
        d: Record = {"path": i["path"]}
        if i.get("role"):
            d["role"] = i["role"]
        d["sha256"] = i["sha256"]
        pre_inputs.append(d)
    return sha256(canonical({"tool": tool, "v": v, "command": command, "resolved": resolved, "inputs": pre_inputs}))


def _excluded(rel: str, exclude: Sequence[str]) -> bool:
    for e in exclude:
        x = e.rstrip("/")
        if rel == x or rel.startswith(x + "/"):
            return True
    return False


def digest_tree(root: str, exclude: Sequence[str] = ()) -> str:
    """SHA-256 over `relative-path NUL file-digest LF` for every regular file under `root`, sorted
    by path, skipping `.parley` directories and excluded paths."""
    files: List[str] = []

    def walk(d: str, rel: str) -> None:
        for name in sorted(os.listdir(d)):
            if name == ".parley":
                continue
            p = os.path.join(d, name)
            r = f"{rel}/{name}" if rel else name
            if _excluded(r, exclude):
                continue
            if os.path.isdir(p):
                walk(p, r)
            elif os.path.isfile(p):
                files.append(r)

    walk(root, "")
    h = hashlib.sha256()
    for r in files:
        with open(os.path.join(root, r), "rb") as f:
            h.update((r + "\0" + sha256(f.read()) + "\n").encode("utf-8"))
    return h.hexdigest()


def digest_input(cwd: str, decl: Mapping[str, Any], supplied: Optional[bytes] = None) -> Record:
    base: Record = {"path": decl["path"]}
    if decl.get("role"):
        base["role"] = decl["role"]
    try:
        if decl.get("role") == "stdin":
            return {**base, "sha256": sha256(supplied)} if supplied is not None else {**base, "error": "input.unread"}
        if supplied is not None:
            return {**base, "sha256": sha256(supplied)}
        p = os.path.join(cwd, decl["path"])
        if os.path.isdir(p) or decl.get("role") == "tree":
            return {**base, "sha256": digest_tree(p, decl.get("exclude") or ())}
        with open(p, "rb") as f:
            return {**base, "sha256": sha256(f.read())}
    except OSError:
        return {**base, "error": "input.unreadable"}


# ---- redaction (spec section 5.3) ----------------------------------------------------------


def classify_secrets(secrets: Iterable[str]) -> Dict[str, List[str]]:
    """A name starting with `-` is a flag; an upper-case identifier is an environment variable;
    anything else is a logical credential source."""
    flags: List[str] = []
    env: List[str] = []
    sources: List[str] = []
    seen: Set[str] = set()
    for s in secrets:
        if s in seen:
            continue
        seen.add(s)
        if s.startswith("-"):
            flags.append(s)
        elif _ENV_NAME.match(s):
            env.append(s)
        else:
            sources.append(s)
    return {"flags": flags, "env": env, "sources": sources}


def collect_secret_values(argv: Sequence[str], names: Mapping[str, List[str]], env: Mapping[str, str]) -> Set[str]:
    values: Set[str] = set()
    for i, a in enumerate(argv):
        for flag in names["flags"]:
            if a == flag and i + 1 < len(argv):
                values.add(argv[i + 1])
            elif a.startswith(flag + "="):
                values.add(a[len(flag) + 1:])
    for name in names["env"]:
        if name in env:
            values.add(env[name])
    values.discard("")
    return values


def replace_secrets(s: str, values: Iterable[str]) -> str:
    """Longest value first, so a secret containing another is replaced whole, leaving no tail."""
    out = s
    for v in sorted(values, key=len, reverse=True):
        if v in out:
            out = out.replace(v, REDACTED)
    return out


def carries_secret(s: str, values: Iterable[str]) -> bool:
    return any(v in s for v in values)


def redact_argv(argv: Sequence[str], values: Set[str], flags: Sequence[str] = ()) -> Tuple[List[str], List[int]]:
    out = [replace_secrets(a, values) for a in argv]
    changed = {i for i, a in enumerate(out) if a != argv[i]}
    for i, a in enumerate(argv):
        for flag in flags:
            if a == flag and i + 1 < len(argv):
                out[i + 1] = REDACTED
                changed.add(i + 1)
            elif a.startswith(flag + "="):
                out[i] = flag + "=" + REDACTED
                changed.add(i)
    return out, sorted(changed)


def _escape_pointer(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def scrub_pointer(pointer: str, values: Iterable[str]) -> str:
    """A JSON Pointer (RFC 6901) with every secret replaced inside each reference token, read as
    the key it stands for: a pointer escapes `/` and `~`, so a key that is a secret holding either
    would otherwise pass a search of the pointer's text. A pointer a validator reports can name a
    key the record no longer has (the one a scrub renamed), and that key can be the secret."""
    values = list(values)
    if not values or not pointer.startswith("/"):
        return replace_secrets(pointer, values)
    tokens = pointer.split("/")
    return "/".join([tokens[0]] + [_escape_pointer(replace_secrets(t.replace("~1", "/").replace("~0", "~"), values)) for t in tokens[1:]])


def scrub(value: Any, values: Set[str], pointer: str = "", found: Optional[List[str]] = None,
          skip_keys: Optional[frozenset] = None, scalars: bool = True, rename_keys: bool = True) -> Any:
    """A deep copy of `value` with every secret replaced, recording the RFC 6901 pointer of each
    place that changed. Strings are replaced within; a number or boolean whose JSON form is a
    secret becomes `[redacted]` (a PIN parsed to a number is still the PIN); a key carrying a
    secret is renamed, and the pointer recorded is the renamed key's.

    A writer-built record passes `skip_keys`, `scalars=False` and `rename_keys=False`: its field
    names (`paths`, `status`, `op`) are the protocol's, named by the released schema, and renaming
    one would publish a line that schema rejects. A tool's object that reaches a writer-built
    record (`resolved`) was scrubbed in full, keys included, before the record was built."""
    if found is None:
        found = []
    if not values:
        return value
    if isinstance(value, str):
        r = replace_secrets(value, values)
        if r != value:
            found.append(pointer or "/")
        return r
    if isinstance(value, (bool, int, float)):
        if scalars and _json_scalar(value) in values:
            found.append(pointer or "/")
            return REDACTED
        return value
    if isinstance(value, (list, tuple)):
        return [scrub(v, values, f"{pointer}/{i}", found, skip_keys, scalars, rename_keys) for i, v in enumerate(value)]
    if isinstance(value, dict):
        out: Record = {}
        for k, v in value.items():
            jk = _json_key(k)
            key = replace_secrets(jk, values) if rename_keys else jk
            p = f"{pointer}/{_escape_pointer(key)}"
            if key != jk:
                found.append(p)
            if skip_keys is not None and jk in skip_keys and isinstance(v, str):
                out[key] = v
            else:
                out[key] = scrub(v, values, p, found, skip_keys, scalars, rename_keys)
        return out
    return value


# ---- where the receipt goes (spec sections 5, 5.2) -----------------------------------------


def repo_root(cwd: str) -> str:
    d = os.path.abspath(cwd)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(cwd)
        d = parent


def state_base(env: Mapping[str, str], home: Optional[str] = None) -> str:
    x = env.get("XDG_STATE_HOME")
    if x and os.path.isabs(x):
        return x
    return os.path.join(home if home is not None else os.path.expanduser("~"), ".local", "state")


def _realpath_safe(p: str) -> str:
    try:
        return os.path.realpath(p)
    except OSError:
        return p


def state_receipt_dir(cwd: str, env: Mapping[str, str], home: Optional[str] = None) -> str:
    """`$XDG_STATE_HOME/parley/<repo-hash>/receipts`, keyed exactly as the TypeScript writer and
    reader key it, so `parley-read` finds receipts this writer put there."""
    key = sha256(_realpath_safe(repo_root(cwd)))[:16]
    return os.path.join(state_base(env, home), "parley", key, "receipts")


def bookkeeping_for(cwd: str, env: Mapping[str, str], home: Optional[str] = None) -> List[Record]:
    """The bookkeeping a run may perform, declared ahead of time (spec section 4.3)."""
    repo = os.path.join(os.path.abspath(cwd), ".parley")
    state = state_receipt_dir(cwd, env, home)
    return [
        {"op": "create", "scope": os.path.join(repo, "receipts") + "/"},
        {"op": "create", "scope": os.path.join(repo, ".gitignore")},
        {"op": "delete", "scope": os.path.join(repo, "receipts") + "/"},
        {"op": "create", "scope": state + "/"},
        {"op": "delete", "scope": state + "/"},
    ]


def _unlink_safe(p: str) -> None:
    try:
        os.unlink(p)
    except OSError:
        pass


_PRINTABLE_ASCII = re.compile(r"[\x20-\x7e]*\Z")


def _negation_reaches_receipts(line: str) -> bool:
    """Whether a `.gitignore` line is a negation that can match the directory `receipts` beside
    it, or a line this writer cannot evaluate exactly, which spec section 5.2 says counts as one
    that does. With `*` in force nothing under `receipts/` can be staged unless the directory
    itself is re-included, because git cannot re-include a file whose parent directory is
    excluded (gitignore(5)).

    The rule, the same in the TypeScript writer:

    - A line holding a NUL byte is not evaluated. git reads a pattern as a C string, so the
      pattern it sees ends at the NUL; this writer does not guess at the rest.
    - Otherwise only a line that starts with `!` is a negation. Trailing spaces, one trailing
      `/`, one leading `/` and any leading `**/` are taken off.
    - What is left is not evaluated when it holds a `/`, a backslash, or any character outside
      printable ASCII (a tab, a control character, any non-ASCII letter: how git folds the case
      of those is its own question), or a bracket expression that is unterminated or holds `[:`,
      `[=` or `[.`.
    - Anything else is matched against `receipts` as git's wildmatch reads one path component:
      `*` any run, `?` one character, a bracket expression a set (`!` or `^` first negates it,
      the first member is literal even when it is `]`, `a-z` is a range, and a `-` after a range
      or beside either bracket is literal), everything else itself. The match ignores case, as
      git does where `core.ignorecase` is set, which only ever adds matches."""
    if "\x00" in line:
        return True
    if not line.startswith("!"):
        return False
    pat = line[1:].rstrip(" ")
    if pat.endswith("/"):
        pat = pat[:-1]
    if pat.startswith("/"):
        pat = pat[1:]
    while pat.startswith("**/"):
        pat = pat[3:]
    if "/" in pat or "\\" in pat:
        return True
    if not _PRINTABLE_ASCII.match(pat):
        return True
    glob = _parse_glob(pat)
    return True if glob is None else _glob_matches(glob, 0, "receipts", 0)


def _parse_glob(pat: str) -> Optional[List[Any]]:
    """A glob of printable ASCII with no `/` and no backslash, as tokens: `"*"` any run, `"?"` any
    one character, or `(negated, ranges)` a set of characters given as inclusive ranges. None
    when it holds a bracket expression this writer does not evaluate."""
    out: List[Any] = []
    n = len(pat)

    def special(j: int) -> bool:
        return pat[j:j + 1] == "[" and pat[j + 1:j + 2] in (":", "=", ".")

    i = 0
    while i < n:
        c = pat[i]
        if c == "*":
            if not out or out[-1] != "*":
                out.append("*")
        elif c == "?":
            out.append("?")
        elif c != "[":
            out.append((False, [(c, c)]))
        else:
            j = i + 1
            negated = pat[j:j + 1] in ("!", "^")
            if negated:
                j += 1
            ranges: List[Tuple[str, str]] = []
            prev: Optional[str] = None
            first = True
            while True:
                if j >= n:
                    return None  # unterminated
                m = pat[j]
                if m == "]" and not first:
                    break
                if special(j):
                    return None
                if m == "-" and prev is not None and j + 1 < n and pat[j + 1] != "]":
                    if special(j + 1):
                        return None
                    ranges.append((prev, pat[j + 1]))
                    prev = None
                    j += 2
                else:
                    ranges.append((m, m))
                    prev = m
                    j += 1
                first = False
            out.append((negated, ranges))
            i = j
        i += 1
    return out


def _glob_matches(glob: Sequence[Any], ti: int, text: str, si: int) -> bool:
    """Whether the tokens from `ti` match `text` from `si` to its end, ignoring case. `text` is
    lower case."""
    if ti == len(glob):
        return si == len(text)
    tok = glob[ti]
    if tok == "*":
        return any(_glob_matches(glob, ti + 1, text, k) for k in range(si, len(text) + 1))
    if si >= len(text):
        return False
    if tok != "?":
        negated, ranges = tok
        c = text[si]
        up = c.upper()
        inside = any(lo <= c <= hi or lo <= up <= hi for lo, hi in ranges)
        if inside == negated:
            return False
    return _glob_matches(glob, ti + 1, text, si + 1)


def _hygiene(parley_dir: str, nonce: str) -> Optional[str]:
    """Spec section 5.2: `.parley/.gitignore` holding a line `*`, create-if-absent and never
    overwritten. Written whole to a temporary name and linked into place, so no process reads it
    empty. None when the file is ours to rely on; otherwise why it is a user's file: no line `*`,
    or a negation that can re-include `receipts/` (flyingrobots/parley#109)."""
    os.makedirs(parley_dir, exist_ok=True)
    f = os.path.join(parley_dir, ".gitignore")
    if not os.path.exists(f):
        tmp = os.path.join(parley_dir, f".gitignore.{nonce}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        try:
            os.write(fd, b"*\n")
        finally:
            os.close(fd)
        try:
            os.link(tmp, f)
        except FileExistsError:
            pass
        finally:
            _unlink_safe(tmp)
    with open(f, "r", encoding="utf-8", errors="replace", newline="") as fh:
        lines = re.split(r"\r?\n", fh.read())
    if "*" not in lines:
        return f"{f} exists without a line consisting of *"
    for line in lines:
        if _negation_reaches_receipts(line):
            if not line.startswith("!"):
                return f"{f} has a line consisting of *, but also a line holding a NUL byte, which this writer cannot rule out as a negation that re-includes receipts/, where git add would stage a receipt"
            return f"{f} has a line consisting of *, but its negation {line} can re-include receipts/, or cannot be evaluated by this writer and so counts as one that can; git add would then stage a receipt"
    return None


def _reserve(receipt_dir: str, run: str) -> Tuple[str, int]:
    os.makedirs(receipt_dir, exist_ok=True)
    path = os.path.join(receipt_dir, f"{run}.jsonl")
    return path, os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o666)


class _Location:
    def __init__(self, where: str, receipt_dir: str, receipt_path: str, fd: int, warning: Optional[Record] = None):
        self.where, self.receipt_dir, self.receipt_path, self.fd, self.warning = where, receipt_dir, receipt_path, fd, warning


def _choose_location(cwd: str, run: str, env: Mapping[str, str], home: Optional[str], secrets: Set[str]) -> Union[_Location, Record]:
    cwd = os.path.abspath(cwd)
    warning: Optional[Record] = None
    repo_dir = os.path.join(cwd, ".parley", "receipts")
    if carries_secret(os.path.join(repo_dir, f"{run}.jsonl"), secrets):
        warning = {"code": "receipt.relocated", "problem": "the receipt path under the working directory would carry a declared secret value, so the receipt went to the state directory", "remedy": "run from a directory whose path does not contain the secret, or leave the receipt where it went"}
    else:
        try:
            why = _hygiene(os.path.join(cwd, ".parley"), run)
            if why is None:
                path, fd = _reserve(repo_dir, run)
                return _Location("repo", repo_dir, path, fd)
            warning = {"code": "receipt.relocated", "problem": f"{why}, so it is a user's file and was left alone; the receipt went to the state directory", "remedy": "make .parley/.gitignore a line consisting of * with no negation that can match receipts, or leave the receipt where it went"}
        except OSError:
            pass  # the working directory is not usable; fall back silently (the bootstrap line says where)
    try:
        state_dir = state_receipt_dir(cwd, env, home)
    except OSError:
        return _unwritable(cwd)
    if carries_secret(os.path.join(state_dir, f"{run}.jsonl"), secrets):
        return {"code": "startup.secret_in_path", "problem": "every receipt location this writer can choose has a path carrying a declared secret value; no receipt path can be printed without disclosing it", "remedy": "set XDG_STATE_HOME to an absolute path that does not contain the secret, or do not pass that value as a declared secret"}
    try:
        path, fd = _reserve(state_dir, run)
        return _Location("state", state_dir, path, fd, warning)
    except OSError:
        return _unwritable(cwd)


def _unwritable(cwd: str) -> Record:
    return {"code": "startup.receipt_unwritable", "problem": f"No writable receipt location: {os.path.join(cwd, '.parley')} is not usable and the state directory is not writable", "remedy": "make .parley writable or set XDG_STATE_HOME to a writable absolute path"}


# ---- a bounded JSON Schema checker ---------------------------------------------------------
# Written for one job: letting a Python tool validate its own output line by line in its own
# tests (spec section 4.4) without a dependency. It implements the constructs the protocol's own
# schemas use and **reports** a keyword it does not implement rather than ignoring it, so "we
# checked the parts we understood" is never passed off as a check.

_ANNOTATIONS = frozenset(["$schema", "$id", "$anchor", "$comment", "title", "description", "examples", "default", "deprecated", "readOnly", "writeOnly"])
_SUPPORTED = _ANNOTATIONS | frozenset([
    "type", "const", "enum", "required", "properties", "additionalProperties", "items",
    "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "minProperties", "maxProperties",
    "pattern", "format", "not", "anyOf", "allOf", "oneOf", "if", "then", "else",
])
_FORMATS = {"json-pointer": re.compile(r"^(?:/(?:[^~/]|~0|~1)*)*\Z")}
_SUBSCHEMA = ("items", "not", "if", "then", "else", "additionalProperties")
_SUBSCHEMA_LISTS = ("anyOf", "allOf", "oneOf")


class _Issue(str):
    """One failure's sentence, which also knows where in the record it is about."""

    at: str

    def __new__(cls, message: str, at: str) -> "_Issue":
        self = super().__new__(cls, message)
        self.at = at
        return self


class CheckResult:
    """`ok` when the value satisfies the schema; otherwise `errors` says where. `pointers` is the
    JSON Pointer (RFC 6901) of each error, in the same order: the place in the record the error is
    about, and for a missing or disallowed property, that property. A pointer is a location and
    nothing else, so it is safe to print where an error's text, which can quote the schema, is not
    (flyingrobots/parley#131). `unsupported` names a construct the checker does not implement, in
    which case nothing was established and `pointers` is empty."""

    def __init__(self, ok: bool, errors: Sequence[str] = (), unsupported: Optional[str] = None):
        self.ok, self.errors, self.unsupported = ok, list(errors), unsupported
        self.pointers: List[str] = [e.at for e in self.errors if isinstance(e, _Issue)]

    def __repr__(self) -> str:
        return f"CheckResult(ok={self.ok!r}, errors={self.errors!r}, unsupported={self.unsupported!r})"


class _Unsupported(Exception):
    def __init__(self, keyword: str):
        super().__init__(f"the schema uses {keyword}, which this checker does not implement")
        self.keyword = keyword


_TYPE_NAMES = frozenset(["null", "boolean", "object", "array", "number", "string", "integer"])
_COUNTS = ("minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties")
_BOUNDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
# What `schema_subset_gap` reports for a `pattern` this writer will not answer for. It names no
# part of the pattern.
_PATTERN_GAP = "a pattern this writer cannot evaluate as ECMAScript reads it"
_UNEVALUATED_GAP = "a construct this checker could not evaluate"


def _is_number(v: Any) -> bool:
    """A finite JSON number: not a boolean, and not the NaN or Infinity `json` will parse."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"), float("-inf"))


def _is_count(v: Any) -> bool:
    """A non-negative integer, however JSON wrote it: `3` and `3.0` are the same number."""
    return _is_number(v) and v >= 0 and (isinstance(v, int) or v.is_integer())


def schema_subset_gap(schema: Any) -> Optional[str]:
    """The first construct in `schema` this checker does not implement, or None. A property of the
    whole document, walked before any value, so a keyword under a property the value lacks is
    still found.

    A keyword whose value has the wrong shape is a schema this checker cannot evaluate, the same
    as a keyword it does not implement: `enum: 5` has no reading to check a record against. Each
    is reported here, so nothing below has to trust a shape it did not check and no malformed
    document can make the walk raise. So is a `pattern` this writer does not read as ECMAScript
    would (`_js_regex`). The TypeScript writer reports the same constructs in the same words."""
    if schema is True or schema is False or schema is None:
        return None
    return _walk_schema(schema)


def _walk_schema(schema: Any) -> Optional[str]:
    if schema is True or schema is False:
        return None
    if not isinstance(schema, dict):
        return "a schema that is not an object or a boolean"
    for k in schema:
        if k not in _SUPPORTED:
            return k if isinstance(k, str) else "a keyword that is not a string"
    s = schema
    if "type" in s:
        names = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not all(isinstance(t, str) and t in _TYPE_NAMES for t in names):
            return "type that is not a type name or a list of type names"
    if "enum" in s and not isinstance(s["enum"], list):
        return "enum that is not a list"
    if "required" in s and not (isinstance(s["required"], list) and all(isinstance(k, str) for k in s["required"])):
        return "required that is not a list of strings"
    for k in _COUNTS:
        if k in s and not _is_count(s[k]):
            return f"{k} that is not a non-negative integer"
    for k in _BOUNDS:
        if k in s and not _is_number(s[k]):
            return f"{k} that is not a number"
    if "pattern" in s:
        if not isinstance(s["pattern"], str):
            return "pattern that is not a string"
        if _js_regex(s["pattern"]) is None:
            return _PATTERN_GAP
    if "format" in s:
        if not isinstance(s["format"], str):
            return "format that is not a string"
        if s["format"] not in _FORMATS:
            return f"format {s['format']}"
    if isinstance(s.get("items"), list):
        return "items as a tuple"
    for k in _SUBSCHEMA:
        if k in s:
            gap = _walk_schema(s[k])
            if gap is not None:
                return gap
    for k in _SUBSCHEMA_LISTS:
        if k in s:
            if not isinstance(s[k], list):
                return f"{k} that is not a list"
            for sub in s[k]:
                gap = _walk_schema(sub)
                if gap is not None:
                    return gap
    if "properties" in s:
        if not isinstance(s["properties"], dict):
            return "properties that is not an object"
        for sub in s["properties"].values():
            gap = _walk_schema(sub)
            if gap is not None:
                return gap
    return None


def check_record(value: Any, schema: Any) -> CheckResult:
    gap = schema_subset_gap(schema)
    if gap is not None:
        return CheckResult(False, [f"the schema uses {gap}, which this checker does not implement"], gap)
    errors: List[str] = []
    try:
        _validate(schema, value, "", errors)
    except _Unsupported as e:
        return CheckResult(False, [str(e)], e.keyword)
    except Exception:
        # Nothing else is expected, since the walk above checked every shape the code below
        # relies on. Whatever it is, it is this checker failing to evaluate the schema, and the
        # answer to that is "nothing was established", never a raise and never the raised text,
        # which can quote the schema (spec section 5.3).
        return CheckResult(False, [f"the schema uses {_UNEVALUATED_GAP}, which this checker does not implement"], _UNEVALUATED_GAP)
    return CheckResult(not errors, errors)


def validate_line(line: Mapping[str, Any], extra: Optional[Mapping[Tuple[str, str], Any]] = None) -> CheckResult:
    """Check one emitted line against the schema for its exact advertised pair (spec section 4.5):
    the embedded drafts, or a tool-owned schema passed in `extra` keyed by `(id, version)`. A pair
    with no schema is reported as unsupported, never as validated."""
    stamp = line.get("_schema") if isinstance(line, Mapping) else None
    if not isinstance(stamp, Mapping) or not isinstance(stamp.get("id"), str) or not isinstance(stamp.get("version"), str):
        return CheckResult(False, ["the line carries no _schema with a string id and version"])
    pair = (stamp["id"], stamp["version"])
    doc = (extra or {}).get(pair) or schema_for(pair)
    if doc is None:
        return CheckResult(False, [f"no schema for {pair[0]}@{pair[1]}"], f"no schema for {pair[0]}@{pair[1]}")
    return check_record(line, doc)


def _token(key: Any) -> str:
    """One RFC 6901 reference token: `~` and `/` inside a key are escaped."""
    return _escape_pointer(key if isinstance(key, str) else _json_key(key))


def _fail(errors: List[str], path: str, message: str, where: Optional[str] = None) -> None:
    errors.append(_Issue(f"{_at(path)} {message}", _at(path if where is None else where)))


def _at(path: str) -> str:
    return path or "/"


def _kind(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "integer" if v.is_integer() else "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (list, tuple)):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _is_type(v: Any, t: str) -> bool:
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool) and (not isinstance(v, float) or (v == v and v not in (float("inf"), float("-inf"))))
    if t == "integer":
        return _kind(v) == "integer"
    return _kind(v) == t


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _satisfies(schema: Any, value: Any) -> bool:
    scratch: List[str] = []
    _validate(schema, value, "", scratch)
    return not scratch


_REGEX_CACHE: Dict[str, Any] = {}
# ECMAScript's `\s`: WhiteSpace and LineTerminator. Python's is a different set either way: with
# re.ASCII it lacks U+00A0 and the rest, without it it adds U+001C to U+001F and U+0085 and lacks
# U+FEFF. Written as the inside of a character class.
_JS_SPACE = r"\t\n\x0b\x0c\r \xa0  -     　﻿"
_JS_DOT = r"[^\n\r  ]"
_JS_QUANTIFIER = re.compile(r"\{([0-9]+)(?:,([0-9]*))?\}")
_HEX = frozenset("0123456789abcdefABCDEF")
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_ASCII_WORD = _ASCII_LETTERS | frozenset("0123456789")
_SYNTAX = frozenset("^$\\.*+?()[]{}|/")
_CONTROL = {"t": 9, "n": 10, "r": 13, "f": 12, "v": 11}


def _is_hex(h: str) -> bool:
    return bool(h) and all(c in _HEX for c in h)


def _lit(cp: int) -> str:
    """One code point as `re` source that means only itself, inside a class or outside one."""
    c = chr(cp)
    if c in _ASCII_WORD:
        return c
    return "\\u%04x" % cp if cp < 0x10000 else "\\U%08x" % cp


def _js_escape(p: str, i: int, in_class: bool) -> Optional[Tuple[str, Any, int]]:
    """The escape at `p[i]` (a backslash) as ECMAScript reads it with the `u` flag: `("char", code
    point, next)`, `("set", re source, next)` or `("assert", re source, next)`. None for one this
    writer does not translate, and for one ECMAScript rejects."""
    c = p[i + 1:i + 2]
    if c == "":
        return None
    if c in ("d", "D", "w", "W"):
        return ("set", "\\" + c, i + 2)
    if c == "s":
        return ("set", _JS_SPACE if in_class else "[" + _JS_SPACE + "]", i + 2)
    if c == "S":
        return None if in_class else ("set", "[^" + _JS_SPACE + "]", i + 2)
    if c == "b":
        return ("char", 8, i + 2) if in_class else ("assert", "\\b", i + 2)
    if c == "B":
        return None if in_class else ("assert", "\\B", i + 2)
    if c in _CONTROL:
        return ("char", _CONTROL[c], i + 2)
    if c == "0":
        return None if p[i + 2:i + 3] in tuple("0123456789") else ("char", 0, i + 2)
    if c == "x":
        h = p[i + 2:i + 4]
        return ("char", int(h, 16), i + 4) if len(h) == 2 and _is_hex(h) else None
    if c == "u":
        if p[i + 2:i + 3] == "{":
            j = p.find("}", i + 3)
            h = p[i + 3:j] if j != -1 else ""
            if not _is_hex(h) or len(h) > 8:
                return None
            cp, nxt = int(h, 16), j + 1
        else:
            h = p[i + 2:i + 6]
            if len(h) != 4 or not _is_hex(h):
                return None
            cp, nxt = int(h, 16), i + 6
        # A surrogate escape is half of a pair in ECMAScript and a code point of its own here.
        if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
            return None
        return ("char", cp, nxt)
    if c == "c":
        letter = p[i + 2:i + 3]
        return ("char", ord(letter) % 32, i + 3) if letter in _ASCII_LETTERS and letter else None
    if c in _SYNTAX or (c == "-" and in_class):
        return ("char", ord(c), i + 2)
    return None


def _js_class(p: str, i: int) -> Optional[Tuple[str, int]]:
    """The character class at `p[i]` (a `[`) as `re` source, and the index after it."""
    n = len(p)
    j = i + 1
    negated = p[j:j + 1] == "^"
    if negated:
        j += 1
    out: List[str] = []

    def atom(k: int) -> Optional[Tuple[str, Any, int]]:
        if p[k] == "\\":
            return _js_escape(p, k, True)
        if 0xD800 <= ord(p[k]) <= 0xDFFF:
            return None
        return ("char", ord(p[k]), k + 1)

    while True:
        if j >= n:
            return None
        if p[j] == "]":
            j += 1
            break
        a = atom(j)
        if a is None:
            return None
        kind, payload, j = a
        if p[j:j + 1] == "-" and j + 1 < n and p[j + 1] != "]":
            b = atom(j + 1)
            # ECMAScript with the `u` flag rejects a range whose end is a class, or out of order.
            if b is None or kind != "char" or b[0] != "char" or b[1] < payload:
                return None
            out.append(_lit(payload) + "-" + _lit(b[1]))
            j = b[2]
        else:
            out.append(_lit(payload) if kind == "char" else payload)
    if not out:
        return None  # `[]` matches nothing and `[^]` anything in ECMAScript; `re` reads neither so
    return "[" + ("^" if negated else "") + "".join(out) + "]", j


def _js_translate(p: str) -> Optional[str]:
    r"""An ECMAScript pattern (read with the `u` flag, as JSON Schema says) as `re` source with the
    same meaning, or None. Every construct is either translated on purpose or refused: nothing is
    copied across on the hope that the two languages agree.

    Translated: literals; `.` (anything but the four line terminators); `^` and `$` (the ends of
    the input); `\d \D \w \W \b \B` (ASCII, with re.ASCII); `\s \S` (ECMAScript's set, spelled
    out); `\t \n \r \f \v \0 \xHH \uHHHH \u{H…} \cX` and an escaped syntax character; classes with
    ranges; groups `(…)` and `(?:…)`; lookahead; lookbehind, where `re` accepts it (fixed width);
    `* + ? {n} {n,} {n,m}` and their lazy forms; `|`.

    Refused: `\p{…}` and `\P{…}`; named groups and `\k<…>`; back-references; inline flags; `\S`
    inside a class; the empty classes `[]` and `[^]`; a surrogate, escaped or not; and everything
    ECMAScript itself rejects with the `u` flag, such as `\-` outside a class, a quantifier with
    nothing to repeat, or a lone `{`, `}` or `]`."""
    out: List[str] = []
    stack: List[bool] = []  # one entry per open group: whether it is a lookaround
    i, n, can_repeat = 0, len(p), False
    while i < n:
        c = p[i]
        if 0xD800 <= ord(c) <= 0xDFFF:
            return None
        if c == "\\":
            e = _js_escape(p, i, False)
            if e is None:
                return None
            kind, payload, i = e
            out.append(_lit(payload) if kind == "char" else payload)
            can_repeat = kind != "assert"
        elif c == "[":
            cls = _js_class(p, i)
            if cls is None:
                return None
            out.append(cls[0])
            i, can_repeat = cls[1], True
        elif c == "(":
            head = next((h for h in ("(?:", "(?=", "(?!", "(?<=", "(?<!") if p.startswith(h, i)), None)
            if head is None:
                if p.startswith("(?", i):
                    return None
                head = "("
            out.append(head)
            stack.append(head not in ("(", "(?:"))
            i, can_repeat = i + len(head), False
        elif c == ")":
            if not stack:
                return None
            out.append(")")
            i, can_repeat = i + 1, not stack.pop()
        elif c in ("|", "^", "$"):
            out.append(r"\Z" if c == "$" else c)
            i, can_repeat = i + 1, False
        elif c == ".":
            out.append(_JS_DOT)
            i, can_repeat = i + 1, True
        elif c in ("*", "+", "?", "{"):
            if not can_repeat:
                return None
            if c == "{":
                m = _JS_QUANTIFIER.match(p, i)
                if m is None or (m.group(2) and int(m.group(2)) < int(m.group(1))):
                    return None
                out.append(m.group(0))
                i = m.end()
            else:
                out.append(c)
                i += 1
            if p[i:i + 1] == "?":
                out.append("?")
                i += 1
            can_repeat = False
        elif c in ("}", "]"):
            return None
        else:
            out.append(_lit(ord(c)))
            i, can_repeat = i + 1, True
    return None if stack else "".join(out)


def _js_regex(pattern: str) -> Any:
    """A schema's `pattern` compiled so that it matches what ECMAScript would match, or None when
    this writer cannot do that (`_js_translate`), or `re` will not compile the translation. None
    is "cannot evaluate", which `schema_subset_gap` reports; the engine's message, which quotes
    the pattern, goes nowhere."""
    cached = _REGEX_CACHE.get(pattern)
    if cached is not None:
        return cached or None
    compiled: Any = False
    try:
        source = _js_translate(pattern)
        if source is not None:
            compiled = re.compile(source, re.ASCII)
    except Exception:
        compiled = False
    _REGEX_CACHE[pattern] = compiled
    return compiled or None


def _validate(schema: Any, value: Any, path: str, errors: List[str]) -> None:
    if schema is True or schema is None:
        return
    if schema is False:
        _fail(errors, path, f"is not allowed here")
        return
    if not isinstance(schema, dict):
        raise _Unsupported("a schema that is not an object or a boolean")
    for k in schema:
        if k not in _SUPPORTED:
            raise _Unsupported(k)
    s = schema
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_is_type(value, t) for t in types):
            _fail(errors, path, f"is {_kind(value)}, not {' or '.join(types)}")
    if "const" in s and not _same(value, s["const"]):
        _fail(errors, path, f"must be {_dumps(s['const'])}")
    if "enum" in s and not any(_same(value, o) for o in s["enum"]):
        _fail(errors, path, f"must be one of {_dumps(s['enum'])}")
    if "not" in s and _satisfies(s["not"], value):
        _fail(errors, path, f"must not match the excluded shape")
    for sub in s.get("allOf", []):
        _validate(sub, value, path, errors)
    if "anyOf" in s and not any(_satisfies(sub, value) for sub in s["anyOf"]):
        _fail(errors, path, f"matches none of the allowed shapes")
    if "oneOf" in s and sum(1 for sub in s["oneOf"] if _satisfies(sub, value)) != 1:
        _fail(errors, path, f"must match exactly one of the allowed shapes")
    if "if" in s:
        branch = s.get("then") if _satisfies(s["if"], value) else s.get("else")
        if branch is not None:
            _validate(branch, value, path, errors)

    if isinstance(value, str):
        n = len(value)
        if _is_count(s.get("minLength")) and n < s["minLength"]:
            _fail(errors, path, f"is shorter than {s['minLength']}")
        if _is_count(s.get("maxLength")) and n > s["maxLength"]:
            _fail(errors, path, f"is longer than {s['maxLength']}")
        if isinstance(s.get("pattern"), str):
            compiled = _js_regex(s["pattern"])
            if compiled is None:
                raise _Unsupported(_PATTERN_GAP)
            if not compiled.search(value):
                _fail(errors, path, f"does not match {s['pattern']}")
        if isinstance(s.get("format"), str):
            f = _FORMATS.get(s["format"])
            if f is None:
                raise _Unsupported(f"format {s['format']}")
            if not f.match(value):
                _fail(errors, path, f"is not a {s['format']}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for key, bad, word in (("minimum", lambda x, b: x < b, "below"), ("maximum", lambda x, b: x > b, "above"),
                               ("exclusiveMinimum", lambda x, b: x <= b, "not above"), ("exclusiveMaximum", lambda x, b: x >= b, "not below")):
            b = s.get(key)
            if _is_number(b) and bad(value, b):
                _fail(errors, path, f"is {word} {b}")

    if isinstance(value, (list, tuple)):
        if _is_count(s.get("minItems")) and len(value) < s["minItems"]:
            _fail(errors, path, f"has fewer than {s['minItems']} items")
        if _is_count(s.get("maxItems")) and len(value) > s["maxItems"]:
            _fail(errors, path, f"has more than {s['maxItems']} items")
        if "items" in s:
            if isinstance(s["items"], list):
                raise _Unsupported("items as a tuple")
            for i, item in enumerate(value):
                _validate(s["items"], item, f"{path}/{i}", errors)

    if isinstance(value, dict):
        if isinstance(s.get("required"), list):
            for k in s["required"]:
                if k not in value:
                    _fail(errors, path, f"is missing {k}", f"{path}/{_token(k)}")
        if _is_count(s.get("minProperties")) and len(value) < s["minProperties"]:
            _fail(errors, path, f"has fewer than {s['minProperties']} properties")
        if _is_count(s.get("maxProperties")) and len(value) > s["maxProperties"]:
            _fail(errors, path, f"has more than {s['maxProperties']} properties")
        props = s.get("properties") or {}
        ap = s.get("additionalProperties")
        for k, v in value.items():
            if k in props:
                _validate(props[k], v, f"{path}/{_token(k)}", errors)
            elif ap is False:
                _fail(errors, path, f"must not carry {k}", f"{path}/{_token(k)}")
            elif ap is not None and ap is not True:
                _validate(ap, v, f"{path}/{_token(k)}", errors)


# ---- sinks ---------------------------------------------------------------------------------


class FdSink:
    """A sink on a file descriptor that delivers the whole line: a partial write continues from
    where it stopped, and EAGAIN (a full pipe on a descriptor someone left non-blocking) waits a
    millisecond and tries again, which is what a blocking write would have done. A closed reader
    (EPIPE) raises, and the run reports it as a sink failure."""

    def __init__(self, fd: int):
        self.fd = fd

    def write(self, line: str) -> None:
        data = line.encode("utf-8")
        view = memoryview(data)
        off = 0
        while off < len(data):
            try:
                off += os.write(self.fd, view[off:])
            except BlockingIOError:
                time.sleep(0.001)


# ---- stray output capture (spec section 1.2) -----------------------------------------------
# While the writer runs, `sys.stdout` and `sys.stderr` are replaced with objects that put whatever
# is written to them into the run's receipt as a step, a line at a time. Text written before the
# receipt exists is held and written after the head. This contains `print`, `logging` (whose
# default handler looks `sys.stderr` up when it writes), `warnings`, `traceback.print_exc` and
# anything else that writes through those two names. It does not contain a write to file
# descriptor 1 or 2 itself: a C extension, a subprocess inheriting the descriptor, `os.write`, or a
# handler that kept a reference to the original stream before `main` started. The README names
# these as the documented exceptions (spec section 6).


class _BufferCapture:
    def __init__(self, owner: "_StreamCapture"):
        self._owner = owner

    def write(self, b: Any) -> int:
        data = bytes(b)
        self._owner.write(data.decode("utf-8", errors="replace"))
        return len(data)

    def flush(self) -> None:
        pass


class _StreamCapture(io.TextIOBase):
    def __init__(self, capture: "_Capture", name: str):
        super().__init__()
        self._capture, self._name = capture, name
        self.buffer = _BufferCapture(self)

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return "utf-8"

    @property
    def errors(self) -> str:  # type: ignore[override]
        return "strict"

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise io.UnsupportedOperation("parley_emit is capturing this stream; it has no descriptor to write around the capture")

    def write(self, s: Any) -> int:
        if not isinstance(s, str):
            raise TypeError(f"write() argument must be str, not {type(s).__name__}")
        self._capture.take(self._name, s)
        return len(s)

    def flush(self) -> None:
        pass


class _Capture:
    def __init__(self) -> None:
        self.run: Optional[Run] = None
        self.pending: List[Tuple[str, str]] = []
        self.partial: Dict[str, str] = {"stdout": "", "stderr": ""}
        self.released = False
        self.lock = threading.RLock()
        self.saved = (sys.stdout, sys.stderr)
        sys.stdout = _StreamCapture(self, "stdout")  # type: ignore[assignment]
        sys.stderr = _StreamCapture(self, "stderr")  # type: ignore[assignment]

    def take(self, name: str, s: str) -> None:
        with self.lock:
            if self.released:
                return
            text = self.partial[name] + s
            cut = text.rfind("\n")
            if cut < 0:
                self.partial[name] = text
                return
            self.partial[name] = text[cut + 1:]
            self._record(name, text[:cut + 1])

    def _record(self, name: str, text: str) -> None:
        if self.run is None:
            self.pending.append((name, text))
            return
        if self.run.ended:
            return
        try:
            self.run.writer_step("captured stray output", f"something in the process wrote to sys.{name}; stdout and stderr carry only protocol lines (spec section 1.2), so the text is kept here", {"stream": name, "text": text})
        except Exception:
            pass  # the run ended between the check and the write

    def attach(self, run: "Run") -> None:
        with self.lock:
            self.run = run
            held, self.pending = self.pending, []
            for name, text in held:
                self._record(name, text)

    def release(self) -> None:
        with self.lock:
            if self.released:
                return
            for name in ("stdout", "stderr"):
                if self.partial[name]:
                    rest, self.partial[name] = self.partial[name], ""
                    self._record(name, rest)
            self.released = True
            sys.stdout, sys.stderr = self.saved


# ---- one run (spec section 3) ----------------------------------------------------------------


class Run:
    """One execution: a single sequence across stdout, stderr and the receipt; the bootstrap line
    first, the head next, `end` last and immutable; every record's payload scrubbed of declared
    secrets before any copy leaves the process."""

    def __init__(self, *, tool: str, v: str, id: str, session: Optional[str], dry_run: bool, stdout: Any, stderr: Any,
                 receipt_fd: int, receipt_path: str, receipt_dir: str, secret_values: Set[str], now: Callable[[], int],
                 cwd: str, command: str, resolved: Any, inputs: List[Record], head_redacted: bool,
                 human: Optional[Callable[[Record], Optional[str]]],
                 schemas: Optional[Mapping[Tuple[str, str], Any]] = None):
        # Every schema document the writer holds, by `(id, version)`: the embedded ones and the
        # ones the tool declared. A record redaction changed is validated against its own pair's
        # document before it is written (spec section 5.3, flyingrobots/parley#131).
        self._schemas: Mapping[Tuple[str, str], Any] = schemas or {}
        # A record was withheld because redaction made it invalid: like a sink failure, the run
        # closes with 4 (spec sections 3.4, 5.3).
        self._output_refused = False
        self.id, self.tool, self.v, self.session = id, tool, v, session
        self.dry_run, self.receipt_path, self.receipt_dir, self.cwd = dry_run, receipt_path, receipt_dir, cwd
        self._stdout, self._stderr, self._fd = stdout, stderr, receipt_fd
        self._secrets, self._now, self._command, self._resolved, self._inputs = secret_values, now, command, resolved, inputs
        self._human = human
        self._seq = -1
        self._closed = False
        self._receipt_open = True
        self._error_reported = False
        self._redacted_any = head_redacted
        self._failed: Set[str] = set()
        self._sidecar_failed = False
        self._deferred: List[Tuple[str, BaseException]] = []
        self._inputs_settled = False
        self._supplied: Dict[str, bytes] = {}
        self._unread: Dict[str, str] = {}
        self._final: Optional[int] = None
        self._renderer_failed = False
        self._renderer_warning: Optional[str] = None
        self._depth = 0
        self._lock = threading.RLock()

    @property
    def ended(self) -> bool:
        return self._closed

    @property
    def status(self) -> Optional[int]:
        return self._final

    @property
    def sink_failed(self) -> bool:
        return bool(self._failed) or self._sidecar_failed

    @property
    def redaction_refused(self) -> bool:
        """True when a record redaction changed was withheld, because it was left invalid under
        its declared schema or because the writer could not evaluate that schema (spec section
        5.3): the run closes with 4."""
        return self._output_refused

    # -- emission ------------------------------------------------------------------------------

    def _next(self, t: Optional[int] = None) -> Tuple[int, int]:
        self._seq += 1
        return self._seq, max(0, int(self._now())) if t is None else t

    def _envelope(self, payload: Record, schema: SchemaRef, at: Tuple[int, int]) -> Record:
        sid, ver = _pair(schema)
        rest = {k: v for k, v in payload.items() if k != "event"}
        return {"event": payload.get("event"), "t": at[1], "seq": at[0], "run": self.id, **rest, "_schema": {"id": sid, "version": ver}}

    @staticmethod
    def _refuse_envelope_keys(obj: Optional[Mapping[str, Any]], what: str) -> None:
        if not obj:
            return
        for k in _ENVELOPE_KEYS:
            if k in obj:
                raise ValueError(f"{what} must not carry {k}; the writer owns the envelope (spec section 1.3)")

    def _write(self, sink: str, text: str, defer: bool = False) -> bool:
        if sink in self._failed:
            return False
        try:
            if sink == "receipt":
                if not self._receipt_open:
                    return False
                data = text.encode("utf-8")
                off = 0
                while off < len(data):
                    off += os.write(self._fd, data[off:])
            else:
                (self._stdout if sink == "stdout" else self._stderr).write(text)
            return True
        except Exception as e:  # a sink failure is an outcome, not something to swallow (5.4)
            self._failed.add(sink)
            if defer:
                self._deferred.append((sink, e))
            elif not self._closed:
                self._report_sink_failure(sink, e)
            return False

    def _write_or_skip(self, sink: str, text: str, defer: bool = False) -> bool:
        return True if text == "" else self._write(sink, text, defer)

    def _report_sink_failure(self, sink: str, e: BaseException) -> None:
        msg = str(e) or type(e).__name__
        self._emit({"stderr": sink != "stderr", "receipt": sink != "receipt"},
                   {"event": "error", "code": "sink.sidecar_failed" if sink == "sidecar" else "sink.write_failed",
                    "problem": f"writing to {sink} failed: {msg}", "remedy": "the run will close with status 4; whatever other sinks received is preserved"},
                   SCHEMA_IDS["error"], writer=True)

    def _prose(self, obj: Record) -> str:
        custom: Optional[str] = None
        if self._human is not None and not self._renderer_failed:
            try:
                custom = self._human(obj)
            except Exception as e:
                custom = None
                self._renderer_failed = True
                self._renderer_warning = str(e) or type(e).__name__
        if isinstance(custom, str):
            return custom if custom.endswith("\n") else custom + "\n"
        ev = obj.get("event")
        if ev == "run":
            return ""
        if ev == "end":
            if obj.get("status") == 0:
                return ""
            return f"end: status {obj.get('status')}{', receipt redacted' if obj.get('redacted') else ''}; receipt at {obj.get('receipt')}\n"
        if ev in ("error", "warning"):
            remedy = f" ({obj['remedy']})" if obj.get("remedy") else ""
            return f"{ev} {obj.get('code')}: {obj.get('problem')}{remedy}\n"
        return f"{ev}: {_dumps(obj)}\n"

    def _scrub_payload(self, payload: Record, found: List[str], writer: bool, verbatim: Optional[str] = None) -> Record:
        """Scrub everything but the event name and, for a writer-built record, the one field
        named by `verbatim`: the schema document of a `schema` line, a static declaration a
        secret cannot reach (spec section 5.3, flyingrobots/parley#111), or the head's
        `redacted`, which holds indexes, JSON Pointers and names the caller has already
        scrubbed. A writer-built record's field names are never renamed."""
        rest = {k: v for k, v in payload.items() if k != "event" and k != verbatim}
        scrubbed = scrub(rest, self._secrets, "", found, DIGEST_KEYS if writer else None, not writer, not writer)
        if verbatim is not None and verbatim in payload:
            # Put back in its own place, so the record's key order is the one it was built with.
            scrubbed = {k: (payload[k] if k == verbatim else scrubbed[k]) for k in payload if k != "event"}
        return scrubbed if "event" not in payload else {"event": payload["event"], **scrubbed}

    def _emit(self, to: Mapping[str, bool], payload: Record, schema: SchemaRef, receipt_extra: Optional[Record] = None,
              writer: bool = False, no_sidecar: bool = False, defer: bool = False, verbatim: Optional[str] = None,
              replaced: Sequence[str] = ()) -> int:
        """Emit one event. `replaced` is pointers into this record where the caller replaced a
        secret before handing it over; each gets its `redaction` event as though the record's own
        scrub had found it."""
        with self._lock:
            if self._closed:
                raise ParleyClosed()
            self._refuse_envelope_keys(payload, "a record")
            self._refuse_envelope_keys(receipt_extra, "receipt_extra")
            found: List[str] = []
            scrubbed = self._scrub_payload(payload, found, writer, verbatim if writer else None)
            extra_found: List[str] = []
            extra = self._scrub_payload(receipt_extra, extra_found, writer) if receipt_extra else None
            # Serialise before taking a seq: a record that is not JSON is the tool's error, raised to
            # the tool, and must not leave a gap in the run's one counter (spec section 1.3).
            _dumps(scrubbed)
            if extra:
                _dumps(extra)
                # The copies of one event agree on every field they share (spec section 1.3):
                # compared as scrubbed, since that is what is written.
                for k, v in extra.items():
                    if k in scrubbed and json.dumps(v, sort_keys=True) != json.dumps(scrubbed[k], sort_keys=True):
                        raise ValueError(f"receipt_extra[{k!r}] differs from the record's {k!r}; the copies of an event must agree on every field they share (spec section 1.3)")
            # A tool's record the scrub changed is validated as each sink would receive it, before
            # any copy is written and before a seq is taken (spec section 5.3,
            # flyingrobots/parley#131). A writer-built record is never checked; what its scrub
            # leaves alone so that it stays valid is listed at DIGEST_KEYS. The error this raises
            # is itself writer-built, so it cannot raise another.
            t: Optional[int] = None
            if not writer and (found or extra_found):
                t = max(0, int(self._now()))
                self._refuse_redaction_conflict(to, payload, receipt_extra, scrubbed, extra, schema, (self._seq + 1, t), found + extra_found)
            at = self._next(t)
            rec = self._envelope(scrubbed, schema, at)
            self._depth += 1
            try:
                human = self._human is not None
                if to.get("stdout"):
                    self._write_or_skip("stdout", self._prose(rec) if human else _dumps(rec) + "\n", defer)
                if to.get("stderr"):
                    self._write_or_skip("stderr", self._prose(rec) if human else _dumps(rec) + "\n", defer)
                if to.get("receipt"):
                    # A shared field is written from the payload, so the copies agree byte for byte on it.
                    full = self._envelope({**scrubbed, **{k: v for k, v in extra.items() if k not in scrubbed}}, schema, at) if extra else rec
                    text = _dumps(full)
                    if not no_sidecar and len(text.encode("utf-8")) > SIDECAR_THRESHOLD:
                        self._sidecar(at[0], text)
                    else:
                        self._write("receipt", text + "\n")
                for p in dict.fromkeys(found + extra_found + list(replaced)):
                    self._redaction(at[0], p)
            finally:
                self._depth -= 1
            if self._depth == 0 and self._renderer_warning is not None and not self._closed:
                msg, self._renderer_warning = self._renderer_warning, None
                self.writer_warning("human.renderer_failed", f"the tool's --human renderer raised: {msg}; the default rendering is used for the rest of the run", remedy="fix the renderer; the receipt is complete regardless")
            return at[0]

    def _copies(self, to: Mapping[str, bool], payload: Mapping[str, Any], extra: Optional[Mapping[str, Any]], schema: SchemaRef, at: Tuple[int, int]) -> List[Record]:
        """The copies of one event as the sinks would receive them: the stream copy, and the
        receipt copy when it carries more."""
        out: List[Record] = []
        if to.get("stdout") or to.get("stderr") or not extra:
            out.append(self._envelope(dict(payload), schema, at))
        if to.get("receipt") and extra:
            out.append(self._envelope({**payload, **{k: v for k, v in extra.items() if k not in payload}}, schema, at))
        return out

    def _refuse_redaction_conflict(self, to: Mapping[str, bool], payload: Record, receipt_extra: Optional[Record], scrubbed: Record,
                                   extra: Optional[Record], schema: SchemaRef, at: Tuple[int, int], redacted: List[str]) -> None:
        """Refuse a record that redaction made invalid under its declared schema, or that the
        writer cannot show is valid (spec section 5.3, flyingrobots/parley#131,
        flyingrobots/parley#144). Called before a seq is taken, with the seq and time the record
        would get, and only for a tool's record the scrub changed.

        A pair with no schema document here is exempt, as section 5.3 says. A pair whose document
        uses a construct outside the checker's subset is not: the writer holds the schema and
        cannot evaluate it, so it cannot show the redacted record is valid, and it withholds the
        record as `redaction.schema_unchecked`. Publishing it would be the silent invalid line
        the rule exists to prevent.

        Otherwise each copy is checked as scrubbed and as the tool handed it over; a failure the
        scrubbed copy has and the original did not is one redaction caused, and is
        `redaction.schema_conflict`. A record already invalid in the same way is not this rule's
        business and is written as before.

        Either way nothing of the record is written. One writer-built error names the schema pair
        and the fields by JSON Pointer, and deliberately nothing the checker said: a validator's
        message can quote the schema or the value, and the value is the secret or sits beside it.
        The construct the checker could not evaluate is part of the schema, so it is not on the
        line either; it is on the exception. The run is marked to close with 4, since a record
        the writer would not write is an output it could not write (spec section 3.4), and the
        refusal is raised."""
        sid, ver = _pair(schema)
        doc = self._schemas.get((sid, ver))
        if doc is None:
            return
        after = self._copies(to, scrubbed, extra, schema, at)
        before = self._copies(to, payload, receipt_extra, schema, at)
        raw: List[str] = []
        for now_, then in zip(after, before):
            verdict = check_record(now_, doc)
            if verdict.ok:
                continue
            if verdict.unsupported is not None:
                self._refuse_unchecked(payload, sid, ver, redacted, verdict.unsupported)
            was = check_record(then, doc)
            already = set() if (was.ok or was.unsupported is not None) else set(zip(was.pointers, was.errors))
            for p, e in zip(verdict.pointers, verdict.errors):
                if (p, e) not in already and p not in raw:
                    raw.append(p)
        if not raw:
            return
        # A pointer the checker reports can name a property the record no longer has, because the
        # scrub renamed it, and that name is then the secret. Each is scrubbed token by token
        # before it goes anywhere; the line's own scrub then sees the same strings the exception
        # is given.
        pointers = [scrub_pointer(p, self._secrets) for p in raw]
        # The receipt still records that a secret was replaced in the error line, and where.
        replaced: List[str] = []
        if pointers != raw:
            replaced = ["/problem"] + [f"/detail/at/{i}" for i, p in enumerate(pointers) if p != raw[i]]
        problem = f"the {payload.get('event')} record was not published: replacing a declared secret at {', '.join(redacted)} left it invalid under {sid}@{ver} at {', '.join(pointers)}"
        self._output_refused = True
        self._emit({"stderr": True, "receipt": True},
                   {"event": "error", "code": REDACTION_CONFLICT_CODE, "problem": problem,
                    "remedy": "keep a declared secret out of any field whose schema the literal [redacted] cannot satisfy: leave the field out, or declare it as an unconstrained string; the run will close with status 4",
                    "detail": {"schema": {"id": sid, "version": ver}, "at": pointers, "redacted": list(redacted)}},
                   SCHEMA_IDS["error"], writer=True, replaced=replaced)
        raise ParleyRedactionConflict({"id": sid, "version": ver}, [replace_secrets(p, self._secrets) for p in pointers],
                                      f"{replace_secrets(problem, self._secrets)}; reported as {REDACTION_CONFLICT_CODE}")

    def _refuse_unchecked(self, payload: Record, sid: str, ver: str, redacted: List[str], construct: str) -> None:
        """Withhold a record the scrub changed whose schema document the writer holds and cannot
        evaluate (spec section 5.3, flyingrobots/parley#144). The error line names the pair and
        the pointers the scrub replaced and nothing of the schema; `construct` goes to the
        exception only, and not even there when it would carry a declared secret value, since an
        exception's message is not scrubbed. Always raises."""
        problem = (f"the {payload.get('event')} record was not published because it could not be checked: a declared secret was replaced at {', '.join(redacted)}, "
                   f"and this writer cannot evaluate the schema document it holds for {sid}@{ver}, so the redacted record was not validated against it")
        self._output_refused = True
        self._emit({"stderr": True, "receipt": True},
                   {"event": "error", "code": REDACTION_UNCHECKED_CODE, "problem": problem,
                    "remedy": "keep the type's declared schema within the keywords this writer's checker evaluates (its README lists them), or keep declared secrets out of records of this type; the record was not shown to be invalid, and the value was replaced, not exposed; the run will close with status 4",
                    "detail": {"schema": {"id": sid, "version": ver}, "redacted": list(redacted)}},
                   SCHEMA_IDS["error"], writer=True)
        # The exception's text is the published line's, scrubbed as the line is.
        named = None if carries_secret(construct, self._secrets) else construct
        raise ParleyRedactionUnchecked({"id": sid, "version": ver}, [replace_secrets(p, self._secrets) for p in redacted], named,
                                       f"{replace_secrets(problem, self._secrets)}{'' if named is None else f': the schema uses {named}'}; reported as {REDACTION_UNCHECKED_CODE}")

    def _sidecar(self, source: int, text: str) -> None:
        rel = f"{self.id}/{source}.json"
        data = text.encode("utf-8")
        try:
            os.makedirs(os.path.join(self.receipt_dir, self.id), exist_ok=True)
            fd = os.open(os.path.join(self.receipt_dir, rel), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            try:
                off = 0
                while off < len(data):
                    off += os.write(fd, data[off:])
            finally:
                os.close(fd)
        except OSError as e:
            # The receipt itself is fine: keep the record inline so the bundle stays complete (5),
            # then say what failed; the run closes with 4 because a write failed (5.4).
            self._sidecar_failed = True
            self._write("receipt", text + "\n")
            self._report_sink_failure("sidecar", e)
            return
        at = self._next()
        self._write("receipt", _dumps(self._envelope({"event": "sidecar", "source": source, "path": rel, "bytes": len(data), "sha256": sha256(data)}, SCHEMA_IDS["sidecar"], at)) + "\n")

    def _redaction(self, in_seq: int, pointer: str) -> None:
        self._redacted_any = True
        at = self._next()
        self._write("receipt", _dumps(self._envelope({"event": "redaction", "in": in_seq, "at": pointer}, SCHEMA_IDS["redaction"], at)) + "\n")

    # -- internal steps of the lifecycle ---------------------------------------------------------

    def _bootstrap(self, inv: Optional[str]) -> None:
        rec: Record = {"event": "run", "tool": self.tool, "v": self.v}
        if inv:
            rec["inv"] = inv
        if self.session:
            rec["session"] = self.session
        rec["paths"] = {"receipt": self.receipt_path}
        if self.dry_run:
            rec["dry_run"] = True
        self._emit({"stdout": True}, rec, SCHEMA_IDS["bootstrap"], writer=True, defer=True)

    def _head(self, fields: Record) -> None:
        """The receipt head. `redacted` is written as the caller built it: its JSON Pointers are
        locations in the already-scrubbed `resolved`, and a second scrub of a pointer as a string
        could only damage it (a secret equal to `/token` would turn the pointer `/token` into
        something that is not a pointer)."""
        self._emit({"receipt": True}, {"event": "receipt.head", **fields}, SCHEMA_IDS["head"], writer=True, no_sidecar=True, verbatim="redacted")

    def _flush_deferred(self) -> None:
        held, self._deferred = self._deferred, []
        for sink, e in held:
            if not self._closed:
                self._report_sink_failure(sink, e)

    def _describe(self, record: Record, schema: SchemaRef, verbatim: Optional[str] = None) -> int:
        return self._emit({"stdout": True, "receipt": True}, record, schema, writer=True, verbatim=verbatim)

    def writer_warning(self, code: str, problem: str, **fields: Any) -> int:
        """A warning the writer itself raises; its code is the writer's own identifier and is not
        scrubbed. Tools call `warning`."""
        return self._emit({"stderr": True, "receipt": True}, {"event": "warning", **_diagnostic(code, problem, fields)}, SCHEMA_IDS["warning"], writer=True)

    def writer_step(self, decision: str, because: str, detail: Any = None) -> int:
        """A decision the writer itself records, such as retention or captured stray output
        (flyingrobots/parley#161). It is writer-built: its field names are the protocol's and are
        never renamed, and it is never withheld by the redaction check, so a declared secret whose
        value is `decision` cannot cost a run a record the tool had no part in. Every string in
        it is still scrubbed: captured text, a file name and the writer's own prose alike, except
        under a key in `DIGEST_KEYS`, so a `detail` built here never puts the tool's text under
        one. Tools call `step`."""
        payload: Record = {"event": "receipt.step", "decision": decision, "because": because}
        if detail is not None:
            payload["detail"] = detail
        return self._emit({"receipt": True}, payload, SCHEMA_IDS["step"], writer=True)

    def writer_error(self, code: str, problem: str, receipt_extra: Optional[Record] = None, **fields: Any) -> int:
        """An error the writer itself reports, such as `uncaught.exception` for an exception that
        escaped the handler (flyingrobots/parley#161). It is writer-built, like `writer_warning`:
        the `code` is the writer's own and is not scrubbed, the field names are never renamed and
        the record is never withheld by the redaction check, so `main` can always report the
        failure. The `problem`, the `remedy` and everything in `receipt_extra` carry the tool's
        text (an exception's name and message, a traceback, a path) and are scrubbed. The run
        then closes with status 2, as after `error`. Tools call `error`."""
        d = _diagnostic(code, problem, fields)
        seq = self._emit({"stderr": True, "receipt": True}, {"event": "error", **d}, SCHEMA_IDS["error"], receipt_extra, writer=True)
        self._error_reported = True
        return seq

    # -- the public surface ---------------------------------------------------------------------

    def result(self, record: Record, schema: SchemaRef, receipt_extra: Optional[Record] = None) -> int:
        """A result: to stdout and the receipt. `receipt_extra` goes to the receipt copy only."""
        if not isinstance(record, dict) or not isinstance(record.get("event"), str) or not record["event"]:
            raise ValueError("a result needs an event name")
        return self._emit({"stdout": True, "receipt": True}, record, schema, receipt_extra)

    def page(self, cursor: Optional[str], has_more: bool, record: Optional[Record] = None, receipt_extra: Optional[Record] = None) -> int:
        """One page of unbounded output (spec section 7.2)."""
        if has_more and not cursor:
            raise ValueError("a page with has_more needs a cursor (spec section 7.2)")
        payload: Record = {"event": "page", **(record or {})}
        if cursor:
            payload["cursor"] = cursor
        payload["has_more"] = bool(has_more)
        return self._emit({"stdout": True, "receipt": True}, payload, SCHEMA_IDS["page"], receipt_extra)

    _NO_DETAIL = object()

    def step(self, decision: str, because: str, detail: Any = _NO_DETAIL) -> int:
        """One decision and why, receipt only (spec section 5)."""
        payload: Record = {"event": "receipt.step", "decision": decision, "because": because}
        if detail is not Run._NO_DETAIL:
            payload["detail"] = detail
        return self._emit({"receipt": True}, payload, SCHEMA_IDS["step"])

    def warning(self, code: str, problem: str, **fields: Any) -> int:
        """A recovered condition: stderr and the receipt; never changes the status (spec 6.1)."""
        return self._emit({"stderr": True, "receipt": True}, {"event": "warning", **_diagnostic(code, problem, fields)}, SCHEMA_IDS["warning"])

    def error(self, code: str, problem: str, receipt_extra: Optional[Record] = None, **fields: Any) -> int:
        """A structured error (spec section 6). The run then closes with status 2 unless `end` is
        given another non-zero status."""
        d = _diagnostic(code, problem, fields)
        seq = self._emit({"stderr": True, "receipt": True}, {"event": "error", **d}, SCHEMA_IDS["error"], receipt_extra)
        self._error_reported = True
        return seq

    def input(self, path: str, data: Union[bytes, str]) -> None:
        """Supply the bytes of a declared input the writer cannot read itself, such as stdin. For a
        declared file, `read_input` reads and records in one step."""
        self._supplied[path] = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self._unread.pop(path, None)

    def read_input(self, path: str) -> bytes:
        """Read a declared file input and record it: the bytes returned are the bytes whose digest
        the receipt carries for that input, whatever happens to the file afterwards (spec section
        2.2, flyingrobots/parley#132). This is the way to read a declared file. A file the program
        reads by other means is digested when the handler finishes, and that digest describes the
        file as it is then, which a tool that edits in place has already changed.

        `path` is the declared path, resolved as a declared input is: against the run's `cwd` when
        relative. When the file cannot be read, the input is recorded as `input_unreadable` records
        it and the `OSError` is raised. Raises `ValueError` for a path that is not a declared
        input, for a `stdin` input (supply it with `input`) or a `tree` input, and once the inputs
        are settled. A later `read_input`, `input` or `input_unreadable` for the same path replaces
        the record."""
        with self._lock:
            if self._closed:
                raise ParleyClosed()
            if self._inputs_settled:
                raise ValueError("the inputs are already settled; call read_input before finalise_inputs or end (spec section 2.2)")
            decl = next((i for i in self._inputs if i["path"] == path), None)
            if decl is None:
                raise ValueError(f"{path!r} is not a declared input of this run")
            if decl.get("role") in ("stdin", "tree"):
                raise ValueError(f"{path!r} is a {decl['role']} input; read_input reads a declared file")
            try:
                with open(os.path.join(self.cwd, path), "rb") as f:
                    data = f.read()
            except OSError:
                self.input_unreadable(path)
                raise
            self._supplied[path] = data
            self._unread.pop(path, None)
            return data

    def input_unreadable(self, path: str, code: str = _INPUT_UNREADABLE) -> None:
        """Say that the program could not read a declared input, so the writer records it with
        `error` and no digest, and omits `inv`, rather than reading the path itself at
        finalisation and digesting bytes the program never saw (spec section 2.2,
        flyingrobots/parley#110). Refused for a path that is not a declared input, and once the
        inputs are settled."""
        with self._lock:
            if self._closed:
                raise ParleyClosed()
            if self._inputs_settled:
                raise ValueError("the inputs are already settled; call input_unreadable before finalise_inputs or end (spec section 2.2)")
            if not any(i["path"] == path for i in self._inputs):
                raise ValueError(f"{path!r} is not a declared input of this run")
            if not isinstance(code, str) or not CODE.match(code):
                raise ValueError(f"code {code!r} is not two or more dot-separated lowercase segments (spec section 6)")
            self._supplied.pop(path, None)
            # A code is never scrubbed, so one that carries a declared secret value is not
            # recorded: the writer's own token stands in for it (spec section 5.3).
            self._unread[path] = _INPUT_UNREADABLE if carries_secret(code, self._secrets) else code

    def _descriptor(self, decl: Mapping[str, Any]) -> Record:
        code = self._unread.get(decl["path"])
        if code is None:
            return digest_input(self.cwd, decl, self._supplied.get(decl["path"]))
        return {"path": decl["path"], **({"role": decl["role"]} if decl.get("role") else {}), "error": code}

    def finalise_inputs(self) -> List[Record]:
        """Digest the declared inputs and emit `receipt.inputs`, with `inv` when every input was
        read (spec section 2.2). Idempotent; `end` calls it."""
        with self._lock:
            if self._inputs_settled or not self._inputs:
                self._inputs_settled = True
                return []
            self._inputs_settled = True
            raw = [self._descriptor(i) for i in self._inputs]
            inputs = scrub(raw, self._secrets, "", [], DIGEST_KEYS, False, False)
            inv = compute_inv(self.tool, self.v, self._command, self._resolved, inputs)
            payload: Record = {"event": "receipt.inputs", "inputs": inputs}
            if inv:
                payload["inv"] = inv
            self._emit({"receipt": True}, payload, SCHEMA_IDS["inputs"], writer=True)
            return inputs

    def end(self, status: Optional[int] = None) -> int:
        """Close the run (spec section 3.3). Status defaults to 2 when an error was reported, else 0;
        a sink failure, or a record withheld because redaction made it invalid (section 5.3),
        forces 4. Returns the exit status the process should exit with."""
        with self._lock:
            if self._closed:
                return 4 if self._final is None else self._final
            if status is not None and (isinstance(status, bool) or not isinstance(status, int) or status < 0 or status > 255 or status == 3):
                raise ValueError("end status is an integer 0-255 other than 3 (spec section 3.4)")
            if status == 0 and self._error_reported:
                raise ValueError("a run that reported an error cannot end with status 0 (spec section 3.4); a recovered condition is a warning")
            try:
                self.finalise_inputs()
            except Exception:
                pass  # an unreadable input is already recorded; nothing else can fail here
            s = status if status is not None else (2 if self._error_reported else 0)
            # A record withheld because redaction made it invalid is an output the writer could not
            # write (spec sections 3.4, 5.3): it forces 4 exactly as a sink failure does.
            if self.sink_failed or self._output_refused:
                s = 4
            at = self._next()
            rec = self._envelope(self._scrub_payload({"event": "end", "status": s, "receipt": self.receipt_path, "redacted": self._redacted_any}, [], True), SCHEMA_IDS["end"], at)
            self._closed = True
            ok_out = self._write_or_skip("stdout", self._prose(rec) if self._human is not None else _dumps(rec) + "\n")
            ok_rec = self._write("receipt", _dumps(rec) + "\n")
            self._receipt_open = False
            close_ok = True
            try:
                os.close(self._fd)
            except OSError:
                close_ok = False
            self._final = s if (ok_out and ok_rec and close_ok) else 4
            return self._final


def _diagnostic(code: str, problem: str, fields: Mapping[str, Any]) -> Record:
    if not isinstance(code, str) or not CODE.match(code):
        raise ValueError(f"code {code!r} is not two or more dot-separated lowercase segments (spec section 6)")
    if not isinstance(problem, str) or not problem:
        raise ValueError("problem is never empty (spec section 6)")
    out: Record = {"code": code, "problem": problem}
    for k in ("remedy", "remedy_target", "measured", "limit", "retryable", "detail"):
        if fields.get(k) is not None:
            out[k] = fields[k]
    unknown = set(fields) - {"remedy", "remedy_target", "measured", "limit", "retryable", "detail"}
    if unknown:
        raise ValueError(f"a diagnostic does not carry {', '.join(sorted(unknown))}; put tool-specific fields under detail")
    return out


# ---- a tool --------------------------------------------------------------------------------


class Tool:
    """A tool's declaration: its commands, retention, credential-source resolvers and renderer."""

    def __init__(self, name: str, version: str, commands: Mapping[str, Mapping[str, Any]], retention: Mapping[str, int],
                 sources: Optional[Mapping[str, Callable[[], bool]]] = None, human: Optional[Callable[[Record], Optional[str]]] = None):
        self.name, self.version, self.commands, self.retention = name, version, dict(commands), dict(retention)
        self.sources, self.human = dict(sources or {}), human


def define_tool(*, name: str, version: str, commands: Mapping[str, Mapping[str, Any]], retention: Mapping[str, int],
                sources: Optional[Mapping[str, Callable[[], bool]]] = None,
                human: Optional[Callable[[Record], Optional[str]]] = None) -> Tool:
    """Check a tool's declaration for what the writer needs and return it.

    `commands` maps a command name to `{intent, effects: {reads, writes, network, idempotent},
    secrets?, emits: [{id, version, schema?}], errors?}`. `retention` is `{count}`: completed
    bundles of this tool beyond that count are deleted, oldest first (spec section 5.1).
    `sources` maps a declared logical credential source to a resolver returning whether a
    credential from it is present. `human` renders a line as prose for `--human`, or returns None
    for the default rendering."""
    if not name:
        raise ValueError("tool name is never empty")
    if not version:
        raise ValueError("tool version is never empty")
    if not commands:
        raise ValueError("a tool has at least one command")
    count = retention.get("count") if isinstance(retention, Mapping) else None
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("retention count must be a positive integer (spec section 5.1)")
    for cname, c in commands.items():
        if not cname or cname.startswith("-"):
            raise ValueError(f"command name {cname!r} is not a positional name")
        if not c.get("intent"):
            raise ValueError(f"command {cname} needs an intent")
        eff = c.get("effects")
        if not isinstance(eff, Mapping) or not all(k in eff for k in ("reads", "writes", "network", "idempotent")):
            raise ValueError(f"command {cname} needs effects with reads, writes, network and idempotent (spec section 4.3)")
        for e in list(c.get("emits", [])) + list(c.get("errors", [])):
            if not e.get("id") or not _SEMVER.match(str(e.get("version", ""))):
                raise ValueError(f"command {cname} emits an invalid type {e.get('id')}@{e.get('version')}")
    return Tool(name, version, commands, retention, sources, human)


def _schema_ref(t: Mapping[str, Any]) -> Dict[str, str]:
    return {"id": t["id"], "version": t["version"]}


def main(tool: Tool, argv: Sequence[str], handler: Callable[[Run, List[str]], Any], *,
         cwd: Optional[str] = None, env: Optional[Mapping[str, str]] = None, home: Optional[str] = None,
         stdout: Any = None, stderr: Any = None, session: Optional[str] = None, now: Optional[Callable[[], int]] = None,
         inputs: Optional[Callable[[List[str], str], List[Record]]] = None,
         resolved: Optional[Callable[[List[str], str], Record]] = None) -> int:
    """Run a tool: parse the writer-owned flags, bootstrap, write the receipt, run the handler under
    the top-level handler of spec section 6, and close with `end`. Returns the exit status
    (spec section 3.4). Nothing raised inside escapes as a traceback.

    `argv` is `[tool.name, *sys.argv[1:]]`. `inputs(args, command)` returns the declared inputs as
    `{path, role?, exclude?}`; `resolved(args, command)` returns the interpretation after defaults,
    which enters `inv` and so must be order-normalised and free of volatile values."""
    env = dict(os.environ if env is None else env)
    out_sink = stdout if stdout is not None else FdSink(1)
    err_sink = stderr if stderr is not None else FdSink(2)
    clock = now or _now_ms
    state: Dict[str, Any] = {"run": None, "capture": None, "location": None}
    try:
        return _main(tool, list(argv), handler, cwd, env, home, out_sink, err_sink, session, clock, inputs, resolved, state)
    except BaseException as e:  # the top-level handler: nothing escapes as plain text (spec 6)
        capture = state["capture"]
        run: Optional[Run] = state["run"]
        try:
            if run is not None and not run.ended:
                # A run that reached the bootstrap line closes with `end` whatever happens (spec
                # section 3.3). The line is writer-built, so no declared secret can have it
                # withheld (flyingrobots/parley#161). When the failure was in reporting the
                # tool's own failure, or this line cannot be written either, the run failed and
                # the error that says why could not be written: that is protocol output that
                # could not be written, status 4, not the 2 of a failure that was reported
                # (spec section 3.4).
                unreported = bool(state.get("reporting"))
                try:
                    run.writer_error("uncaught.writer_failure", f"the writer itself failed: {_describe(e)}", receipt_extra={"detail": {"traceback": traceback.format_exc()}}, remedy="this is a defect in parley_emit; report it with the receipt")
                except BaseException:
                    unreported = True
                try:
                    return run.end(4 if unreported else None)
                except BaseException:
                    return 4
            if run is not None:
                return 4
            location = state["location"]
            if location is not None:  # reserved but never announced: a startup failure has no receipt (3.2)
                try:
                    os.close(location.fd)
                except OSError:
                    pass
                _unlink_safe(location.receipt_path)
            line = {"event": "startup.failed", "t": max(0, int(clock())), "seq": 0, "run": ulid(), "tool": tool.name or "unknown", "v": tool.version or "unknown",
                    "code": "startup.writer_failed", "problem": f"the writer failed before the bootstrap line: {type(e).__name__}", "remedy": "this is a defect in parley_emit or in the tool's declaration; report it", "_schema": SCHEMA_IDS["startup_failed"]}
            err_sink.write(_dumps(line) + "\n")
            return 3
        except BaseException:
            return 4 if run is not None else 3
        finally:
            if capture is not None:
                capture.release()


def _describe(e: BaseException) -> str:
    """An exception in a few words, for the writer's own failure line. Never raises: an exception
    that cannot be described is said to be that."""
    try:
        return f"{type(e).__name__}: {str(e) or '(no message)'}"
    except BaseException:
        return f"{type(e).__name__}: (it could not be described)"


def _report_uncaught(run: "Run", state: Dict[str, Any], code: str, problem: Callable[[], str], remedy: str, receipt_extra: Optional[Record] = None) -> None:
    """The tool's failure as the writer's own error line (spec section 6): writer-built, so no
    declared secret can rename its fields or have it withheld, while the exception's name, message
    and traceback are scrubbed like any other text of the tool's (flyingrobots/parley#161).
    `problem` is built here, inside the marked region, because describing an exception can itself
    raise; `main` reads the mark to tell a failure that went unreported."""
    state["reporting"] = True
    run.writer_error(code, problem(), receipt_extra=receipt_extra, remedy=remedy)
    state["reporting"] = False


def _main(tool: Tool, argv: List[str], handler: Callable[[Run, List[str]], Any], cwd_opt: Optional[str], env: Dict[str, str],
          home: Optional[str], stdout: Any, stderr: Any, session_opt: Optional[str], now: Callable[[], int],
          inputs_fn: Optional[Callable[[List[str], str], List[Record]]], resolved_fn: Optional[Callable[[List[str], str], Record]],
          state: Dict[str, Any]) -> int:
    cwd = os.path.abspath(cwd_opt if cwd_opt is not None else os.getcwd())
    raw_args = argv[1:]
    # `--` ends the writer's flags (flyingrobots/parley#103): the writer's own flags are recognised
    # anywhere before the first `--`, that `--` is removed, and every argument after it is the
    # tool's, untouched, a writer flag's text or a second `--` included.
    dash = raw_args.index("--") if "--" in raw_args else -1
    own = raw_args if dash == -1 else raw_args[:dash]
    after = [] if dash == -1 else raw_args[dash + 1:]
    human = any(a in ("--human", "--humanize") for a in own)
    dry_run = "--dry-run" in own
    discovery = "schema" if "--schema" in own else ("help" if ("--help" in own or "-h" in own) else None)
    args = [a for a in own if a not in _OWN_FLAGS]
    names = list(tool.commands)
    # The command is chosen by position (flyingrobots/parley#101): once the writer's flags are set
    # aside, the first remaining argument before any `--` is the command, and only that one argument
    # is removed. A tool with one command may omit it. A later argument with a command's text is the
    # tool's, and nothing after `--` is ever the command.
    command_name: Optional[str] = None
    rest = args + after
    if args and args[0] in tool.commands:
        command_name, rest = args[0], args[1:] + after
    elif len(names) == 1:
        command_name = names[0]
    command = tool.commands.get(command_name) if command_name else None

    # The declared secrets of every command: a value passed to the wrong command is still a secret.
    all_names = classify_secrets(s for n in names for s in tool.commands[n].get("secrets", []))
    secret_values = collect_secret_values(argv, all_names, env)
    own_names = classify_secrets(command.get("secrets", []) if command else [])

    run_id = ulid(now())
    for _ in range(16):
        if not carries_secret(run_id, secret_values):
            break
        run_id = ulid(now())

    def startup_failed(code: str, problem: str, remedy: str) -> int:
        line = {"event": "startup.failed", "t": max(0, int(now())), "seq": 0, "run": run_id, "tool": tool.name, "v": tool.version,
                "code": code, "problem": replace_secrets(problem, secret_values), "remedy": remedy, "_schema": SCHEMA_IDS["startup_failed"]}
        try:
            stderr.write(f"startup failed {code}: {line['problem']} ({remedy})\n" if human else _dumps(line) + "\n")
        except Exception:
            pass  # nothing else can be said
        return 3

    if carries_secret(run_id, secret_values):
        return startup_failed("startup.secret_in_path", "no run id free of a declared secret value could be chosen", "do not pass a value this short as a declared secret")
    session_raw = session_opt if session_opt is not None else env.get("PARLEY_SESSION")
    if session_raw and carries_secret(session_raw, secret_values):
        return startup_failed("startup.secret_in_identity", "the session id contains a declared secret value and cannot be printed", "supply a session id that does not contain the secret")
    if not command_name and discovery is None:
        return startup_failed("startup.unknown_command", f"no command named; commands are {', '.join(names)}", f"name one of: {', '.join(names)}")

    # Capture starts here, before any tool code runs; text captured before the receipt exists is held.
    capture = _Capture()
    state["capture"] = capture

    def fail(code: str, problem: str, remedy: str) -> int:
        capture.release()
        return startup_failed(code, problem, remedy)

    # Declared credential sources, resolved before the head (spec 5.3); a raising resolver means "not present".
    present_sources: List[str] = []
    for s in own_names["sources"]:
        try:
            fn = tool.sources.get(s)
            if fn is not None and fn():
                present_sources.append(s)
        except Exception:
            pass
    present_env = [n for n in all_names["env"] if n in env]

    location = _choose_location(cwd, run_id, env, home, secret_values)
    if not isinstance(location, _Location):
        return fail(location["code"], location["problem"], location["remedy"])
    state["location"] = location

    try:
        if discovery:
            resolved_raw: Any = {"discovery": discovery, "command": command_name}
        else:
            resolved_raw = resolved_fn(rest, command_name) if resolved_fn else {"command": command_name, "args": rest}
        decls = [] if (discovery or not command) else list(inputs_fn(rest, command_name) if inputs_fn else [])
        _dumps(resolved_raw)
    except Exception as e:
        try:
            os.close(location.fd)
            os.unlink(location.receipt_path)
        except OSError:
            pass
        return fail("startup.arguments_invalid", f"the arguments could not be interpreted: {str(e) or type(e).__name__}", "fix the arguments; see the command's --help")

    session = session_raw or None
    resolved_pointers: List[str] = []
    resolved_v = scrub(resolved_raw, secret_values, "", resolved_pointers)
    argv_redacted, argv_indexes = redact_argv(argv, secret_values, all_names["flags"])
    input_pointers: List[str] = []
    # `path` and `role` are the writer's field names here and are never renamed; their values are
    # the tool's and are scrubbed.
    descriptors = scrub([{"path": d["path"], **({"role": d["role"]} if d.get("role") else {})} for d in decls], secret_values, "", input_pointers, rename_keys=False)
    input_indexes = sorted({int(p.split("/")[1]) for p in input_pointers})
    redacted: Record = {}
    if argv_indexes:
        redacted["argv"] = argv_indexes
    if resolved_pointers:
        redacted["resolved"] = resolved_pointers
    if input_indexes:
        redacted["inputs"] = input_indexes
    # The head writes `redacted` as built here (Run._head), so the two lists of names are scrubbed
    # here, as the head's scrub used to scrub them; the indexes and pointers above need none.
    if present_env:
        redacted["env"] = scrub(present_env, secret_values)
    if present_sources:
        redacted["sources"] = scrub(present_sources, secret_values)
    head_redacted = bool(redacted)
    inv = compute_inv(tool.name, tool.version, command_name, resolved_v, []) if (not decls and command) else None

    run = Run(tool=tool.name, v=tool.version, id=run_id, session=session, dry_run=dry_run, stdout=stdout, stderr=stderr,
              receipt_fd=location.fd, receipt_path=location.receipt_path, receipt_dir=location.receipt_dir,
              secret_values=secret_values, now=now, cwd=cwd, command=command_name or discovery or "", resolved=resolved_v,
              inputs=decls, head_redacted=head_redacted, human=(tool.human or (lambda _l: None)) if human else None,
              schemas=_declared_schemas(tool))
    state["run"] = run

    run._bootstrap(inv)
    bookkeeping = bookkeeping_for(cwd, env, home)
    effects = {**command["effects"], "bookkeeping": bookkeeping} if command else {"reads": [], "writes": [], "network": False, "idempotent": True, "bookkeeping": bookkeeping}
    head: Record = {"tool": tool.name, "v": tool.version}
    if inv:
        head["inv"] = inv
    if session:
        head["session"] = session
    head.update({"argv": argv_redacted, "resolved": resolved_v})
    if head_redacted:
        head["redacted"] = redacted
    head.update({"inputs": descriptors, "effects": effects})
    if dry_run:
        head["dry_run"] = True
    run._head(head)
    run._flush_deferred()
    capture.attach(run)
    if run.sink_failed:
        capture.release()
        return run.end()
    if location.warning:
        w = location.warning
        run.writer_warning(w["code"], w["problem"], remedy=w["remedy"])

    _retain(run, tool.name, location.receipt_dir, tool.retention["count"], dry_run, int(now()))

    if discovery:
        try:
            _discover(run, tool, discovery, command_name, bookkeeping)
        except (ParleyClosed, ParleyRedactionConflict):
            pass  # a conflict was already reported by the writer; the run closes with 4
        except Exception as e:
            if not run.ended:
                _report_uncaught(run, state, "uncaught.exception", lambda: f"uncaught {type(e).__name__} during discovery: {str(e) or '(no message)'}",
                                 f"this is a defect in the tool's declaration; report it with the receipt at {run.receipt_path}",
                                 {"detail": {"traceback": traceback.format_exc()}})
        capture.release()
        return (run.status if run.status is not None else 4) if run.ended else run.end()

    try:
        handler(run, rest)
    except SystemExit as e:
        code = e.code
        if run.ended:
            return run.status if run.status is not None else 4
        if code not in (None, 0):
            _report_uncaught(run, state, "uncaught.exit", lambda: f"the tool called sys.exit({code!r}) inside its handler instead of returning or calling run.end",
                             "end the run with run.end(status) and return; the writer owns the exit status (spec section 3.4)")
    except ParleyRedactionConflict:
        # Already reported by the writer, under its own code and without the value (spec section
        # 5.3, flyingrobots/parley#131); an uncaught.exception beside it would say the same thing
        # twice. The run closes with 4.
        if run.ended:
            return run.status if run.status is not None else 4
    except BaseException as e:  # KeyboardInterrupt included: it still closes a complete failed receipt
        if run.ended:
            capture.release()
            return 4
        _report_uncaught(run, state, "uncaught.exception", lambda: f"uncaught {type(e).__name__}: {str(e) or '(no message)'}",
                         f"this is a defect in the tool; report it with the receipt at {run.receipt_path}",
                         {"detail": {"traceback": traceback.format_exc()}})
    finally:
        capture.release()
    return (run.status if run.status is not None else 4) if run.ended else run.end()


def _declared_schemas(tool: Tool) -> Dict[Tuple[str, str], Any]:
    """Every schema document this writer can validate a record against, by `(id, version)`: the
    embedded ones and those the tool declared on its emitted and error types (spec section 4.2).
    A pair outside this map cannot be checked."""
    out: Dict[Tuple[str, str], Any] = {(s["id"], s["version"]): s["schema"] for s in SCHEMAS}
    for c in tool.commands.values():
        for t in list(c.get("emits", [])) + list(c.get("errors") or []):
            if t.get("schema") is not None:
                out[(t["id"], t["version"])] = t["schema"]
    return out


def _discover(run: Run, tool: Tool, discovery: str, command_name: Optional[str], bookkeeping: List[Record]) -> None:
    names = list(tool.commands)
    which = [command_name] if (discovery == "help" and command_name) else names
    types: Dict[Tuple[str, str], Mapping[str, Any]] = {}

    def add(t: Mapping[str, Any]) -> None:
        types.setdefault((t["id"], t["version"]), t)

    for name in which:
        c = tool.commands[name]
        errors = list(c.get("errors") or DEFAULT_ERRORS)
        run._describe({"event": "command", "name": name, "intent": c["intent"], "effects": {**c["effects"], "bookkeeping": bookkeeping},
                       "secrets": list(c.get("secrets", [])), "emits": [_schema_ref(t) for t in list(c["emits"]) + errors]}, SCHEMA_IDS["command"])
    for name in which:
        c = tool.commands[name]
        for t in c["emits"]:
            add(t)
        for t in (c.get("errors") or DEFAULT_ERRORS):
            add(t)
    if discovery == "schema":
        for t in WRITER_SCHEMAS:
            add(t)
    for (sid, ver), t in types.items():
        doc = t.get("schema") or schema_for((sid, ver))
        if doc is None:
            # The writer's own warning, so writer-built: its code and field names are not scrubbed.
            run.writer_warning("schema.unavailable", f"no schema document for {sid}@{ver}", remedy="declare the schema on the emitted type")
            continue
        run._describe({"event": "schema", "id": sid, "version": ver, "schema": doc}, SCHEMA_IDS["schema"], verbatim="schema")
    run.end(0)


# ---- retention (spec section 5.1), per tool ------------------------------------------------
# A tool's count covers only bundles whose receipt head names that tool (flyingrobots/parley#75):
# another tool's receipts and a reader's are never counted and never deleted by it.


def _first_line(path: str) -> Optional[Record]:
    try:
        with open(path, "rb") as f:
            line = f.readline()
        if not line.endswith(b"\n"):
            return None
        obj = json.loads(line.decode("utf-8"))
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError):
        return None


def _has_ended(path: str) -> bool:
    """True when the receipt's final line is a newline-terminated `end` (spec section 5.4)."""
    try:
        size = os.path.getsize(path)
        if size == 0:
            return False
        with open(path, "rb") as f:
            n = min(size, 8192)
            f.seek(size - n)
            tail = f.read(n)
        if not tail.endswith(b"\n"):
            return False
        last = tail[:-1].split(b"\n")[-1]
        obj = json.loads(last.decode("utf-8"))
        return isinstance(obj, dict) and obj.get("event") == "end"
    except (OSError, ValueError):
        return False


def _retain(run: Run, tool_name: str, receipt_dir: str, count: int, dry_run: bool, at: int) -> None:
    mine: List[Tuple[float, str]] = []
    try:
        for name in os.listdir(receipt_dir):
            if not name.endswith(".jsonl"):
                continue
            p = os.path.join(receipt_dir, name)
            head = _first_line(p)
            if head is None or head.get("event") != "receipt.head" or head.get("tool") != tool_name:
                continue
            mine.append((os.stat(p).st_mtime * 1000, name))
    except OSError:
        return
    excess = len(mine) - count
    if excess <= 0:
        return
    candidates = sorted((m for m in mine if m[1] != f"{run.id}.jsonl"), key=lambda m: (m[0], m[1]))
    # The scan orders the candidates; each decision re-observes its receipt, because another run
    # can append between the scan and here (flyingrobots/parley#112). The observation is kept and
    # compared again just before the unlink.
    victims: List[Tuple[str, Tuple[int, int]]] = []
    for _, name in candidates:
        if len(victims) >= excess:
            break
        p = os.path.join(receipt_dir, name)
        seen = _observe(p)
        if seen is None:
            continue
        if _has_ended(p) or at - seen[1] / 1e6 > _INCOMPLETE_GRACE_MS:
            victims.append((name, seen))
    total = len(mine)
    if not victims:
        run.writer_step("retention: nothing to delete", f"{total} receipts of {tool_name} exceed its retention count of {count}, but every excess receipt is still in flight (no end line yet); only completed bundles, or incomplete ones older than a day, are deleted (spec section 5.1)")
        return
    if dry_run:
        run.writer_step(f"retention: would delete {len(victims)} receipt bundle(s)", f"{total} receipts of {tool_name} exceed its retention count of {count}; a dry run performs no retention deletion (spec section 4.3)", {"receipts": [n for n, _ in victims]})
        return
    deleted: List[str] = []
    for name, seen in victims:
        p = os.path.join(receipt_dir, name)
        if _observe(p) != seen:
            continue  # it moved since the decision: its run may be alive (flyingrobots/parley#112)
        # One bundle (spec section 5): the sidecars go only once the receipt is gone, so a
        # receipt that cannot be unlinked keeps its records (flyingrobots/parley#113).
        try:
            os.unlink(p)
            ours = True
        except FileNotFoundError:
            ours = False  # another run deleted it first; its sidecars still go
        except OSError:
            continue
        try:
            _rmtree(os.path.join(receipt_dir, name[: -len(".jsonl")]))
        except OSError:
            continue  # a bundle another run is deleting
        if ours:
            deleted.append(name)
    run.writer_step(f"retention: deleted {len(deleted)} receipt bundle(s)", f"{total} receipts of {tool_name} exceeded its retention count of {count}; the oldest completed bundles of this tool are deleted with their sidecars, and no other tool's receipts are counted or touched (spec section 5.1)", {"receipts": deleted})


def _observe(p: str) -> Optional[Tuple[int, int]]:
    """A receipt's size and mtime in nanoseconds, or None when it is gone."""
    try:
        st = os.stat(p)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _rmtree(p: str) -> None:
    if not os.path.isdir(p) or os.path.islink(p):
        return
    for name in os.listdir(p):
        q = os.path.join(p, name)
        if os.path.isdir(q) and not os.path.islink(q):
            _rmtree(q)
        else:
            _unlink_safe(q)
    os.rmdir(p)


# ---- vendoring ------------------------------------------------------------------------------

VENDOR_SCHEMA = {"id": "parley.tooling.vendor_info", "version": "1.0.0"}


def vendor_info(path: Optional[str] = None) -> Record:
    """What a consumer pins a vendored copy by: the SHA-256 of this file's bytes."""
    p = os.path.abspath(path or __file__)
    with open(p, "rb") as f:
        data = f.read()
    digest = sha256(data)
    return {"event": "vendor.info", "file": p, "bytes": len(data), "sha256": digest, "version": __version__, "spec": SPEC_VERSION,
            "schemas": {"commit": SCHEMA_SOURCE["commit"], "files": len(SCHEMA_SOURCE["files"])},
            "verify": f"echo '{digest}  {os.path.basename(p)}' | shasum -a 256 -c -", "_schema": VENDOR_SCHEMA}


def _cli(argv: Sequence[str]) -> int:
    """`python3 parley_emit.py --vendor-info [--human]`. This is the file's own tooling, not a
    parley run: it emits JSON Lines stamped `parley.tooling.vendor_info` and makes no protocol
    claim."""
    prose = "--human" in argv or "--humanize" in argv
    args = [a for a in argv if a not in ("--human", "--humanize")]
    out = sys.stdout
    if args == ["--vendor-info"]:
        info = vendor_info()
        out.write((f"{info['sha256']}  {info['file']}  (parley_emit {info['version']}, spec {info['spec']}, schemas at {info['schemas']['commit'][:12]})\n") if prose else _dumps(info) + "\n")
        return 0
    if args in (["--help"], ["-h"]):
        line = {"event": "vendor.help", "usage": "python3 parley_emit.py --vendor-info [--human]",
                "intent": "Print this file's SHA-256 so a tool that vendors it can pin its copy", "_schema": VENDOR_SCHEMA}
        out.write((line["usage"] + "\n  " + line["intent"] + "\n") if prose else _dumps(line) + "\n")
        return 0
    line = {"event": "vendor.error", "code": "vendor.usage", "problem": f"unrecognised arguments: {' '.join(args) or '(none)'}",
            "remedy": "run python3 parley_emit.py --vendor-info", "_schema": VENDOR_SCHEMA}
    sys.stderr.write((f"vendor.usage: {line['problem']} ({line['remedy']})\n") if prose else _dumps(line) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
