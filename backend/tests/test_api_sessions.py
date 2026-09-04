"""Tests for short-lived server-authoritative recommendation sessions."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from botocore.exceptions import ClientError

from praxis.api.runtime import CreateSessionData, SessionCandidate
from praxis.api.sessions import (
    SESSION_TTL_SECONDS,
    ApiSessionError,
    FailedSession,
    PendingSession,
    SessionStatus,
    SessionStore,
    StoredSession,
    load_session_table_name,
)
from praxis.domain import EvidenceCitation
from praxis.tools.contracts import BookEvidence

SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
ACTOR_ID = "51f4a405-8835-411d-9821-5980d73f51f6"
OTHER_ACTOR_ID = "7b9db85b-9448-4a41-9bb7-235a461429ae"
GOAL = "Learn compiler backends over a weekend"
NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)


class FakeTable:
    """Capture DynamoDB requests and return one configured session item."""

    def __init__(self, item: dict[str, object] | None = None) -> None:
        self.item = item
        self.put_request: dict[str, object] | None = None
        self.get_request: dict[str, object] | None = None
        self.update_request: dict[str, object] | None = None
        self.error: ClientError | None = None

    def put_item(self, **kwargs: object) -> dict[str, object]:
        if self.error is not None:
            raise self.error
        self.put_request = kwargs
        return {}

    def get_item(self, **kwargs: object) -> dict[str, object]:
        if self.error is not None:
            raise self.error
        self.get_request = kwargs
        return {} if self.item is None else {"Item": self.item}

    def update_item(self, **kwargs: object) -> dict[str, object]:
        if self.error is not None:
            raise self.error
        self.update_request = kwargs
        return {}


def session_data() -> CreateSessionData:
    """Return one complete recommendation session fixture."""
    return CreateSessionData(
        session_id=SESSION_ID,
        candidates=[
            SessionCandidate(
                candidate_id=f"candidate_{number}",
                title=f"Candidate {number}",
                summary="Build a focused compiler project.",
                rationale="The evidence provides implementation context.",
                estimated_scope="weekend",
                technologies=["Python"],
                first_milestone="Implement one instruction-selection rule.",
                evidence_citations=[
                    EvidenceCitation(
                        evidence_id="book:0f5ba253568e4836",
                        generated_connection="The evidence supports the project.",
                    )
                ],
            )
            for number in range(1, 4)
        ],
        evidence=[
            BookEvidence(
                evidence_id="book:0f5ba253568e4836",
                kind="book",
                title="Compiler Backend Development",
                author="Quentin Colombet",
                year=2025,
                category="Compilers",
                tags=[],
            )
        ],
    )


def test_starts_one_hour_session_without_overwrite() -> None:
    table = FakeTable()
    pending = SessionStore(table, now=lambda: NOW).start(SESSION_ID, ACTOR_ID, GOAL)

    assert pending == PendingSession(
        session_id=SESSION_ID,
        expires_at=int(NOW.timestamp()) + SESSION_TTL_SECONDS,
        goal=GOAL,
        actor_id=ACTOR_ID,
    )
    assert table.put_request == {
        "Item": pending.model_dump(mode="python"),
        "ConditionExpression": "attribute_not_exists(session_id)",
    }


def test_completes_only_a_pending_session() -> None:
    table = FakeTable()
    stored = SessionStore(table, now=lambda: NOW).complete(session_data(), ACTOR_ID, GOAL)

    assert stored.expires_at == int(NOW.timestamp()) + SESSION_TTL_SECONDS
    assert stored.status == SessionStatus.READY
    assert table.put_request == {
        "Item": stored.model_dump(mode="python"),
        "ConditionExpression": "#status = :pending AND actor_id = :actor_id",
        "ExpressionAttributeNames": {"#status": "status"},
        "ExpressionAttributeValues": {
            ":actor_id": ACTOR_ID,
            ":pending": SessionStatus.PENDING,
        },
    }


def test_marks_only_a_pending_session_failed() -> None:
    table = FakeTable()

    SessionStore(table, now=lambda: NOW).fail(SESSION_ID, ACTOR_ID)

    assert table.update_request == {
        "Key": {"session_id": SESSION_ID},
        "ConditionExpression": "#status = :pending AND actor_id = :actor_id",
        "UpdateExpression": "SET #status = :failed",
        "ExpressionAttributeNames": {"#status": "status"},
        "ExpressionAttributeValues": {
            ":actor_id": ACTOR_ID,
            ":failed": SessionStatus.FAILED,
            ":pending": SessionStatus.PENDING,
        },
    }


def test_loads_unexpired_session_and_resolves_selected_evidence() -> None:
    stored = StoredSession(
        **session_data().model_dump(mode="python"),
        expires_at=int((NOW + timedelta(minutes=5)).timestamp()),
        goal=GOAL,
        actor_id=ACTOR_ID,
    )
    table_item = stored.model_dump(mode="python")
    table_item["expires_at"] = Decimal(stored.expires_at)
    evidence = cast("list[dict[str, object]]", table_item["evidence"])
    evidence[0]["year"] = Decimal(2025)
    table = FakeTable(table_item)

    result = SessionStore(table, now=lambda: NOW).get(SESSION_ID, ACTOR_ID)

    assert result == stored
    assert table.get_request == {"Key": {"session_id": SESSION_ID}, "ConsistentRead": True}
    assert result is not None
    selected = result.selected_candidate("candidate_2")
    assert selected is not None
    assert selected.title == "Candidate 2"
    assert result.evidence_for(selected) == session_data().evidence


def test_treats_expired_or_missing_session_as_absent() -> None:
    expired = StoredSession(
        **session_data().model_dump(mode="python"),
        expires_at=int(NOW.timestamp()),
        goal=GOAL,
        actor_id=ACTOR_ID,
    )

    assert SessionStore(FakeTable(), now=lambda: NOW).get(SESSION_ID, ACTOR_ID) is None
    assert (
        SessionStore(FakeTable(expired.model_dump(mode="python")), now=lambda: NOW).get(
            SESSION_ID, ACTOR_ID
        )
        is None
    )


@pytest.mark.parametrize(
    "record",
    [
        PendingSession(
            session_id=SESSION_ID,
            expires_at=int((NOW + timedelta(minutes=5)).timestamp()),
            goal=GOAL,
            actor_id=ACTOR_ID,
        ),
        FailedSession(
            session_id=SESSION_ID,
            expires_at=int((NOW + timedelta(minutes=5)).timestamp()),
            goal=GOAL,
            actor_id=ACTOR_ID,
        ),
    ],
)
def test_loads_non_ready_session_state_without_exposing_candidates(
    record: PendingSession | FailedSession,
) -> None:
    store = SessionStore(FakeTable(record.model_dump(mode="python")), now=lambda: NOW)

    assert store.get_record(SESSION_ID, ACTOR_ID) == record
    assert store.get(SESSION_ID, ACTOR_ID) is None


def test_treats_another_actors_session_as_absent() -> None:
    stored = StoredSession(
        **session_data().model_dump(mode="python"),
        expires_at=int((NOW + timedelta(minutes=5)).timestamp()),
        goal=GOAL,
        actor_id=ACTOR_ID,
    )
    store = SessionStore(FakeTable(stored.model_dump(mode="python")), now=lambda: NOW)

    assert store.get_record(SESSION_ID, OTHER_ACTOR_ID) is None
    assert store.get(SESSION_ID, OTHER_ACTOR_ID) is None


def test_normalizes_dynamodb_failures() -> None:
    table = FakeTable()
    table.error = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "sensitive detail"}},
        "GetItem",
    )

    with pytest.raises(ApiSessionError, match="could not be loaded") as captured:
        SessionStore(table, now=lambda: NOW).get(SESSION_ID, ACTOR_ID)

    assert "sensitive detail" not in str(captured.value)


def test_requires_session_table_configuration() -> None:
    assert load_session_table_name({"PRAXIS_SESSION_TABLE_NAME": "praxis-dev-sessions"}) == (
        "praxis-dev-sessions"
    )
    with pytest.raises(ApiSessionError, match="invalid recommendation session configuration"):
        load_session_table_name({})
