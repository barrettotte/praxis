"""Bounded DynamoDB-backed catalog operations for AWS Lambda."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, cast

from boto3.session import Session
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from praxis.catalog import (
    CatalogEntry,
    CatalogItem,
    CatalogKind,
    CatalogSearchResult,
    GetCatalogItemRequest,
    InMemoryCatalog,
    SearchCatalogRequest,
    catalog_entry,
    get_catalog_item,
    project_evidence,
    search_catalog,
)
from praxis.catalog.search import MAX_SEARCH_EVALUATED_ITEMS
from praxis.domain import Book, Byte, MuseumObject, Project

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table
    from mypy_boto3_dynamodb.type_defs import TableAttributeValueTypeDef


class CatalogConfigurationError(ValueError):
    """Raised when catalog Lambda configuration is absent."""


class CatalogDataError(ValueError):
    """Raised when a deployed catalog item violates the storage contract."""


class CatalogRepository(Protocol):
    """Storage boundary used by the catalog Lambda operation handler."""

    def search(self, request: SearchCatalogRequest) -> tuple[CatalogSearchResult, ...]:
        """Return bounded, ranked catalog matches."""
        ...

    def get(self, request: GetCatalogItemRequest) -> CatalogEntry:
        """Return one catalog record by stable evidence ID."""
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


type CatalogRequest = Annotated[
    SearchCatalogInvocation | GetCatalogItemInvocation,
    Field(discriminator="operation"),
]
CATALOG_REQUEST_ADAPTER: TypeAdapter[CatalogRequest] = TypeAdapter(CatalogRequest)


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

    @classmethod
    def from_resource(
        cls, resource: DynamoDBServiceResource, table_name: str
    ) -> DynamoCatalogRepository:
        """Bind the repository to one configured table."""
        return cls(table=resource.Table(table_name))

    def search(self, request: SearchCatalogRequest) -> tuple[CatalogSearchResult, ...]:
        """Load at most the evaluated-item budget and reuse deterministic ranking."""
        kinds = tuple(CatalogKind) if request.kinds is None else tuple(sorted(request.kinds))
        entries: list[CatalogEntry] = []
        evaluated = 0
        for kind in kinds:
            last_key: Mapping[str, TableAttributeValueTypeDef] | None = None
            while evaluated < MAX_SEARCH_EVALUATED_ITEMS:
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
        return search_catalog(_in_memory_catalog(tuple(entries)), request)

    def get(self, request: GetCatalogItemRequest) -> CatalogEntry:
        """Read and validate one projected DynamoDB item."""
        response = self.table.get_item(
            Key={"record_id": request.id},
            ProjectionExpression="record_id, #kind, payload",
            ExpressionAttributeNames={"#kind": "kind"},
        )
        item = response.get("Item")
        if item is None:
            return get_catalog_item(_in_memory_catalog(()), request)
        return _entry_from_item(item)


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
        case _:
            raise AssertionError("Validated catalog operation was not handled")


def lambda_handler(event: object, _context: object) -> dict[str, object]:
    """AWS Lambda entry point for bounded read-only catalog operations."""
    table_name = _required_environment("CATALOG_TABLE_NAME")
    session = Session()
    resource: DynamoDBServiceResource = session.resource("dynamodb")  # pyright: ignore[reportUnknownMemberType]
    repository = DynamoCatalogRepository.from_resource(resource, table_name)
    return handle_catalog_request(event, repository)
