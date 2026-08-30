"""Tests for deployed AgentCore Memory smoke validation."""

import json
from pathlib import Path

from praxis.agent.memory import MemoryRecord
from praxis.agent.memory_smoke import SMOKE_RECORDS, run_memory_smoke, write_evidence


class FakeMemoryStore:
    """In-memory adapter that exposes smoke-check reads and writes."""

    def __init__(self, records: tuple[MemoryRecord, ...] = ()) -> None:
        self.records = records
        self.write_count = 0

    def list_actor_records(self, _actor_id: str) -> tuple[MemoryRecord, ...]:
        return self.records

    def remember(
        self,
        _actor_id: str,
        _session_id: str,
        records: tuple[MemoryRecord, ...],
        *,
        operation_id: str,
        timestamp: object,
    ) -> tuple[str, ...]:
        assert operation_id.startswith("praxis_memory_smoke_")
        assert timestamp is not None
        self.records += records
        self.write_count += len(records)
        return tuple(f"record-{index}" for index, _ in enumerate(records))

    def recall(self, _actor_id: str, _query: str) -> tuple[MemoryRecord, ...]:
        return self.records


def test_memory_smoke_creates_missing_records_and_verifies_boundary() -> None:
    store = FakeMemoryStore()

    result = run_memory_smoke(store)  # type: ignore[arg-type]

    assert store.write_count == 2
    assert result.created_count == 2
    assert result.catalog_identifiers_rejected is True
    assert result.retrieved_kinds == ("decision", "preference")


def test_memory_smoke_preflight_makes_repeated_run_read_only() -> None:
    store = FakeMemoryStore(SMOKE_RECORDS)

    result = run_memory_smoke(store)  # type: ignore[arg-type]

    assert store.write_count == 0
    assert result.idempotent_preflight is True


def test_memory_smoke_evidence_omits_content_and_identifiers(tmp_path: Path) -> None:
    result = run_memory_smoke(FakeMemoryStore(SMOKE_RECORDS))  # type: ignore[arg-type]

    capture = json.loads(write_evidence(result, tmp_path).read_text())

    assert capture == {
        "actor_scoped": True,
        "catalog_identifiers_rejected": True,
        "created_count": 0,
        "idempotent_preflight": True,
        "retrieved_count": 2,
        "retrieved_kinds": ["decision", "preference"],
    }
