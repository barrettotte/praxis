"""Bounded DynamoDB-backed catalog operations for AWS Lambda."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, cast, runtime_checkable

from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from praxis.catalog import (
    CatalogEntry,
    CatalogItem,
    CatalogItemNotFoundError,
    CatalogKind,
    CatalogSearchResult,
    CompareProjectHistoryRequest,
    GetCatalogItemRequest,
    InMemoryCatalog,
    SearchCatalogRequest,
    catalog_entry,
    compare_project_history,
    get_catalog_item,
    project_evidence,
    search_catalog,
)
from praxis.catalog.search import MAX_SEARCH_EVALUATED_ITEMS
from praxis.domain import Book, Byte, MuseumObject, Project
from praxis.functions.tracing import lambda_invocation_trace_context, lambda_tracer
from praxis.tools import (
    MAX_CANDIDATE_SCORE_EVIDENCE_IDS,
    ScoreProjectCandidatesInput,
    SummarizeExperienceInput,
    validate_tool_input,
    validate_tool_output,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table
    from mypy_boto3_dynamodb.type_defs import TableAttributeValueTypeDef

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
tracer = lambda_tracer(__name__)


class CatalogConfigurationError(ValueError):
    """Raised when catalog Lambda configuration is absent."""


class CatalogDataError(ValueError):
    """Raised when a deployed catalog item violates the storage contract."""


class CatalogGatewayInvocationError(ValueError):
    """Raised when AgentCore supplies an unsupported tool context."""


type CatalogToolErrorCode = Literal[
    "DEPENDENCY_FAILURE",
    "INTERNAL_ERROR",
    "INVALID_ARGUMENTS",
    "NOT_FOUND",
    "TIMEOUT",
]


class CatalogToolError(RuntimeError):
    """Safe, stable error raised for AgentCore to convert into an MCP error."""

    def __init__(
        self,
        code: CatalogToolErrorCode,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        self.code = code
        self.public_message = message
        self.retryable = retryable
        super().__init__(json.dumps(self.as_dict(), separators=(",", ":")))

    def as_dict(self) -> dict[str, object]:
        """Return the public error payload without internal exception details."""
        return {
            "code": self.code,
            "message": self.public_message,
            "retryable": self.retryable,
        }


@runtime_checkable
class RemainingTimeContext(Protocol):
    """Lambda context capability used to stop before the hard timeout."""

    def get_remaining_time_in_millis(self) -> int:
        """Return execution time remaining before Lambda termination."""
        ...


class CatalogRepository(Protocol):
    """Storage boundary used by the catalog Lambda operation handler."""

    def search(self, request: SearchCatalogRequest) -> tuple[CatalogSearchResult, ...]:
        """Return bounded, ranked catalog matches."""
        ...

    def get(self, request: GetCatalogItemRequest) -> CatalogEntry:
        """Return one catalog record by stable evidence ID."""
        ...

    def project_entries(self) -> tuple[CatalogEntry, ...]:
        """Return the bounded historical-project snapshot."""
        ...


class CatalogInvocation(BaseModel):
    """Apply strict validation to internal Lambda invocation envelopes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SearchCatalogInvocation(CatalogInvocation):
    """Invoke bounded catalog search."""

    operation: Literal["search_catalog"]
    arguments: SearchCatalogRequest


class GetCatalogItemInvocation(CatalogInvocation):
    """Invoke stable evidence lookup."""

    operation: Literal["get_catalog_item"]
    arguments: GetCatalogItemRequest


class SummarizeExperienceInvocation(CatalogInvocation):
    """Invoke deterministic prior-project comparison."""

    operation: Literal["summarize_experience"]
    arguments: SummarizeExperienceInput


class ScoreProjectCandidatesInvocation(CatalogInvocation):
    """Invoke deterministic candidate-history scoring."""

    operation: Literal["score_project_candidates"]
    arguments: ScoreProjectCandidatesInput


type CatalogRequest = Annotated[
    SearchCatalogInvocation
    | GetCatalogItemInvocation
    | SummarizeExperienceInvocation
    | ScoreProjectCandidatesInvocation,
    Field(discriminator="operation"),
]
CATALOG_REQUEST_ADAPTER: TypeAdapter[CatalogRequest] = TypeAdapter(CatalogRequest)
type CatalogGatewayToolName = Literal[
    "get_catalog_item",
    "score_project_candidates",
    "search_catalog",
    "summarize_experience",
]
CATALOG_GATEWAY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_catalog_item",
        "score_project_candidates",
        "search_catalog",
        "summarize_experience",
    }
)
GATEWAY_TOOL_DELIMITER = "___"
GATEWAY_TOOL_CONTEXT_KEY = "bedrockAgentCoreToolName"
MINIMUM_REMAINING_TIME_MS = 6_000
CATALOG_CLIENT_CONFIG = Config(
    connect_timeout=2,
    read_timeout=5,
    retries={"mode": "standard", "total_max_attempts": 2},
    tcp_keepalive=True,
)


def ensure_time_budget(context: object) -> None:
    """Stop safely before Lambda's hard timeout can truncate a response."""
    if (
        isinstance(context, RemainingTimeContext)
        and context.get_remaining_time_in_millis() < MINIMUM_REMAINING_TIME_MS
    ):
        raise CatalogToolError(
            "TIMEOUT",
            "Catalog tool did not have enough time to complete.",
            retryable=True,
        )


def _safe_tool_error(error: Exception) -> CatalogToolError:
    if isinstance(error, CatalogToolError):
        return error
    if isinstance(error, (ValidationError, CatalogGatewayInvocationError)):
        return CatalogToolError(
            "INVALID_ARGUMENTS", "Catalog tool arguments are invalid.", retryable=False
        )
    if isinstance(error, CatalogItemNotFoundError):
        return CatalogToolError("NOT_FOUND", "Catalog item was not found.", retryable=False)
    if isinstance(error, (BotoCoreError, ClientError)):
        return CatalogToolError(
            "DEPENDENCY_FAILURE",
            "Catalog storage is temporarily unavailable.",
            retryable=True,
        )
    return CatalogToolError("INTERNAL_ERROR", "Catalog tool failed.", retryable=False)


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CatalogConfigurationError(f"{name} is required")
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        values = cast("list[object]", value)
        return [_json_value(item) for item in values]
    if isinstance(value, dict):
        values = cast("dict[object, object]", value)
        return {str(key): _json_value(item) for key, item in values.items()}
    return value


def _domain_item(kind: CatalogKind, payload: object) -> CatalogItem:
    encoded = json.dumps(_json_value(payload), separators=(",", ":")).encode()
    match kind:
        case CatalogKind.BOOK:
            return TypeAdapter(Book).validate_json(encoded)
        case CatalogKind.PROJECT:
            return TypeAdapter(Project).validate_json(encoded)
        case CatalogKind.BYTE:
            return TypeAdapter(Byte).validate_json(encoded)
        case CatalogKind.MUSEUM_OBJECT:
            return TypeAdapter(MuseumObject).validate_json(encoded)


def _entry_from_item(item: Mapping[str, TableAttributeValueTypeDef]) -> CatalogEntry:
    record_id = item.get("record_id")
    raw_kind = item.get("kind")
    payload = item.get("payload")
    if not isinstance(record_id, str) or not isinstance(raw_kind, str) or payload is None:
        raise CatalogDataError("Catalog item is missing record_id, kind, or payload")
    try:
        kind = CatalogKind(raw_kind)
    except ValueError as error:
        raise CatalogDataError("Catalog item has an unsupported kind") from error
    domain_item = _domain_item(kind, payload)
    expected = catalog_entry(domain_item)
    if expected.id != record_id or expected.kind is not kind:
        raise CatalogDataError("Catalog item identity does not match its payload")
    return CatalogEntry(id=record_id, kind=kind, item=domain_item)


def _in_memory_catalog(entries: tuple[CatalogEntry, ...]) -> InMemoryCatalog:
    return InMemoryCatalog(
        books=tuple(entry.item for entry in entries if isinstance(entry.item, Book)),
        projects=tuple(entry.item for entry in entries if isinstance(entry.item, Project)),
        bytes=tuple(entry.item for entry in entries if isinstance(entry.item, Byte)),
        museum_objects=tuple(
            entry.item for entry in entries if isinstance(entry.item, MuseumObject)
        ),
    )


@dataclass(frozen=True, slots=True)
class DynamoCatalogRepository:
    """Read catalog records from their DynamoDB primary and GSI access paths."""

    table: Table
    time_budget_guard: Callable[[], None]

    @classmethod
    def from_resource(
        cls,
        resource: DynamoDBServiceResource,
        table_name: str,
        time_budget_guard: Callable[[], None],
    ) -> DynamoCatalogRepository:
        """Bind the repository to one configured table."""
        return cls(table=resource.Table(table_name), time_budget_guard=time_budget_guard)

    def search(self, request: SearchCatalogRequest) -> tuple[CatalogSearchResult, ...]:
        """Load at most the evaluated-item budget and reuse deterministic ranking."""
        kinds = tuple(CatalogKind) if request.kinds is None else tuple(sorted(request.kinds))
        entries = self._entries_for_kinds(kinds)
        return search_catalog(_in_memory_catalog(entries), request)

    def _entries_for_kinds(self, kinds: tuple[CatalogKind, ...]) -> tuple[CatalogEntry, ...]:
        """Read a bounded set of projected entries through the catalog GSI."""
        entries: list[CatalogEntry] = []
        evaluated = 0
        for kind in kinds:
            last_key: Mapping[str, TableAttributeValueTypeDef] | None = None
            while evaluated < MAX_SEARCH_EVALUATED_ITEMS:
                self.time_budget_guard()
                remaining = MAX_SEARCH_EVALUATED_ITEMS - evaluated
                query: dict[str, object] = {
                    "IndexName": "kind-date-index",
                    "KeyConditionExpression": "#kind = :kind",
                    "ExpressionAttributeNames": {"#kind": "kind"},
                    "ExpressionAttributeValues": {":kind": kind.value},
                    "ProjectionExpression": "record_id, #kind, payload",
                    "Limit": remaining,
                }
                if last_key:
                    query["ExclusiveStartKey"] = last_key
                response = self.table.query(**query)  # pyright: ignore[reportArgumentType]
                evaluated += response.get("ScannedCount", 0)
                entries.extend(_entry_from_item(item) for item in response.get("Items", ()))
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
            if evaluated >= MAX_SEARCH_EVALUATED_ITEMS:
                break
        return tuple(entries)

    def get(self, request: GetCatalogItemRequest) -> CatalogEntry:
        """Read and validate one projected DynamoDB item."""
        self.time_budget_guard()
        response = self.table.get_item(
            Key={"record_id": request.id},
            ProjectionExpression="record_id, #kind, payload",
            ExpressionAttributeNames={"#kind": "kind"},
        )
        item = response.get("Item")
        if item is None:
            return get_catalog_item(_in_memory_catalog(()), request)
        return _entry_from_item(item)

    def project_entries(self) -> tuple[CatalogEntry, ...]:
        """Read bounded project history through the existing catalog GSI."""
        return self._entries_for_kinds((CatalogKind.PROJECT,))


def _project_history_catalog(repository: CatalogRepository) -> InMemoryCatalog:
    return _in_memory_catalog(repository.project_entries())


def _experience_matches(
    catalog: InMemoryCatalog, request: SummarizeExperienceInput
) -> list[dict[str, object]]:
    matches = compare_project_history(
        catalog,
        CompareProjectHistoryRequest(
            description=request.description,
            languages=frozenset(request.languages),
            limit=request.limit,
        ),
    )
    output: list[dict[str, object]] = []
    for match in matches:
        projected: dict[str, object] = {
            "evidence_id": match.evidence_id,
            "name": match.project.name,
            "matched_terms": list(match.matched_terms),
            "shared_languages": list(match.shared_languages),
            "history_overlap_score": match.score,
        }
        if match.project.date is not None:
            projected["date"] = match.project.date
        output.append(projected)
    return output


def _candidate_history_scores(
    catalog: InMemoryCatalog, request: ScoreProjectCandidatesInput
) -> list[dict[str, object]]:
    scores: list[dict[str, object]] = []
    for candidate in request.candidates:
        matches = compare_project_history(
            catalog,
            CompareProjectHistoryRequest(
                description=candidate.description,
                languages=frozenset(candidate.languages),
                limit=MAX_CANDIDATE_SCORE_EVIDENCE_IDS,
            ),
        )
        scores.append(
            {
                "candidate_id": candidate.candidate_id,
                "history_overlap_score": sum(match.score for match in matches),
                "evidence_ids": [match.evidence_id for match in matches],
            }
        )
    return scores


def handle_catalog_request(event: object, repository: CatalogRepository) -> dict[str, object]:
    """Validate one invocation and return a minimal factual response."""
    request = CATALOG_REQUEST_ADAPTER.validate_json(json.dumps(event, separators=(",", ":")))
    match request:
        case SearchCatalogInvocation():
            results = repository.search(request.arguments)
            return {
                "operation": request.operation,
                "results": [
                    {"score": result.score} | project_evidence(result.entry) for result in results
                ],
            }
        case GetCatalogItemInvocation():
            return {
                "operation": request.operation,
                "item": project_evidence(repository.get(request.arguments)),
            }
        case SummarizeExperienceInvocation():
            return {
                "operation": request.operation,
                "matches": _experience_matches(
                    _project_history_catalog(repository), request.arguments
                ),
            }
        case ScoreProjectCandidatesInvocation():
            return {
                "operation": request.operation,
                "scores": _candidate_history_scores(
                    _project_history_catalog(repository), request.arguments
                ),
            }
        case _:
            raise AssertionError("Validated catalog operation was not handled")


def _gateway_tool_name(context: object) -> CatalogGatewayToolName | None:
    client_context = getattr(context, "client_context", None)
    custom = getattr(client_context, "custom", None)
    if not isinstance(custom, Mapping):
        return None
    custom_values = cast("Mapping[object, object]", custom)
    qualified_name = custom_values.get(GATEWAY_TOOL_CONTEXT_KEY)
    if qualified_name is None:
        return None
    if not isinstance(qualified_name, str):
        raise CatalogGatewayInvocationError("AgentCore tool name must be a string")
    _target_name, delimiter, tool_name = qualified_name.rpartition(GATEWAY_TOOL_DELIMITER)
    if not delimiter or tool_name not in CATALOG_GATEWAY_TOOL_NAMES:
        raise CatalogGatewayInvocationError("AgentCore requested an unsupported catalog tool")
    return cast("CatalogGatewayToolName", tool_name)


def execute_catalog_tool(
    tool_name: CatalogGatewayToolName, event: object, repository: CatalogRepository
) -> dict[str, object]:
    """Apply identical tool contracts to in-memory and Lambda-backed requests."""
    arguments = validate_tool_input(tool_name, event).model_dump(mode="json", exclude_none=True)
    response = handle_catalog_request({"operation": tool_name, "arguments": arguments}, repository)
    gateway_response = {key: value for key, value in response.items() if key != "operation"}
    validated = validate_tool_output(tool_name, gateway_response)
    return cast("dict[str, object]", validated.model_dump(mode="json", exclude_none=True))


def handle_catalog_invocation(
    event: object, context: object, repository: CatalogRepository
) -> dict[str, object]:
    """Handle direct envelopes and AgentCore Gateway tool events."""
    try:
        ensure_time_budget(context)
        tool_name = _gateway_tool_name(context)
        if tool_name is None:
            return handle_catalog_request(event, repository)

        return execute_catalog_tool(tool_name, event, repository)
    except Exception as error:
        raise _safe_tool_error(error) from error


def lambda_handler(event: object, context: object) -> dict[str, object]:
    """AWS Lambda entry point for bounded read-only catalog operations."""
    with tracer.start_as_current_span(
        "praxis.catalog.request",
        context=lambda_invocation_trace_context(),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            response = _handle_request(event, context)
        except CatalogToolError as error:
            span.set_attribute("praxis.outcome", error.code)
            span.set_status(trace.StatusCode.ERROR)
            raise
        except Exception:
            span.set_attribute("praxis.outcome", "INTERNAL_ERROR")
            span.set_status(trace.StatusCode.ERROR)
            raise
        span.set_attribute("praxis.outcome", "success")
        return response


def _handle_request(event: object, context: object) -> dict[str, object]:
    """Execute catalog work with normalized errors and content-free outcome logs."""
    started = monotonic()
    outcome = "INTERNAL_ERROR"
    try:
        ensure_time_budget(context)
        table_name = _required_environment("CATALOG_TABLE_NAME")
        session = Session()
        resource: DynamoDBServiceResource = session.resource(  # pyright: ignore[reportUnknownMemberType]
            "dynamodb", config=CATALOG_CLIENT_CONFIG
        )
        repository = DynamoCatalogRepository.from_resource(
            resource,
            table_name,
            time_budget_guard=lambda: ensure_time_budget(context),
        )
        response = handle_catalog_invocation(event, context, repository)
        outcome = "success"
        return response
    except Exception as error:
        safe_error = _safe_tool_error(error)
        outcome = safe_error.code
        raise safe_error from error
    finally:
        # Log only the normalized outcome, never arguments, records, or error text.
        level = logging.ERROR
        if outcome == "success":
            level = logging.INFO
        elif outcome in {"INVALID_ARGUMENTS", "NOT_FOUND"}:
            level = logging.WARNING
        logger.log(
            level,
            "catalog_request",
            extra={"outcome": outcome, "duration_ms": round((monotonic() - started) * 1000)},
        )
