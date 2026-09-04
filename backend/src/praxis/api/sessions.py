"""Short-lived server-authoritative recommendation session storage."""

import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from functools import cache
from typing import Annotated, Literal, Protocol, Self, cast

from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from praxis.api.requests import MAX_API_TEXT_CHARACTERS, ActorId
from praxis.api.runtime import CreateSessionData, SessionCandidate
from praxis.tools.contracts import Evidence

SESSION_TTL_SECONDS = 60 * 60


class ApiSessionError(RuntimeError):
    """Raised when recommendation session storage is unavailable or invalid."""


class ApiSessionNotFoundError(ApiSessionError):
    """Raised when a requested session candidate is absent or expired."""


class SessionTable(Protocol):
    """DynamoDB table methods used by the application session store."""

    def put_item(self, **kwargs: object) -> dict[str, object]: ...

    def get_item(self, **kwargs: object) -> dict[str, object]: ...

    def update_item(self, **kwargs: object) -> dict[str, object]: ...


class SessionStatus(StrEnum):
    """Public lifecycle states for one asynchronous recommendation session."""

    FAILED = "failed"
    PENDING = "pending"
    READY = "ready"


class SessionRecord(BaseModel):
    """Shared fields persisted for every short-lived session state."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=True,
    )

    session_id: Annotated[
        str,
        Field(
            alias="sessionId",
            pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        ),
    ]
    expires_at: int = Field(gt=0)
    goal: Annotated[str, Field(min_length=1, max_length=MAX_API_TEXT_CHARACTERS)]
    actor_id: ActorId


class PendingSession(SessionRecord):
    """A queued recommendation session without generated content."""

    status: Literal[SessionStatus.PENDING] = SessionStatus.PENDING


class FailedSession(SessionRecord):
    """A completed background attempt that exposed no failure details."""

    status: Literal[SessionStatus.FAILED] = SessionStatus.FAILED


class StoredSession(CreateSessionData):
    """A recommendation set retained only for the bounded selection workflow."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=True,
    )

    expires_at: int = Field(gt=0)
    goal: Annotated[str, Field(min_length=1, max_length=MAX_API_TEXT_CHARACTERS)]
    actor_id: ActorId
    status: Literal[SessionStatus.READY] = SessionStatus.READY

    @model_validator(mode="after")
    def require_candidate_ids(self) -> Self:
        """Require the complete deterministic candidate identifier set."""
        if {item.candidate_id for item in self.candidates} != {
            "candidate_1",
            "candidate_2",
            "candidate_3",
        }:
            raise ValueError("session candidate IDs are incomplete")
        return self

    def selected_candidate(self, candidate_id: str) -> SessionCandidate | None:
        """Return one session-owned candidate by its application identifier."""
        return next(
            (candidate for candidate in self.candidates if candidate.candidate_id == candidate_id),
            None,
        )

    def evidence_for(self, candidate: SessionCandidate) -> list[Evidence]:
        """Return only catalog facts cited by the selected candidate."""
        cited_ids = {citation.evidence_id for citation in candidate.evidence_citations}
        return [item for item in self.evidence if item.evidence_id in cited_ids]


type AnySession = PendingSession | FailedSession | StoredSession
_SESSION_ADAPTER: TypeAdapter[AnySession] = TypeAdapter(
    Annotated[AnySession, Field(discriminator="status")]
)


def _normalize_dynamodb_numbers(value: object) -> object:
    """Convert integral DynamoDB numbers before strict domain validation."""
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueError("stored session contains a fractional number")
        return int(value)
    if isinstance(value, list):
        return [_normalize_dynamodb_numbers(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        mapping = cast("dict[str, object]", value)
        return {key: _normalize_dynamodb_numbers(item) for key, item in mapping.items()}
    return value


class SessionStore:
    """Persist and resolve short-lived recommendation sessions in DynamoDB."""

    def __init__(
        self,
        table: SessionTable,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._table = table
        self._now = now or (lambda: datetime.now(UTC))

    def start(self, session_id: str, actor_id: str, goal: str) -> PendingSession:
        """Create one pending session without replacing an existing identifier."""
        pending = PendingSession(
            session_id=session_id,
            expires_at=int(self._now().timestamp()) + SESSION_TTL_SECONDS,
            goal=goal,
            actor_id=actor_id,
        )
        try:
            self._table.put_item(
                Item=pending.model_dump(mode="python"),
                ConditionExpression="attribute_not_exists(session_id)",
            )
        except (BotoCoreError, ClientError) as error:
            raise ApiSessionError("recommendation session could not be started") from error
        return pending

    def complete(self, session: CreateSessionData, actor_id: str, goal: str) -> StoredSession:
        """Replace one pending session with its validated recommendation set."""
        stored = StoredSession(
            session_id=session.session_id,
            candidates=session.candidates,
            evidence=session.evidence,
            expires_at=int(self._now().timestamp()) + SESSION_TTL_SECONDS,
            goal=goal,
            actor_id=actor_id,
        )
        try:
            self._table.put_item(
                Item=stored.model_dump(mode="python"),
                ConditionExpression="#status = :pending AND actor_id = :actor_id",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":actor_id": actor_id,
                    ":pending": SessionStatus.PENDING,
                },
            )
        except (BotoCoreError, ClientError) as error:
            raise ApiSessionError("recommendation session could not be completed") from error
        return stored

    def fail(self, session_id: str, actor_id: str) -> None:
        """Mark one pending session failed without retaining dependency details."""
        try:
            self._table.update_item(
                Key={"session_id": session_id},
                ConditionExpression="#status = :pending AND actor_id = :actor_id",
                UpdateExpression="SET #status = :failed",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":actor_id": actor_id,
                    ":failed": SessionStatus.FAILED,
                    ":pending": SessionStatus.PENDING,
                },
            )
        except (BotoCoreError, ClientError) as error:
            raise ApiSessionError("recommendation session could not be failed") from error

    def get_record(self, session_id: str, actor_id: str) -> AnySession | None:
        """Read one unexpired session state using a strongly consistent lookup."""
        try:
            response = self._table.get_item(
                Key={"session_id": session_id},
                ConsistentRead=True,
            )
            item = response.get("Item")
            if not isinstance(item, dict):
                return None
            stored = _SESSION_ADAPTER.validate_python(
                _normalize_dynamodb_numbers(cast("dict[str, object]", item))
            )
        except (BotoCoreError, ClientError, ValidationError) as error:
            raise ApiSessionError("recommendation session could not be loaded") from error
        if stored.actor_id != actor_id or stored.expires_at <= int(self._now().timestamp()):
            return None
        return stored

    def get(self, session_id: str, actor_id: str) -> StoredSession | None:
        """Return one ready session for candidate selection."""
        record = self.get_record(session_id, actor_id)
        return record if isinstance(record, StoredSession) else None


def load_session_table_name(environment: Mapping[str, str] | None = None) -> str:
    """Load the deployment-owned recommendation session table name."""
    source = os.environ if environment is None else environment
    table_name = source.get("PRAXIS_SESSION_TABLE_NAME", "").strip()
    if not table_name:
        raise ApiSessionError("invalid recommendation session configuration")
    return table_name


@cache
def create_session_store() -> SessionStore:
    """Create one reusable DynamoDB-backed session store for the API Lambda."""
    try:
        resource = Session().resource(  # pyright: ignore[reportUnknownMemberType]
            "dynamodb",
            config=Config(
                connect_timeout=2,
                read_timeout=2,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
        table = cast("SessionTable", resource.Table(load_session_table_name()))
        return SessionStore(table)
    except BotoCoreError as error:
        raise ApiSessionError("recommendation session client initialization failed") from error
