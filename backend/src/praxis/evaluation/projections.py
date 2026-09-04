"""Compare authoritative catalog records with agent-facing evidence projections."""

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from praxis.catalog import CatalogEntry, InMemoryCatalog, project_evidence
from praxis.config import load_catalog_directory

REPOSITORY = Path(__file__).parents[4]
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY / "evals" / "catalog-projections" / "results"
SOURCE_FILES = {
    "book": "books.json",
    "project": "projects.json",
    "byte": "bytes.json",
    "museum": "museum.json",
}
JSON_RECORDS = TypeAdapter(list[dict[str, object]])


class ProjectionComparisonModel(BaseModel):
    """Strict base contract for projection measurement artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectionKindResult(ProjectionComparisonModel):
    """Serialized-size and field comparison for one catalog kind."""

    record_count: Annotated[int, Field(ge=1)]
    full_record_bytes: Annotated[int, Field(ge=1)]
    projected_record_bytes: Annotated[int, Field(ge=1)]
    bytes_saved: Annotated[int, Field(ge=0)]
    reduction_fraction: Annotated[float, Field(ge=0, le=1)]
    full_fields: list[str]
    projected_fields: list[str]
    omitted_fields: list[str]


class ProjectionComparison(ProjectionComparisonModel):
    """Reproducible comparison over one authoritative catalog snapshot."""

    version: Annotated[int, Field(ge=1)]
    dataset_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    record_count: Annotated[int, Field(ge=1)]
    full_record_bytes: Annotated[int, Field(ge=1)]
    projected_record_bytes: Annotated[int, Field(ge=1)]
    bytes_saved: Annotated[int, Field(ge=0)]
    reduction_fraction: Annotated[float, Field(ge=0, le=1)]
    serialization: str
    kinds: dict[str, ProjectionKindResult]


def compact_json_size(payload: Mapping[str, object]) -> int:
    """Return deterministic compact-JSON UTF-8 size for one record."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return len(encoded)


def dataset_sha256(directory: Path) -> str:
    """Identify the exact four source files without copying their contents."""
    digest = hashlib.sha256()
    for filename in SOURCE_FILES.values():
        path = directory / filename
        digest.update(filename.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _full_record(entry: CatalogEntry, source: Mapping[str, object]) -> dict[str, object]:
    """Add tool-boundary identity to an otherwise unprojected source record."""
    return {"evidence_id": entry.id, "kind": entry.kind.value} | dict(source)


def _kind_result(
    entries: Sequence[CatalogEntry],
    sources: Sequence[Mapping[str, object]],
) -> ProjectionKindResult:
    """Compare aligned validated entries and authoritative source objects."""
    if len(entries) != len(sources) or not entries:
        raise ValueError("catalog entries and source records must align")
    full_records = [
        _full_record(entry, source) for entry, source in zip(entries, sources, strict=True)
    ]
    projected_records = [project_evidence(entry) for entry in entries]
    full_bytes = sum(compact_json_size(record) for record in full_records)
    projected_bytes = sum(compact_json_size(record) for record in projected_records)
    full_fields = sorted({field for record in full_records for field in record})
    projected_fields = sorted({field for record in projected_records for field in record})
    return ProjectionKindResult(
        record_count=len(entries),
        full_record_bytes=full_bytes,
        projected_record_bytes=projected_bytes,
        bytes_saved=full_bytes - projected_bytes,
        reduction_fraction=(full_bytes - projected_bytes) / full_bytes,
        full_fields=full_fields,
        projected_fields=projected_fields,
        omitted_fields=sorted(set(full_fields) - set(projected_fields)),
    )


def compare_catalog_projections(directory: Path) -> ProjectionComparison:
    """Measure every source record against the exact current tool projection."""
    catalog = InMemoryCatalog.from_directory(directory)
    entries_by_kind: dict[str, list[CatalogEntry]] = {kind: [] for kind in SOURCE_FILES}
    for entry in catalog.entries():
        entries_by_kind[entry.kind.value].append(entry)

    kind_results: dict[str, ProjectionKindResult] = {}
    for kind, filename in SOURCE_FILES.items():
        sources = JSON_RECORDS.validate_json((directory / filename).read_bytes())
        kind_results[kind] = _kind_result(entries_by_kind[kind], sources)

    full_bytes = sum(result.full_record_bytes for result in kind_results.values())
    projected_bytes = sum(result.projected_record_bytes for result in kind_results.values())
    return ProjectionComparison(
        version=1,
        dataset_sha256=dataset_sha256(directory),
        record_count=len(catalog),
        full_record_bytes=full_bytes,
        projected_record_bytes=projected_bytes,
        bytes_saved=full_bytes - projected_bytes,
        reduction_fraction=(full_bytes - projected_bytes) / full_bytes,
        serialization="compact sorted-key JSON records encoded as UTF-8",
        kinds=kind_results,
    )


def write_comparison(result: ProjectionComparison, output_directory: Path) -> Path:
    """Write one content-addressed artifact without replacing prior measurements."""
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"catalog-projections-{result.dataset_sha256[:12]}.json"
    content = f"{result.model_dump_json(indent=2)}\n"
    if output_path.exists():
        if output_path.read_text(encoding="utf-8") != content:
            raise ValueError("existing projection artifact differs for the same dataset")
        return output_path
    output_path.write_text(content, encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    """Build the catalog-projection comparison command-line parser."""
    parser = argparse.ArgumentParser(
        description="Compare full catalog records with agent-facing projections."
    )
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Measure the authoritative catalog and write a reproducible result artifact."""
    arguments = build_parser().parse_args(argv)
    data_directory = cast("Path | None", arguments.data_dir) or load_catalog_directory()
    output_directory = cast(Path, arguments.output_dir)
    result = compare_catalog_projections(data_directory)
    output_path = write_comparison(result, output_directory)
    print(output_path.relative_to(REPOSITORY))
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ProjectionComparison",
    "compact_json_size",
    "compare_catalog_projections",
    "dataset_sha256",
    "write_comparison",
]
