"""Check a sanitized evaluation artifact against reviewed regression gates."""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, Self, cast

from pydantic import Field, ValidationError, model_validator

from praxis.evaluation.models import EvaluationModel
from praxis.evaluation.results import AgentCoreEvaluatorId, BaselineResult

REPOSITORY = Path(__file__).parents[4]
DEFAULT_THRESHOLDS = REPOSITORY / "evals" / "project-recommendations" / "regression-thresholds.json"


class EvaluatorThreshold(EvaluationModel):
    """Required coverage and score for one managed evaluator."""

    evaluator_id: AgentCoreEvaluatorId
    minimum_completed_case_count: Annotated[int, Field(ge=1)]
    maximum_failed_case_count: Annotated[int, Field(ge=0)]
    minimum_average_score: Annotated[float, Field(ge=0, le=1)]


class RegressionThresholds(EvaluationModel):
    """Versioned gates for a complete project-recommendation evaluation."""

    suite: Literal["project-recommendation-regression-thresholds"]
    version: Literal[1]
    prompts_version: Literal[2]
    expectations_version: Literal[2]
    required_case_count: Literal[30]
    minimum_success_count: Annotated[int, Field(ge=1, le=30)]
    minimum_average_quality_score: Annotated[float, Field(ge=0, le=1)]
    minimum_expected_evidence_pass_count: Annotated[int, Field(ge=0, le=30)]
    minimum_expected_trajectory_pass_count: Annotated[int, Field(ge=0, le=30)]
    minimum_concrete_milestone_pass_count: Annotated[int, Field(ge=0, le=30)]
    minimum_retrieval_precision_at_k: Annotated[float, Field(ge=0, le=1)]
    minimum_expected_evidence_coverage: Annotated[float, Field(ge=0, le=1)]
    minimum_mean_reciprocal_rank: Annotated[float, Field(ge=0, le=1)]
    minimum_citation_claim_count: Annotated[int, Field(ge=1)]
    minimum_citation_correctness_rate: Annotated[float, Field(ge=0, le=1)]
    maximum_unsupported_claim_rate: Annotated[float, Field(ge=0, le=1)]
    maximum_wall_latency_p50_ms: Annotated[int, Field(ge=1)]
    maximum_wall_latency_p95_ms: Annotated[int, Field(ge=1)]
    maximum_total_tokens: Annotated[int, Field(ge=1)]
    maximum_tokens_per_success: Annotated[float, Field(gt=0)]
    evaluator_thresholds: Annotated[list[EvaluatorThreshold], Field(min_length=1)]

    @model_validator(mode="after")
    def require_consistent_thresholds(self) -> Self:
        """Reject internally inconsistent or duplicate gates."""
        evaluator_ids = [threshold.evaluator_id for threshold in self.evaluator_thresholds]
        if len(evaluator_ids) != len(set(evaluator_ids)):
            raise ValueError("managed evaluator thresholds must be unique")
        if self.maximum_wall_latency_p50_ms > self.maximum_wall_latency_p95_ms:
            raise ValueError("p50 latency threshold must not exceed p95")
        return self


class RegressionCheck(EvaluationModel):
    """One evaluated regression constraint."""

    metric: str
    actual: float
    operator: Literal["==", ">=", "<="]
    threshold: float
    passed: bool


class RegressionReport(EvaluationModel):
    """Machine-readable result of applying every reviewed gate."""

    passed: bool
    checks: list[RegressionCheck]


def _check(
    metric: str, actual: float, operator: Literal["==", ">=", "<="], threshold: float
) -> RegressionCheck:
    """Evaluate one numeric constraint."""
    comparisons = {
        "==": actual == threshold,
        ">=": actual >= threshold,
        "<=": actual <= threshold,
    }
    return RegressionCheck(
        metric=metric,
        actual=actual,
        operator=operator,
        threshold=threshold,
        passed=comparisons[operator],
    )


def evaluate_regression(
    result: BaselineResult,
    thresholds: RegressionThresholds,
) -> RegressionReport:
    """Apply every threshold without invoking a model or external service."""
    summary = result.summary
    checks = [
        _check("prompts_version", result.prompts_version, "==", thresholds.prompts_version),
        _check(
            "expectations_version",
            result.expectations_version,
            "==",
            thresholds.expectations_version,
        ),
        _check("case_count", summary.case_count, "==", thresholds.required_case_count),
        _check("success_count", summary.success_count, ">=", thresholds.minimum_success_count),
        _check(
            "average_quality_score",
            summary.average_quality_score,
            ">=",
            thresholds.minimum_average_quality_score,
        ),
        _check(
            "expected_evidence_pass_count",
            summary.expected_evidence_pass_count,
            ">=",
            thresholds.minimum_expected_evidence_pass_count,
        ),
        _check(
            "expected_trajectory_pass_count",
            summary.expected_trajectory_pass_count,
            ">=",
            thresholds.minimum_expected_trajectory_pass_count,
        ),
        _check(
            "concrete_milestone_pass_count",
            summary.concrete_milestone_pass_count,
            ">=",
            thresholds.minimum_concrete_milestone_pass_count,
        ),
        _check(
            "average_retrieval_precision_at_k",
            summary.average_retrieval_precision_at_k,
            ">=",
            thresholds.minimum_retrieval_precision_at_k,
        ),
        _check(
            "average_expected_evidence_coverage",
            summary.average_expected_evidence_coverage,
            ">=",
            thresholds.minimum_expected_evidence_coverage,
        ),
        _check(
            "mean_reciprocal_rank",
            summary.mean_reciprocal_rank,
            ">=",
            thresholds.minimum_mean_reciprocal_rank,
        ),
        _check(
            "citation_claim_count",
            summary.citation_claim_count,
            ">=",
            thresholds.minimum_citation_claim_count,
        ),
        _check(
            "citation_correctness_rate",
            summary.citation_correctness_rate,
            ">=",
            thresholds.minimum_citation_correctness_rate,
        ),
        _check(
            "unsupported_claim_rate",
            summary.unsupported_claim_rate,
            "<=",
            thresholds.maximum_unsupported_claim_rate,
        ),
        _check(
            "wall_latency_p50_ms",
            summary.wall_latency_p50_ms,
            "<=",
            thresholds.maximum_wall_latency_p50_ms,
        ),
        _check(
            "wall_latency_p95_ms",
            summary.wall_latency_p95_ms,
            "<=",
            thresholds.maximum_wall_latency_p95_ms,
        ),
        _check(
            "total_tokens",
            summary.total_tokens,
            "<=",
            thresholds.maximum_total_tokens,
        ),
        _check(
            "tokens_per_success",
            summary.total_tokens / max(summary.success_count, 1),
            "<=",
            thresholds.maximum_tokens_per_success,
        ),
    ]

    evaluator_summaries = {
        evaluator.evaluator_id: evaluator for evaluator in summary.agentcore_evaluations
    }
    for threshold in thresholds.evaluator_thresholds:
        prefix = f"agentcore.{threshold.evaluator_id}"
        evaluator = evaluator_summaries.get(threshold.evaluator_id)
        checks.append(_check(f"{prefix}.present", float(evaluator is not None), "==", 1))
        if evaluator is None:
            continue
        checks.extend(
            [
                _check(
                    f"{prefix}.completed_case_count",
                    evaluator.completed_case_count,
                    ">=",
                    threshold.minimum_completed_case_count,
                ),
                _check(
                    f"{prefix}.failed_case_count",
                    evaluator.failed_case_count,
                    "<=",
                    threshold.maximum_failed_case_count,
                ),
                _check(
                    f"{prefix}.average_score",
                    evaluator.average_score or 0,
                    ">=",
                    threshold.minimum_average_score,
                ),
            ]
        )

    return RegressionReport(passed=all(check.passed for check in checks), checks=checks)


def load_result(path: Path) -> BaselineResult:
    """Load and validate one sanitized baseline result artifact."""
    return BaselineResult.model_validate_json(path.read_bytes())


def load_thresholds(path: Path = DEFAULT_THRESHOLDS) -> RegressionThresholds:
    """Load and validate the reviewed threshold policy."""
    return RegressionThresholds.model_validate_json(path.read_bytes())


def build_parser() -> argparse.ArgumentParser:
    """Build the offline regression-check parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate an artifact, print every gate, and fail on regressions."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        result = load_result(cast(Path, arguments.result))
        thresholds = load_thresholds(cast(Path, arguments.thresholds))
    except (OSError, ValidationError) as error:
        parser.error(str(error))
    report = evaluate_regression(result, thresholds)
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
