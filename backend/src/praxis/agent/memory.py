"""Typed AgentCore Memory access for user preferences and prior decisions."""

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Literal, Protocol, cast

from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from praxis.config import MemorySettings

MemoryKind = Literal["preference", "decision"]
ACTOR_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_/-]{0,254}$"
EVIDENCE_ID_PATTERN = re.compile(r"\b(?:book|byte|museum|project):[0-9a-f]{16}\b")
OPERATION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,76}$")


class MemoryError(RuntimeError):
    """Raised when AgentCore Memory violates the application contract."""


class MemoryRecord(BaseModel):
    """Application-owned content allowed to persist in AgentCore Memory."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    kind: MemoryKind
    text: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("text")
    @classmethod
    def reject_catalog_identifiers(cls, value: str) -> str:
        """Prevent stable catalog evidence identifiers from entering memory."""
        if EVIDENCE_ID_PATTERN.search(value):
            raise ValueError("catalog evidence identifiers cannot be stored in memory")
        return value


class MemoryClient(Protocol):
    """AgentCore data-plane methods used by the memory adapter."""

    def batch_create_memory_records(self, **kwargs: object) -> dict[str, object]: ...

    def list_memory_records(self, **kwargs: object) -> dict[str, object]: ...

    def retrieve_memory_records(self, **kwargs: object) -> dict[str, object]: ...


def actor_namespace(actor_id: str) -> str:
    """Return the actor-scoped namespace prefix shared by allowed record kinds."""
    if re.fullmatch(ACTOR_ID_PATTERN, actor_id) is None:
        raise ValueError("actor_id has an invalid format")
    return f"/actors/{actor_id}/"


def record_namespace(actor_id: str, kind: MemoryKind) -> str:
    """Return the exact namespace for one application-owned memory kind."""
    return f"{actor_namespace(actor_id)}{kind}s/"


def create_memory_client(settings: MemorySettings) -> MemoryClient:
    """Create a bounded AgentCore data-plane client for the configured identity."""
    session = Session(profile_name=settings.profile, region_name=settings.region)
    return cast(
        "MemoryClient",
        session.client(  # pyright: ignore[reportUnknownMemberType]
            "bedrock-agentcore",
            config=Config(
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        ),
    )


class AgentCoreMemoryStore:
    """Persist and retrieve only typed, actor-scoped application memory."""

    def __init__(self, settings: MemorySettings, client: MemoryClient | None = None) -> None:
        self.settings = settings
        self.client = client or create_memory_client(settings)

    def remember(
        self,
        actor_id: str,
        session_id: str,
        records: Sequence[MemoryRecord],
        *,
        operation_id: str,
        timestamp: datetime,
    ) -> tuple[str, ...]:
        """Write an explicitly approved, idempotently keyed record batch."""
        if not records:
            return ()
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        if OPERATION_ID_PATTERN.fullmatch(operation_id) is None:
            raise ValueError("operation_id has an invalid format")
        requests = [
            {
                "requestIdentifier": f"{operation_id}-{index}",
                "namespaces": [record_namespace(actor_id, record.kind)],
                "content": {"text": record.model_dump_json()},
                "timestamp": timestamp,
                "metadata": {
                    "actor_id": {"stringValue": actor_id},
                    "kind": {"stringValue": record.kind},
                    "operation_id": {"stringValue": operation_id},
                    "session_id": {"stringValue": session_id},
                },
            }
            for index, record in enumerate(records, start=1)
        ]
        try:
            response = self.client.batch_create_memory_records(
                memoryId=self.settings.memory_id,
                records=requests,
                clientToken=operation_id,
            )
        except (BotoCoreError, ClientError) as error:
            raise MemoryError("AgentCore Memory record creation failed") from error
        failed = response.get("failedRecords")
        if isinstance(failed, list) and failed:
            raise MemoryError("AgentCore Memory rejected one or more records")
        successful_value = response.get("successfulRecords")
        if not isinstance(successful_value, list):
            raise MemoryError("AgentCore Memory returned an invalid creation response")
        successful = cast("list[object]", successful_value)
        if len(successful) != len(records):
            raise MemoryError("AgentCore Memory returned an invalid creation response")
        identifiers: list[str] = []
        for item in successful:
            if not isinstance(item, dict):
                raise MemoryError("AgentCore Memory omitted a created record identifier")
            item_mapping = cast("dict[str, object]", item)
            record_id = item_mapping.get("memoryRecordId")
            if not isinstance(record_id, str):
                raise MemoryError("AgentCore Memory omitted a created record identifier")
            identifiers.append(record_id)
        return tuple(identifiers)

    def recall(self, actor_id: str, query: str) -> tuple[MemoryRecord, ...]:
        """Retrieve relevant actor memory without exposing service metadata."""
        if not query.strip():
            raise ValueError("memory query must not be empty")
        try:
            response = self.client.retrieve_memory_records(
                memoryId=self.settings.memory_id,
                namespacePath=actor_namespace(actor_id),
                searchCriteria={"searchQuery": query.strip(), "topK": self.settings.top_k},
                maxResults=self.settings.top_k,
            )
        except (BotoCoreError, ClientError) as error:
            raise MemoryError("AgentCore Memory retrieval failed") from error
        return _parse_records(response, actor_id)

    def list_actor_records(self, actor_id: str) -> tuple[MemoryRecord, ...]:
        """List actor memory for deterministic verification and duplicate checks."""
        try:
            response = self.client.list_memory_records(
                memoryId=self.settings.memory_id,
                namespacePath=actor_namespace(actor_id),
                maxResults=100,
            )
        except (BotoCoreError, ClientError) as error:
            raise MemoryError("AgentCore Memory listing failed") from error
        return _parse_records(response, actor_id)


def _parse_records(response: Mapping[str, object], actor_id: str) -> tuple[MemoryRecord, ...]:
    """Validate service records against content and namespace allowlists."""
    summaries = response.get("memoryRecordSummaries", [])
    if not isinstance(summaries, list):
        raise MemoryError("AgentCore Memory returned invalid record summaries")
    records: list[MemoryRecord] = []
    for summary in cast("list[object]", summaries):
        if not isinstance(summary, dict):
            raise MemoryError("AgentCore Memory returned an invalid record")
        summary_mapping = cast("dict[str, object]", summary)
        content = summary_mapping.get("content")
        namespaces = summary_mapping.get("namespaces")
        if not isinstance(content, dict):
            raise MemoryError("AgentCore Memory returned invalid record content")
        content_mapping = cast("dict[str, object]", content)
        text = content_mapping.get("text")
        if not isinstance(text, str):
            raise MemoryError("AgentCore Memory returned invalid record content")
        try:
            record = MemoryRecord.model_validate_json(text)
        except ValidationError as error:
            raise MemoryError("AgentCore Memory returned disallowed record content") from error
        if (
            not isinstance(namespaces, list)
            or record_namespace(actor_id, record.kind) not in namespaces
        ):
            raise MemoryError("AgentCore Memory returned a record outside its typed namespace")
        records.append(record)
    return tuple(records)


def memory_prompt_context(records: Sequence[MemoryRecord]) -> tuple[str, ...]:
    """Serialize validated memory content for the agent prompt boundary."""
    return tuple(
        json.dumps(record.model_dump(mode="json"), separators=(",", ":")) for record in records
    )
