"""Tests for deterministic retrieval-limit comparisons."""

from pathlib import Path

import pytest

from praxis.evaluation.models import (
    CaseExpectation,
    EvaluationCase,
    EvaluationExpectations,
    EvaluationSet,
    EvidenceExpectation,
    ExpectedEvidenceRecord,
    ExpectedToolCall,
)
from praxis.evaluation.retrieval_limits import compare_retrieval_limits, write_comparison

REPOSITORY = Path(__file__).parents[2]
FIXTURE_DIRECTORY = REPOSITORY / "data" / "fixtures"
SUFFIXES = (
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
)


def evaluation_inputs() -> tuple[EvaluationSet, EvaluationExpectations]:
    """Build the minimum valid suite around a known fixture search result."""
    cases = [
        EvaluationCase(
            id=f"project-{index:02d}-limit-{suffix}",
            prompt=f"Find the example catalog item {suffix}",
            category="straightforward",
            tags=["retrieval-limit"],
        )
        for index, suffix in enumerate(SUFFIXES, start=1)
    ]
    expectations = [
        CaseExpectation(
            case_id=case.id,
            evidence=EvidenceExpectation(
                any_of=[
                    ExpectedEvidenceRecord(
                        evidence_id="museum:672644138e538185",
                        kind="museum",
                        label="Example Computer",
                    )
                ],
                required_kinds=["museum"],
            ),
            trajectory=[ExpectedToolCall(tool="search_catalog", minimum_calls=1, maximum_calls=1)],
        )
        for case in cases
    ]
    return (
        EvaluationSet(suite="project-recommendation-baseline", version=1, cases=cases),
        EvaluationExpectations(
            suite="project-recommendation-baseline",
            prompts_version=1,
            version=1,
            expectations=expectations,
        ),
    )


def test_compare_retrieval_limits_measures_quality_and_payload_growth() -> None:
    evaluation_set, expectations = evaluation_inputs()

    result = compare_retrieval_limits(
        FIXTURE_DIRECTORY,
        evaluation_set,
        expectations,
        limits=(1, 3),
    )

    one, three = result.limits
    assert result.prompt_count == 10
    assert [item.limit for item in result.limits] == [1, 3]
    assert one.expected_evidence_pass_count == three.expected_evidence_pass_count == 10
    assert one.mean_reciprocal_rank == three.mean_reciprocal_rank == 1.0
    assert one.total_returned_count < three.total_returned_count
    assert one.total_projected_response_bytes < three.total_projected_response_bytes


def test_retrieval_limits_require_unique_increasing_values() -> None:
    evaluation_set, expectations = evaluation_inputs()

    with pytest.raises(ValueError, match="unique and increasing"):
        compare_retrieval_limits(
            FIXTURE_DIRECTORY,
            evaluation_set,
            expectations,
            limits=(3, 1, 3),
        )


def test_write_retrieval_comparison_is_content_addressed(tmp_path: Path) -> None:
    evaluation_set, expectations = evaluation_inputs()
    result = compare_retrieval_limits(
        FIXTURE_DIRECTORY,
        evaluation_set,
        expectations,
        limits=(1,),
    )

    output_path = write_comparison(result, tmp_path)

    assert output_path.name == f"retrieval-limits-{result.input_sha256[:12]}.json"
    assert write_comparison(result, tmp_path) == output_path
