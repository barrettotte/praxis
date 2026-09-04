"""Tests for full-record and agent-projection size comparisons."""

from pathlib import Path

from praxis.evaluation.projections import compare_catalog_projections, write_comparison

REPOSITORY = Path(__file__).parents[2]
FIXTURE_DIRECTORY = REPOSITORY / "data" / "fixtures"


def test_compare_catalog_projections_measures_every_kind() -> None:
    result = compare_catalog_projections(FIXTURE_DIRECTORY)

    assert result.record_count == 8
    assert set(result.kinds) == {"book", "byte", "museum", "project"}
    assert all(kind.record_count == 2 for kind in result.kinds.values())
    assert result.full_record_bytes == sum(kind.full_record_bytes for kind in result.kinds.values())
    assert result.projected_record_bytes == sum(
        kind.projected_record_bytes for kind in result.kinds.values()
    )
    assert result.projected_record_bytes < result.full_record_bytes
    assert result.bytes_saved == result.full_record_bytes - result.projected_record_bytes
    assert {"isbn10", "isbn13", "language", "lccn"} <= set(result.kinds["book"].omitted_fields)
    assert {"deployUrl", "featured", "hidden", "image", "url"} <= set(
        result.kinds["project"].omitted_fields
    )
    assert {"image", "id"} <= set(result.kinds["museum"].omitted_fields)


def test_write_comparison_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    result = compare_catalog_projections(FIXTURE_DIRECTORY)

    first = write_comparison(result, tmp_path)
    second = write_comparison(result, tmp_path)

    assert first == second
    assert first.name == f"catalog-projections-{result.dataset_sha256[:12]}.json"
    assert first.read_text().endswith("\n")
