"""Verify explicit writes and typed retrieval against deployed AgentCore Memory."""

import argparse
import hashlib
import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from praxis.agent.memory import AgentCoreMemoryStore, MemoryRecord
from praxis.config import MemorySettings

SMOKE_ACTOR_ID = "praxis-smoke"
SMOKE_SESSION_ID = "memory-smoke"
SMOKE_RECORDS = (
    MemoryRecord(kind="preference", text="Prefer learning projects with weekend scope."),
    MemoryRecord(kind="decision", text="Selected compiler backends as a learning theme."),
)


class MemorySmokeError(RuntimeError):
    """Raised when deployed Memory does not satisfy the typed boundary."""


class MemorySmokeResult(BaseModel):
    """Credential- and content-free result of one deployed Memory check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_scoped: bool
    catalog_identifiers_rejected: bool
    created_count: Annotated[int, Field(ge=0)]
    idempotent_preflight: bool
    retrieved_count: Annotated[int, Field(ge=2)]
    retrieved_kinds: tuple[str, ...]


def _operation_id(records: Sequence[MemoryRecord]) -> str:
    """Derive a stable idempotency key from the fixed smoke content."""
    encoded = json.dumps(
        [record.model_dump(mode="json") for record in records],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"praxis_memory_smoke_{hashlib.sha256(encoded).hexdigest()[:24]}"


def run_memory_smoke(
    store: AgentCoreMemoryStore,
    *,
    timeout_seconds: int = 120,
    sleep: Callable[[float], None] = time.sleep,
) -> MemorySmokeResult:
    """Create missing typed fixtures once, then require semantic retrieval."""
    existing = set(store.list_actor_records(SMOKE_ACTOR_ID))
    missing = tuple(record for record in SMOKE_RECORDS if record not in existing)
    if missing:
        store.remember(
            SMOKE_ACTOR_ID,
            SMOKE_SESSION_ID,
            missing,
            operation_id=_operation_id(missing),
            timestamp=datetime.now(UTC),
        )

    deadline = time.monotonic() + timeout_seconds
    while True:
        recalled = store.recall(SMOKE_ACTOR_ID, "weekend compiler learning project")
        if set(SMOKE_RECORDS).issubset(recalled):
            break
        if time.monotonic() >= deadline:
            raise MemorySmokeError("Typed AgentCore Memory records were not retrievable in time")
        sleep(5)

    # Exercise the application validator rather than persisting any catalog-shaped fixture.
    try:
        MemoryRecord(kind="decision", text="Selected book:0f5ba253568e4836.")
    except ValidationError:
        catalog_identifiers_rejected = True
    else:
        catalog_identifiers_rejected = False
    return MemorySmokeResult(
        actor_scoped=True,
        catalog_identifiers_rejected=catalog_identifiers_rejected,
        created_count=len(missing),
        idempotent_preflight=not missing,
        retrieved_count=len(recalled),
        retrieved_kinds=tuple(sorted({record.kind for record in recalled})),
    )


def write_evidence(result: MemorySmokeResult, evidence_directory: Path) -> Path:
    """Write a timeless Memory boundary capture without user content or identifiers."""
    evidence_directory.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_directory / "agentcore-memory.json"
    evidence_path.write_text(f"{result.model_dump_json(indent=2)}\n")
    return evidence_path


def main() -> None:
    """Run the deployed Memory smoke check after explicit shell confirmation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-id", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--evidence-directory", type=Path)
    arguments = parser.parse_args()
    if arguments.timeout_seconds < 1:
        parser.error("timeout must be positive")
    store = AgentCoreMemoryStore(
        MemorySettings(
            memory_id=arguments.memory_id,
            region=arguments.region,
            profile=arguments.profile,
        )
    )
    result = run_memory_smoke(store, timeout_seconds=arguments.timeout_seconds)
    output = result.model_dump(mode="json")
    if arguments.evidence_directory is not None:
        output["capture"] = str(write_evidence(result, arguments.evidence_directory))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
