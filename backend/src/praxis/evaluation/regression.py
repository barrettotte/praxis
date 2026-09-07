"""Check a sanitized evaluation artifact against reviewed regression gates."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, Self, cast

from pydantic import Field, ValidationError, model_validator

from praxis.evaluation.models import EvaluationModel
from praxis.evaluation.results import BaselineResult

REPOSITORY = Path(__file__).parents[4]
DEFAULT_THRESHOLDS = REPOSITORY / "evals" / "project-recommendations" / "regression-thresholds.json"


class RegressionThresholds(EvaluationModel):
    """Versioned gates for a complete project-recommendation evaluation."""

    suite: Literal["project-recommendation-regression-thresholds"]
    version: Literal[3]
    prompts_version: Literal[2]
    expectations_version: Literal[2]
    required_case_count: Literal[30]
    minimum_success_count: Annotated[int, Field(ge=1, le=30)]
    minimum_citation_count: Annotated[int, Field(ge=1)]
    minimum_citation_resolution_rate: Annotated[float, Field(ge=0, le=1)]
    maximum_wall_latency_p50_ms: Annotated[int, Field(ge=1)]
    maximum_wall_latency_p95_ms: Annotated[int, Field(ge=1)]
    maximum_total_tokens: Annotated[int, Field(ge=1)]
    maximum_tokens_per_success: Annotated[float, Field(gt=0)]

    @model_validator(mode="after")
    def require_consistent_thresholds(self) -> Self:
        """Reject internally inconsistent operational limits."""
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
            "citation_count",
            summary.citation_count,
            ">=",
            thresholds.minimum_citation_count,
        ),
        _check(
            "citation_resolution_rate",
            summary.citation_resolution_rate,
            ">=",
            thresholds.minimum_citation_resolution_rate,
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
    print(
        json.dumps(
            {
                "scope": "recorded_evaluation_artifact",
                "current_model_quality_verified": False,
                "result_path": str(arguments.result),
                "thresholds_path": str(arguments.thresholds),
                "recorded_metadata": result.metadata.model_dump(mode="json"),
                **report.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
