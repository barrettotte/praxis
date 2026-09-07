"""Tests for reviewed project-recommendation regression gates."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from praxis.evaluation import regression
from praxis.evaluation.regression import (
    evaluate_regression,
    load_thresholds,
)
from praxis.evaluation.results import BaselineResult


@pytest.fixture
def result() -> BaselineResult:
    """Synthetic passing measurements; no recorded model output is a test dependency."""
    candidate = {
        "title": "Test project",
        "summary": "Test summary",
        "rationale": "Test rationale",
        "estimated_scope": "weekend",
        "technologies": ["Python"],
        "first_milestone": "Build a parser and test one input.",
        "evidence_citations": [
            {"evidence_id": "book:aaaaaaaaaaaaaaaa", "generated_connection": "Related resource"}
        ],
    }
    tokens = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    return BaselineResult.model_validate_json(
        json.dumps(
            {
                "suite": "project-recommendation-baseline",
                "result_version": 5,
                "prompts_version": 2,
                "expectations_version": 2,
                "metadata": {
                    "generated_at": "2026-01-01T00:00:00Z",
                    "model_id": "synthetic",
                    "region": "test",
                    "dataset": {"label": "synthetic", "record_count": 1, "sha256": "a" * 64},
                    "source": {
                        "git_revision": "a" * 40,
                        "working_tree_dirty": False,
                        "sha256": "b" * 64,
                    },
                },
                "summary": {
                    "case_count": 30,
                    "success_count": 30,
                    "expected_evidence_pass_count": 30,
                    "expected_trajectory_pass_count": 30,
                    "wall_latency_p50_ms": 1,
                    "wall_latency_p95_ms": 1,
                    "total_tokens": 60,
                    "total_local_tool_calls": 30,
                    "total_model_tool_calls": 30,
                    "average_retrieval_precision_at_k": 1.0,
                    "average_expected_evidence_coverage": 1.0,
                    "mean_reciprocal_rank": 1.0,
                    "citation_count": 90,
                    "resolved_citation_count": 90,
                    "citation_resolution_rate": 1.0,
                    "agentcore_evaluations": [
                        {
                            "evaluator_id": name,
                            "completed_case_count": 30,
                            "failed_case_count": 0,
                            "result_count": 30,
                            "score_count": 30,
                            "average_score": 1.0,
                            "token_usage": tokens,
                        }
                        for name in (
                            "Builtin.GoalSuccessRate",
                            "Builtin.Correctness",
                            "Builtin.ToolSelectionAccuracy",
                        )
                    ],
                },
                "cases": [
                    {
                        "case_id": f"synthetic-{i}",
                        "category": "straightforward",
                        "succeeded": True,
                        "candidates": {
                            "candidates": [
                                candidate | {"title": f"Test project {n}"} for n in range(3)
                            ]
                        },
                        "retrieved_evidence_ids": ["book:aaaaaaaaaaaaaaaa"],
                        "cited_evidence_ids": ["book:aaaaaaaaaaaaaaaa"],
                        "local_tool_calls": [{"tool": "search_catalog", "calls": 1}],
                        "model_tool_calls": [{"tool": "ProjectCandidateSet", "calls": 1}],
                        "wall_latency_ms": 1,
                        "model_latency_ms": 1,
                        "time_to_first_byte_ms": None,
                        "token_usage": tokens,
                        "cycle_count": 1,
                        "checks": {
                            "structured_output_valid": True,
                            "citation_ids_retrieved": True,
                            "expected_evidence_met": True,
                            "expected_trajectory_met": True,
                        },
                    }
                    for i in range(30)
                ],
            }
        )
    )


def test_passing_measurements_pass_gates(result: BaselineResult) -> None:
    report = evaluate_regression(result, load_thresholds())

    assert report.passed
    assert report.checks
    assert all(check.passed for check in report.checks)


@pytest.mark.parametrize(
    ("metric", "value"),
    [
        ("success_count", 26),
        ("citation_count", 80),
        ("citation_resolution_rate", 0.99),
        ("wall_latency_p50_ms", 40001),
        ("wall_latency_p95_ms", 50001),
        ("total_tokens", 120001),
    ],
)
def test_operational_and_citation_regressions_fail(
    result: BaselineResult, metric: str, value: float
) -> None:
    regressed = result.model_copy(
        update={"summary": result.summary.model_copy(update={metric: value})}
    )
    report = evaluate_regression(regressed, load_thresholds())
    assert not report.passed
    assert any(check.metric == metric and not check.passed for check in report.checks)


def test_diagnostic_scores_do_not_gate_results(result: BaselineResult) -> None:
    summary = result.summary.model_copy(
        update={
            "expected_evidence_pass_count": 0,
            "expected_trajectory_pass_count": 0,
            "average_retrieval_precision_at_k": 0.0,
            "average_expected_evidence_coverage": 0.0,
            "mean_reciprocal_rank": 0.0,
            "agentcore_evaluations": [
                evaluator.model_copy(update={"average_score": 0.0})
                for evaluator in result.summary.agentcore_evaluations
            ],
        }
    )
    assert evaluate_regression(
        result.model_copy(update={"summary": summary}), load_thresholds()
    ).passed
    assert evaluate_regression(
        result.model_copy(
            update={"summary": summary.model_copy(update={"agentcore_evaluations": []})}
        ),
        load_thresholds(),
    ).passed


@pytest.mark.parametrize("passes", [False, True])
def test_cli_labels_artifact_scope_without_claiming_current_quality(
    passes: bool, capsys: pytest.CaptureFixture[str], result: BaselineResult, tmp_path: Path
) -> None:
    if not passes:
        result = result.model_copy(
            update={"summary": result.summary.model_copy(update={"success_count": 0})}
        )
    with patch.object(regression, "load_result", return_value=result):
        status = regression.main([str(tmp_path / "result.json")])
    output = json.loads(capsys.readouterr().out)

    assert status == (0 if passes else 1)
    assert output["passed"] is passes
    assert output["scope"] == "recorded_evaluation_artifact"
    assert output["current_model_quality_verified"] is False
    assert output["result_path"] == str(tmp_path / "result.json")
    assert output["recorded_metadata"] == result.metadata.model_dump(mode="json")
