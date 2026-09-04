"""Tests for reviewed project-recommendation regression gates."""

from praxis.evaluation.regression import (
    REPOSITORY,
    evaluate_regression,
    load_result,
    load_thresholds,
)

VERIFIED_PRO_BASELINE = (
    REPOSITORY
    / "evals"
    / "project-recommendations"
    / "results"
    / "agentcore-v46-20260904T175002Z.json"
)


def test_verified_pro_baseline_passes_regression_gates() -> None:
    report = evaluate_regression(load_result(VERIFIED_PRO_BASELINE), load_thresholds())

    assert report.passed
    assert report.checks
    assert all(check.passed for check in report.checks)


def test_quality_regression_fails_report() -> None:
    result = load_result(VERIFIED_PRO_BASELINE)
    regressed = result.model_copy(
        update={"summary": result.summary.model_copy(update={"average_quality_score": 0.49})}
    )

    report = evaluate_regression(regressed, load_thresholds())

    assert not report.passed
    assert any(
        check.metric == "average_quality_score" and not check.passed for check in report.checks
    )


def test_missing_managed_evaluator_fails_report() -> None:
    result = load_result(VERIFIED_PRO_BASELINE)
    regressed = result.model_copy(
        update={"summary": result.summary.model_copy(update={"agentcore_evaluations": []})}
    )

    report = evaluate_regression(regressed, load_thresholds())

    assert not report.passed
    assert any(check.metric.endswith(".present") and not check.passed for check in report.checks)
