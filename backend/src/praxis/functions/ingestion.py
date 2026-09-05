"""Ingest validated source JSON from S3 into the DynamoDB catalog."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol, cast

from boto3.dynamodb.types import TypeSerializer
from boto3.session import Session
from pydantic import TypeAdapter, ValidationError

from praxis.catalog import (
    CatalogEntry,
    CatalogItem,
    CatalogKind,
    catalog_entry,
    catalog_search_text,
)
from praxis.catalog.text import normalize_text
from praxis.domain import Book, Byte, MuseumObject, Project

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource
    from mypy_boto3_dynamodb.type_defs import (
        AttributeValueTypeDef,
        WriteRequestOutputTypeDef,
        WriteRequestTypeDef,
    )
    from mypy_boto3_s3.client import S3Client

type DynamoScalar = str | int | Decimal | bool | None
type DynamoValue = DynamoScalar | list[DynamoValue] | dict[str, DynamoValue]
type DynamoItem = dict[str, DynamoValue]

BATCH_WRITE_LIMIT = 25
MAX_BATCH_WRITE_ATTEMPTS = 5
SCHEMA_VERSION = 1
INGESTION_REPORT_ID = "ingestion:latest"
RAW_RECORDS_ADAPTER = TypeAdapter(list[object])
BOOK_ADAPTER = TypeAdapter(Book)
PROJECT_ADAPTER = TypeAdapter(Project)
BYTE_ADAPTER = TypeAdapter(Byte)
MUSEUM_ADAPTER = TypeAdapter(MuseumObject)
DYNAMO_SERIALIZER = TypeSerializer()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class IngestionConfigurationError(ValueError):
    """Raised when required Lambda environment configuration is absent."""


class IngestionWriteError(RuntimeError):
    """Raised when DynamoDB does not accept a batch after bounded retries."""


class SourceReader(Protocol):
    """Read source object bytes without exposing an SDK client to ingestion logic."""

    def read_bytes(self, bucket_name: str, object_key: str) -> bytes:
        """Return one complete source object."""
        ...


class CatalogWriter(Protocol):
    """Reconcile the deployed table to a complete catalog snapshot."""

    def replace_items(self, table_name: str, items: Sequence[DynamoItem]) -> int:
        """Replace catalog items and return the number of stale records deleted."""
        ...

    def record_report(self, table_name: str, report: DynamoItem) -> None:
        """Persist the latest ingestion report outside the catalog index."""
        ...


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    """Runtime resources used by the ingestion Lambda."""

    source_bucket_name: str
    catalog_table_name: str

    @classmethod
    def from_environment(cls) -> IngestionConfig:
        """Load required resource names from Lambda environment variables."""
        return cls(
            source_bucket_name=_required_environment("SOURCE_BUCKET_NAME"),
            catalog_table_name=_required_environment("CATALOG_TABLE_NAME"),
        )


@dataclass(frozen=True, slots=True)
class SourceResult:
    """Count records accepted from one source object."""

    kind: CatalogKind
    object_key: str
    record_count: int
    rejected_count: int


@dataclass(frozen=True, slots=True)
class RejectedRecord:
    """Safe validation details for one rejected source record."""

    kind: CatalogKind
    object_key: str
    ordinal: int
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IngestionReport:
    """Structured result returned by a successful ingestion invocation."""

    sources: tuple[SourceResult, ...]
    records_deleted: int
    rejected_records: tuple[RejectedRecord, ...]
    catalog_updated: bool

    @property
    def records_accepted(self) -> int:
        """Return the total records that passed source validation."""
        return sum(source.record_count for source in self.sources)

    @property
    def records_written(self) -> int:
        """Return records written only when the snapshot was safely updated."""
        return self.records_accepted if self.catalog_updated else 0

    @property
    def records_rejected(self) -> int:
        """Return the total records rejected across all sources."""
        return len(self.rejected_records)

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable Lambda response."""
        return {
            "catalog_updated": self.catalog_updated,
            "records_accepted": self.records_accepted,
            "records_written": self.records_written,
            "records_deleted": self.records_deleted,
            "records_rejected": self.records_rejected,
            "sources": [
                {
                    "kind": source.kind.value,
                    "object_key": source.object_key,
                    "record_count": source.record_count,
                    "rejected_count": source.rejected_count,
                }
                for source in self.sources
            ],
            "rejected_records": [
                {
                    "kind": rejected.kind.value,
                    "object_key": rejected.object_key,
                    "ordinal": rejected.ordinal,
                    "issues": list(rejected.issues),
                }
                for rejected in self.rejected_records
            ],
        }

    def as_item(self) -> DynamoItem:
        """Return the report as a non-catalog DynamoDB metadata item."""
        return {
            "record_id": INGESTION_REPORT_ID,
            "report": _dynamo_value(self.as_dict()),
            "schema_version": SCHEMA_VERSION,
        }


SOURCE_OBJECTS = (
    (CatalogKind.BOOK, "books.json"),
    (CatalogKind.PROJECT, "projects.json"),
    (CatalogKind.BYTE, "bytes.json"),
    (CatalogKind.MUSEUM_OBJECT, "museum.json"),
)


class S3SourceReader:
    """Read source objects through a typed S3 client."""

    def __init__(self, client: S3Client) -> None:
        self._client = client

    def read_bytes(self, bucket_name: str, object_key: str) -> bytes:
        """Read one complete S3 object body."""
        response = self._client.get_object(Bucket=bucket_name, Key=object_key)
        return response["Body"].read()


class DynamoCatalogWriter:
    """Write native Python items through the DynamoDB resource serializer."""

    def __init__(
        self,
        resource: DynamoDBServiceResource,
        client: DynamoDBClient,
    ) -> None:
        self._resource = resource
        self._client = client

    def replace_items(self, table_name: str, items: Sequence[DynamoItem]) -> int:
        """Upsert the target snapshot and remove records no longer present."""
        target_ids = {str(item["record_id"]) for item in items}
        if len(target_ids) != len(items):
            raise IngestionWriteError("Catalog snapshot contains duplicate record IDs")

        put_requests: list[WriteRequestTypeDef] = [
            {"PutRequest": {"Item": serialize_dynamo_item(item)}} for item in items
        ]
        self._write_requests(table_name, put_requests)

        stale_ids = self._existing_record_ids(table_name) - target_ids
        delete_requests: list[WriteRequestTypeDef] = [
            {"DeleteRequest": {"Key": serialize_dynamo_item({"record_id": record_id})}}
            for record_id in sorted(stale_ids)
        ]
        self._write_requests(table_name, delete_requests)
        return len(stale_ids)

    def record_report(self, table_name: str, report: DynamoItem) -> None:
        """Persist one latest-report metadata item using the retrying writer."""
        request: WriteRequestTypeDef = {"PutRequest": {"Item": serialize_dynamo_item(report)}}
        self._write_batch(table_name, (request,))

    def _existing_record_ids(self, table_name: str) -> set[str]:
        table = self._resource.Table(table_name)
        response = table.scan(
            ProjectionExpression="record_id, #kind",
            ExpressionAttributeNames={"#kind": "kind"},
        )
        record_ids: set[str] = set()
        while True:
            record_ids.update(
                record_id
                for item in response.get("Items", ())
                if item.get("kind") in {kind.value for kind in CatalogKind}
                if isinstance((record_id := item.get("record_id")), str)
            )
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return record_ids
            response = table.scan(
                ProjectionExpression="record_id, #kind",
                ExpressionAttributeNames={"#kind": "kind"},
                ExclusiveStartKey=last_key,
            )

    def _write_requests(
        self,
        table_name: str,
        requests: Sequence[WriteRequestTypeDef],
    ) -> None:
        for offset in range(0, len(requests), BATCH_WRITE_LIMIT):
            self._write_batch(table_name, requests[offset : offset + BATCH_WRITE_LIMIT])

    def _write_batch(
        self,
        table_name: str,
        requests: Sequence[WriteRequestTypeDef],
    ) -> None:
        pending: Sequence[WriteRequestTypeDef | WriteRequestOutputTypeDef] = requests
        for attempt in range(MAX_BATCH_WRITE_ATTEMPTS):
            response = self._client.batch_write_item(RequestItems={table_name: pending})
            pending = response.get("UnprocessedItems", {}).get(table_name, ())
            if not pending:
                return
            time.sleep(0.05 * (2**attempt))
        message = f"DynamoDB left {len(pending)} catalog writes unprocessed"
        raise IngestionWriteError(message)


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        message = f"{name} is required"
        raise IngestionConfigurationError(message)
    return value


def _validated_item(kind: CatalogKind, value: object) -> CatalogItem:
    encoded = json.dumps(value, separators=(",", ":")).encode()
    match kind:
        case CatalogKind.BOOK:
            return BOOK_ADAPTER.validate_json(encoded)
        case CatalogKind.PROJECT:
            return PROJECT_ADAPTER.validate_json(encoded)
        case CatalogKind.BYTE:
            return BYTE_ADAPTER.validate_json(encoded)
        case CatalogKind.MUSEUM_OBJECT:
            return MUSEUM_ADAPTER.validate_json(encoded)


def _validation_issues(error: ValidationError) -> tuple[str, ...]:
    return tuple(
        f"{'.'.join(str(part) for part in issue['loc']) or '$'}:{issue['type']}"
        for issue in error.errors(include_input=False, include_url=False)
    )


def _validated_items(
    kind: CatalogKind,
    object_key: str,
    body: bytes,
) -> tuple[tuple[tuple[int, CatalogItem], ...], tuple[RejectedRecord, ...]]:
    accepted: list[tuple[int, CatalogItem]] = []
    rejected: list[RejectedRecord] = []
    for ordinal, value in enumerate(RAW_RECORDS_ADAPTER.validate_json(body)):
        try:
            accepted.append((ordinal, _validated_item(kind, value)))
        except ValidationError as error:
            rejected.append(
                RejectedRecord(
                    kind=kind,
                    object_key=object_key,
                    ordinal=ordinal,
                    issues=_validation_issues(error),
                )
            )
    return tuple(accepted), tuple(rejected)


def _record_fields(entry: CatalogEntry) -> tuple[str, str, str | None, list[str]]:
    match entry.item:
        case Book() as book:
            languages = [normalize_text(book.language)] if book.language else []
            return book.title, f"{book.year:04d}", book.category, languages
        case Project() as project:
            languages = sorted({normalize_text(language) for language in project.languages})
            return project.name, project.date or "0000", None, languages
        case Byte() as byte:
            return byte.name, byte.date.isoformat(), byte.category, []
        case MuseumObject() as museum:
            sort_date = f"{museum.year:04d}" if museum.year is not None else "0000"
            return museum.name, sort_date, museum.category, []


def _dynamo_value(value: object) -> DynamoValue:
    if value is None or isinstance(value, (bool, str, int, Decimal)):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        values = cast("list[object]", value)
        return [_dynamo_value(item) for item in values]
    if isinstance(value, dict):
        values = cast("dict[object, object]", value)
        return {str(key): _dynamo_value(item) for key, item in values.items()}
    message = f"Unsupported catalog value type: {type(value).__name__}"
    raise TypeError(message)


def serialize_dynamo_item(item: Mapping[str, DynamoValue]) -> dict[str, AttributeValueTypeDef]:
    """Convert a native item to the low-level DynamoDB wire representation."""
    return {
        name: cast("AttributeValueTypeDef", DYNAMO_SERIALIZER.serialize(value))
        for name, value in item.items()
    }


def _catalog_item(entry: CatalogEntry, object_key: str, ordinal: int) -> DynamoItem:
    label, sort_date, category, languages = _record_fields(entry)
    payload_json = entry.item.model_dump_json(by_alias=True)
    payload = cast("dict[str, object]", entry.item.model_dump(mode="json", by_alias=True))
    item: DynamoItem = {
        "record_id": entry.id,
        "kind": entry.kind.value,
        "kind_date_key": f"{sort_date}#{entry.id}",
        "label": label,
        "languages": _dynamo_value(languages),
        "search_text": catalog_search_text(entry.item),
        "source": {
            "file": object_key,
            "ordinal": ordinal,
            "content_digest": sha256(payload_json.encode()).hexdigest(),
        },
        "payload": cast("dict[str, DynamoValue]", _dynamo_value(payload)),
        "schema_version": SCHEMA_VERSION,
    }
    if category:
        item["category"] = normalize_text(category)
    return item


def run_ingestion(
    config: IngestionConfig,
    source_reader: SourceReader,
    catalog_writer: CatalogWriter,
) -> IngestionReport:
    """Read, validate, transform, and batch-write all catalog sources."""
    records: list[DynamoItem] = []
    source_results: list[SourceResult] = []
    rejected_records: list[RejectedRecord] = []
    for kind, object_key in SOURCE_OBJECTS:
        source_items, source_rejections = _validated_items(
            kind,
            object_key,
            source_reader.read_bytes(config.source_bucket_name, object_key),
        )
        records.extend(
            _catalog_item(catalog_entry(item), object_key, ordinal)
            for ordinal, item in source_items
        )
        rejected_records.extend(source_rejections)
        source_results.append(
            SourceResult(
                kind=kind,
                object_key=object_key,
                record_count=len(source_items),
                rejected_count=len(source_rejections),
            )
        )
    if rejected_records:
        report = IngestionReport(
            sources=tuple(source_results),
            records_deleted=0,
            rejected_records=tuple(rejected_records),
            catalog_updated=False,
        )
        catalog_writer.record_report(config.catalog_table_name, report.as_item())
        return report

    records_deleted = catalog_writer.replace_items(config.catalog_table_name, records)
    report = IngestionReport(
        sources=tuple(source_results),
        records_deleted=records_deleted,
        rejected_records=(),
        catalog_updated=True,
    )
    catalog_writer.record_report(config.catalog_table_name, report.as_item())
    return report


def lambda_handler(_event: object, _context: object) -> dict[str, object]:
    """AWS Lambda entry point for a complete catalog ingestion run."""
    started = time.monotonic()
    report: IngestionReport | None = None
    outcome = "error"
    try:
        config = IngestionConfig.from_environment()
        session = Session()
        s3_client: S3Client = session.client("s3")  # pyright: ignore[reportUnknownMemberType]
        dynamodb_client: DynamoDBClient = session.client("dynamodb")  # pyright: ignore[reportUnknownMemberType]
        dynamodb_resource: DynamoDBServiceResource = session.resource("dynamodb")  # pyright: ignore[reportUnknownMemberType]
        source_reader = S3SourceReader(s3_client)
        catalog_writer = DynamoCatalogWriter(dynamodb_resource, dynamodb_client)
        report = run_ingestion(config, source_reader, catalog_writer)
        response = report.as_dict()
        outcome = "updated" if report.catalog_updated else "rejected"
        return response
    finally:
        # An incomplete run can have partial writes; unknown counts must not look like zero.
        level = logging.ERROR if outcome == "error" else logging.INFO
        if outcome == "rejected":
            level = logging.WARNING
        logger.log(
            level,
            "catalog_ingestion",
            extra={
                "outcome": outcome,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "records_accepted": report.records_accepted if report else None,
                "records_written": report.records_written if report else None,
                "records_deleted": report.records_deleted if report else None,
                "records_rejected": report.records_rejected if report else None,
            },
        )
