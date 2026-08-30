"""Tests for the typed AgentCore Memory boundary."""

from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic import ValidationError

from praxis.agent.memory import (
    AgentCoreMemoryStore,
    MemoryError,
    MemoryRecord,
    actor_namespace,
    memory_prompt_context,
    record_namespace,
)
from praxis.config import MemorySettings


class FakeMemoryClient:
    """Capture AgentCore Memory requests and return configured records."""

    def __init__(self) -> None:
        self.create_request: dict[str, object] | None = None
        self.list_response: dict[str, object] = {"memoryRecordSummaries": []}
        self.retrieve_response: dict[str, object] = {"memoryRecordSummaries": []}

    def batch_create_memory_records(self, **kwargs: object) -> dict[str, object]:
        self.create_request = kwargs
        records = cast("list[object]", kwargs["records"])
        return {
            "successfulRecords": [
                {"memoryRecordId": f"record-{index}", "status": "SUCCEEDED"}
                for index, _ in enumerate(records, start=1)
            ],
            "failedRecords": [],
        }

    def list_memory_records(self, **_kwargs: object) -> dict[str, object]:
        return self.list_response

    def retrieve_memory_records(self, **_kwargs: object) -> dict[str, object]:
        return self.retrieve_response


def settings() -> MemorySettings:
    return MemorySettings(memory_id="praxis_memory-abcdefghij", region="us-east-1")


def summary(record: MemoryRecord, actor_id: str = "user-123") -> dict[str, object]:
    return {
        "memoryRecordId": "record-1",
        "content": {"text": record.model_dump_json()},
        "memoryStrategyId": "direct",
        "namespaces": [record_namespace(actor_id, record.kind)],
        "createdAt": datetime(2026, 8, 29, tzinfo=UTC),
    }


def test_memory_namespaces_are_actor_and_kind_scoped() -> None:
    assert actor_namespace("user-123") == "/actors/user-123/"
    assert record_namespace("user-123", "preference") == "/actors/user-123/preferences/"
    assert record_namespace("user-123", "decision") == "/actors/user-123/decisions/"


@pytest.mark.parametrize("actor_id", ["", " user", "user:other", "../user", "user?"])
def test_actor_namespace_rejects_unsafe_identifiers(actor_id: str) -> None:
    with pytest.raises(ValueError, match="actor_id has an invalid format"):
        actor_namespace(actor_id)


def test_memory_record_rejects_catalog_evidence_identifiers() -> None:
    with pytest.raises(ValidationError, match="catalog evidence identifiers"):
        MemoryRecord(
            kind="decision",
            text="Use book:0f5ba253568e4836 as the selected catalog evidence.",
        )


def test_remember_writes_only_typed_content_and_audit_metadata() -> None:
    client = FakeMemoryClient()
    store = AgentCoreMemoryStore(settings(), client)
    records = (
        MemoryRecord(kind="preference", text="Prefer weekend projects."),
        MemoryRecord(kind="decision", text="Selected a compiler learning project."),
    )
    timestamp = datetime(2026, 8, 29, 12, tzinfo=UTC)

    identifiers = store.remember(
        "user-123",
        "session-456",
        records,
        operation_id="request_123",
        timestamp=timestamp,
    )

    assert identifiers == ("record-1", "record-2")
    assert client.create_request is not None
    assert client.create_request["clientToken"] == "request_123"
    requests = cast("list[dict[str, object]]", client.create_request["records"])
    assert requests[0]["namespaces"] == ["/actors/user-123/preferences/"]
    assert requests[1]["namespaces"] == ["/actors/user-123/decisions/"]
    assert requests[0]["content"] == {
        "text": '{"kind":"preference","text":"Prefer weekend projects."}'
    }
    assert requests[0]["metadata"] == {
        "actor_id": {"stringValue": "user-123"},
        "kind": {"stringValue": "preference"},
        "operation_id": {"stringValue": "request_123"},
        "session_id": {"stringValue": "session-456"},
    }


def test_recall_returns_only_validated_typed_actor_records() -> None:
    client = FakeMemoryClient()
    record = MemoryRecord(kind="preference", text="Prefer TypeScript visualizations.")
    client.retrieve_response = {"memoryRecordSummaries": [summary(record)]}
    store = AgentCoreMemoryStore(settings(), client)

    assert store.recall("user-123", "visualization") == (record,)
    assert memory_prompt_context((record,)) == (
        '{"kind":"preference","text":"Prefer TypeScript visualizations."}',
    )


def test_recall_rejects_records_from_an_unexpected_namespace() -> None:
    client = FakeMemoryClient()
    record = MemoryRecord(kind="decision", text="Selected a compiler project.")
    invalid = summary(record)
    invalid["namespaces"] = ["/catalog/books/"]
    client.retrieve_response = {"memoryRecordSummaries": [invalid]}

    with pytest.raises(MemoryError, match="outside its typed namespace"):
        AgentCoreMemoryStore(settings(), client).recall("user-123", "compiler")


def test_remember_rejects_partial_batch_success() -> None:
    client = FakeMemoryClient()

    def failed_create(**_kwargs: object) -> dict[str, object]:
        return {
            "successfulRecords": [],
            "failedRecords": [{"memoryRecordId": "", "status": "FAILED"}],
        }

    client.batch_create_memory_records = failed_create  # type: ignore[method-assign]
    with pytest.raises(MemoryError, match="rejected"):
        AgentCoreMemoryStore(settings(), client).remember(
            "user-123",
            "session-456",
            [MemoryRecord(kind="preference", text="Prefer short projects.")],
            operation_id="request_123",
            timestamp=datetime.now(UTC),
        )


def test_remember_rejects_unsafe_operation_id() -> None:
    with pytest.raises(ValueError, match="operation_id has an invalid format"):
        AgentCoreMemoryStore(settings(), FakeMemoryClient()).remember(
            "user-123",
            "session-456",
            [MemoryRecord(kind="preference", text="Prefer short projects.")],
            operation_id="unsafe operation",
            timestamp=datetime.now(UTC),
        )
