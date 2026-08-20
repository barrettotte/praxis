from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from praxis.functions.ingestion import (
    CatalogWriter,
    DynamoCatalogWriter,
    DynamoItem,
    IngestionConfig,
    IngestionConfigurationError,
    SourceReader,
    run_ingestion,
    serialize_dynamo_item,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource
    from mypy_boto3_dynamodb.type_defs import BatchWriteItemOutputTypeDef

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"


class FixtureSourceReader(SourceReader):
    def __init__(self, directory: Path, overrides: Mapping[str, bytes] | None = None) -> None:
        self._directory = directory
        self._overrides = dict(overrides or {})
        self.reads: list[tuple[str, str]] = []

    def read_bytes(self, bucket_name: str, object_key: str) -> bytes:
        self.reads.append((bucket_name, object_key))
        if object_key in self._overrides:
            return self._overrides[object_key]
        return (self._directory / object_key).read_bytes()


class RecordingCatalogWriter(CatalogWriter):
    def __init__(self) -> None:
        self.table_name: str | None = None
        self.items: tuple[DynamoItem, ...] = ()
        self.report: DynamoItem | None = None

    def replace_items(self, table_name: str, items: Sequence[DynamoItem]) -> int:
        previous_ids = {str(item["record_id"]) for item in self.items}
        target_ids = {str(item["record_id"]) for item in items}
        self.table_name = table_name
        self.items = tuple(items)
        return len(previous_ids - target_ids)

    def record_report(self, table_name: str, report: DynamoItem) -> None:
        self.table_name = table_name
        self.report = report


class RecordingBatchClient:
    def __init__(self) -> None:
        self.request_items: object | None = None

    def batch_write_item(self, **kwargs: object) -> BatchWriteItemOutputTypeDef:
        self.request_items = kwargs["RequestItems"]
        return cast(
            "BatchWriteItemOutputTypeDef",
            {
                "UnprocessedItems": {},
                "ItemCollectionMetrics": {},
                "ConsumedCapacity": [],
                "ResponseMetadata": {},
            },
        )


def _item_by_id(items: Sequence[DynamoItem]) -> Mapping[str, DynamoItem]:
    return {str(item["record_id"]): item for item in items}


def test_run_ingestion_reads_validates_and_writes_all_sources() -> None:
    reader = FixtureSourceReader(FIXTURE_DIRECTORY)
    writer = RecordingCatalogWriter()
    config = IngestionConfig(source_bucket_name="source-bucket", catalog_table_name="catalog")

    report = run_ingestion(config, reader, writer)

    assert report.records_written == 8
    assert report.records_accepted == 8
    assert report.records_deleted == 0
    assert report.records_rejected == 0
    assert report.catalog_updated
    assert [source.record_count for source in report.sources] == [2, 2, 2, 2]
    assert reader.reads == [
        ("source-bucket", "books.json"),
        ("source-bucket", "projects.json"),
        ("source-bucket", "bytes.json"),
        ("source-bucket", "museum.json"),
    ]
    assert writer.table_name == "catalog"
    assert len(writer.items) == 8
    assert writer.report is not None
    assert writer.report["record_id"] == "ingestion:latest"


def test_ingestion_items_match_local_evidence_ids_and_access_schema() -> None:
    reader = FixtureSourceReader(FIXTURE_DIRECTORY)
    writer = RecordingCatalogWriter()

    run_ingestion(
        IngestionConfig(source_bucket_name="source-bucket", catalog_table_name="catalog"),
        reader,
        writer,
    )

    items = _item_by_id(writer.items)
    project = items["project:caf5bb80f7ceade5"]
    assert project["kind"] == "project"
    assert project["kind_date_key"] == "2024-09#project:caf5bb80f7ceade5"
    assert project["languages"] == ["css", "typescript"]
    assert project["schema_version"] == 1
    assert "typescript" in str(project["search_text"])


def test_ingestion_normalizes_categories_and_languages() -> None:
    reader = FixtureSourceReader(FIXTURE_DIRECTORY)
    writer = RecordingCatalogWriter()

    run_ingestion(
        IngestionConfig(source_bucket_name="source-bucket", catalog_table_name="catalog"),
        reader,
        writer,
    )

    items = _item_by_id(writer.items)
    software_book = items["book:13effac8435d4f50"]
    retro_book = items["book:0f1a93bdfcbe1ab6"]
    project = items["project:caf5bb80f7ceade5"]
    assert software_book["category"] == "software engineering"
    assert retro_book["category"] == "systems and low-level programming"
    assert retro_book["languages"] == ["english"]
    assert project["languages"] == ["css", "typescript"]


def test_ingestion_records_source_provenance() -> None:
    reader = FixtureSourceReader(FIXTURE_DIRECTORY)
    writer = RecordingCatalogWriter()

    run_ingestion(
        IngestionConfig(source_bucket_name="source-bucket", catalog_table_name="catalog"),
        reader,
        writer,
    )

    source = _item_by_id(writer.items)["book:13effac8435d4f50"]["source"]
    assert isinstance(source, dict)
    assert source["file"] == "books.json"
    assert source["ordinal"] == 0
    assert len(str(source["content_digest"])) == 64


def test_batch_write_items_use_the_low_level_dynamodb_wire_format() -> None:
    serialized = serialize_dynamo_item(
        {
            "record_id": "ingestion:latest",
            "schema_version": 1,
            "report": {"catalog_updated": True, "records_written": 1030},
        }
    )

    assert serialized == {
        "record_id": {"S": "ingestion:latest"},
        "schema_version": {"N": "1"},
        "report": {
            "M": {
                "catalog_updated": {"BOOL": True},
                "records_written": {"N": "1030"},
            }
        },
    }


def test_catalog_writer_batches_through_the_explicit_low_level_client() -> None:
    client = RecordingBatchClient()
    writer = DynamoCatalogWriter(
        cast("DynamoDBServiceResource", object()),
        cast("DynamoDBClient", client),
    )

    writer.record_report(
        "catalog",
        {"record_id": "ingestion:latest", "schema_version": 1},
    )

    assert client.request_items == {
        "catalog": (
            {
                "PutRequest": {
                    "Item": {
                        "record_id": {"S": "ingestion:latest"},
                        "schema_version": {"N": "1"},
                    }
                }
            },
        )
    }


def test_repeated_ingestion_reconciles_to_an_identical_snapshot() -> None:
    reader = FixtureSourceReader(FIXTURE_DIRECTORY)
    writer = RecordingCatalogWriter()
    writer.items = (
        {
            "record_id": "book:0000000000000000",
            "kind": "book",
        },
    )
    config = IngestionConfig(source_bucket_name="source-bucket", catalog_table_name="catalog")

    first_report = run_ingestion(config, reader, writer)
    first_items = writer.items
    second_report = run_ingestion(config, reader, writer)

    assert first_report.records_deleted == 1
    assert second_report.records_deleted == 0
    assert writer.items == first_items


def test_rejected_record_is_reported_without_replacing_catalog() -> None:
    reader = FixtureSourceReader(
        FIXTURE_DIRECTORY,
        overrides={"books.json": b'[{"year": 2024}]'},
    )
    writer = RecordingCatalogWriter()
    previous_items: tuple[DynamoItem, ...] = (
        {
            "record_id": "book:0000000000000000",
            "kind": "book",
        },
    )
    writer.items = previous_items

    report = run_ingestion(
        IngestionConfig(source_bucket_name="source-bucket", catalog_table_name="catalog"),
        reader,
        writer,
    )

    assert not report.catalog_updated
    assert report.records_accepted == 6
    assert report.records_written == 0
    assert report.records_rejected == 1
    assert report.records_deleted == 0
    assert report.sources[0].record_count == 0
    assert report.sources[0].rejected_count == 1
    assert report.rejected_records[0].object_key == "books.json"
    assert report.rejected_records[0].ordinal == 0
    assert "title:missing" in report.rejected_records[0].issues
    assert writer.items == previous_items
    assert writer.report is not None
    persisted_report = writer.report["report"]
    assert isinstance(persisted_report, dict)
    assert persisted_report["records_accepted"] == 6
    assert persisted_report["records_written"] == 0
    assert persisted_report["records_rejected"] == 1
    assert persisted_report["rejected_records"] == [
        {
            "kind": "book",
            "object_key": "books.json",
            "ordinal": 0,
            "issues": ["title:missing"],
        }
    ]


@pytest.mark.parametrize("missing_name", ["SOURCE_BUCKET_NAME", "CATALOG_TABLE_NAME"])
def test_ingestion_config_requires_resource_names(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    monkeypatch.setenv("SOURCE_BUCKET_NAME", "source-bucket")
    monkeypatch.setenv("CATALOG_TABLE_NAME", "catalog")
    monkeypatch.delenv(missing_name)

    with pytest.raises(IngestionConfigurationError, match=missing_name):
        IngestionConfig.from_environment()
