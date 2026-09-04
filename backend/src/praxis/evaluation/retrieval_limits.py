"""Compare catalog retrieval quality and context size across result limits."""

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from praxis.catalog import (
    CatalogSearchResult,
    InMemoryCatalog,
    SearchCatalogRequest,
    project_evidence,
    search_catalog,
)
from praxis.catalog.text import catalog_query
from praxis.config import load_catalog_directory
from praxis.evaluation.models import CaseExpectation, EvaluationExpectations, EvaluationSet
from praxis.evaluation.projections import compact_json_size, dataset_sha256
from praxis.evaluation.runner import measure_retrieval_relevance

REPOSITORY = Path(__file__).parents[4]
DEFAULT_PROMPTS = REPOSITORY / "evals" / "project-recommendations" / "prompts.json"
DEFAULT_EXPECTATIONS = REPOSITORY / "evals" / "project-recommendations" / "expectations.json"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY / "evals" / "retrieval-limits" / "results"
DEFAULT_LIMITS = (3, 5, 10, 20)
PRODUCTION_PREFETCH_LIMIT = 3


class RetrievalLimitModel(BaseModel):
    """Strict base contract for retrieval-limit measurement artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RetrievalCaseResult(RetrievalLimitModel):
    """Retrieval measurements for one prompt at one result limit."""

    case_id: str
    query: str
    returned_count: Annotated[int, Field(ge=0)]
    projected_response_bytes: Annotated[int, Field(ge=0)]
    retrieved_evidence_ids: list[str]
    matched_count: Annotated[int, Field(ge=0)]
    expected_evidence_met: bool
    precision_at_k: Annotated[float, Field(ge=0, le=1)]
    expected_evidence_coverage: Annotated[float, Field(ge=0, le=1)]
    reciprocal_rank: Annotated[float, Field(ge=0, le=1)]


class RetrievalLimitResult(RetrievalLimitModel):
    """Aggregate and auditable case results for one retrieval limit."""

    limit: Annotated[int, Field(ge=1, le=20)]
    case_count: Annotated[int, Field(ge=1)]
    nonempty_case_count: Annotated[int, Field(ge=0)]
    expected_evidence_pass_count: Annotated[int, Field(ge=0)]
    total_returned_count: Annotated[int, Field(ge=0)]
    total_projected_response_bytes: Annotated[int, Field(ge=0)]
    average_precision_at_k: Annotated[float, Field(ge=0, le=1)]
    average_expected_evidence_coverage: Annotated[float, Field(ge=0, le=1)]
    mean_reciprocal_rank: Annotated[float, Field(ge=0, le=1)]
    cases: list[RetrievalCaseResult]


class RetrievalLimitComparison(RetrievalLimitModel):
    """Reproducible retrieval tradeoff comparison for one input snapshot."""

    version: Annotated[int, Field(ge=1)]
    input_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    dataset_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    record_count: Annotated[int, Field(ge=1)]
    prompt_count: Annotated[int, Field(ge=1)]
    prompts_version: int
    expectations_version: int
    production_prefetch_limit: Annotated[int, Field(ge=1, le=20)]
    serialization: str
    limits: list[RetrievalLimitResult]


def _expected_evidence_met(evidence_ids: Sequence[str], expectation: CaseExpectation) -> bool:
    """Apply the curated minimum-match and required-kind rules to retrieval."""
    expected = {record.evidence_id: record.kind for record in expectation.evidence.any_of}
    matched = set(evidence_ids) & expected.keys()
    matched_kinds = {expected[evidence_id] for evidence_id in matched}
    return (
        len(matched) >= expectation.evidence.minimum_matches
        and set(expectation.evidence.required_kinds) <= matched_kinds
    )


def _response_payload(results: Sequence[CatalogSearchResult]) -> dict[str, object]:
    """Serialize the same projected search response emitted by the catalog Lambda."""
    projected = [{"score": result.score} | project_evidence(result.entry) for result in results]
    return {"operation": "search_catalog", "results": projected}


def _measure_limit(
    catalog: InMemoryCatalog,
    evaluation_set: EvaluationSet,
    expectations: Mapping[str, CaseExpectation],
    limit: int,
) -> RetrievalLimitResult:
    """Measure all canonical prompts at one result limit."""
    cases: list[RetrievalCaseResult] = []
    for case in evaluation_set.cases:
        query = catalog_query(case.prompt)
        results = search_catalog(catalog, SearchCatalogRequest(query=query, limit=limit))
        evidence_ids = [result.entry.id for result in results]
        expectation = expectations[case.id]
        relevance = measure_retrieval_relevance(evidence_ids, expectation)
        cases.append(
            RetrievalCaseResult(
                case_id=case.id,
                query=query,
                returned_count=len(results),
                projected_response_bytes=compact_json_size(_response_payload(results)),
                retrieved_evidence_ids=evidence_ids,
                matched_count=relevance.matched_count,
                expected_evidence_met=_expected_evidence_met(evidence_ids, expectation),
                precision_at_k=relevance.precision_at_k,
                expected_evidence_coverage=relevance.expected_evidence_coverage,
                reciprocal_rank=relevance.reciprocal_rank,
            )
        )
    case_count = len(cases)
    return RetrievalLimitResult(
        limit=limit,
        case_count=case_count,
        nonempty_case_count=sum(case.returned_count > 0 for case in cases),
        expected_evidence_pass_count=sum(case.expected_evidence_met for case in cases),
        total_returned_count=sum(case.returned_count for case in cases),
        total_projected_response_bytes=sum(case.projected_response_bytes for case in cases),
        average_precision_at_k=sum(case.precision_at_k for case in cases) / case_count,
        average_expected_evidence_coverage=(
            sum(case.expected_evidence_coverage for case in cases) / case_count
        ),
        mean_reciprocal_rank=sum(case.reciprocal_rank for case in cases) / case_count,
        cases=cases,
    )


def _input_sha256(
    dataset_hash: str,
    evaluation_set: EvaluationSet,
    expectations: EvaluationExpectations,
    limits: Sequence[int],
) -> str:
    """Identify the dataset, reviewed fixtures, limits, and comparison schema."""
    payload = {
        "dataset_sha256": dataset_hash,
        "evaluation_set": evaluation_set.model_dump(mode="json"),
        "expectations": expectations.model_dump(mode="json"),
        "limits": list(limits),
        "version": 1,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def compare_retrieval_limits(
    directory: Path,
    evaluation_set: EvaluationSet,
    expectations: EvaluationExpectations,
    limits: Sequence[int] = DEFAULT_LIMITS,
) -> RetrievalLimitComparison:
    """Compare deterministic production retrieval over reviewed prompts and evidence."""
    normalized_limits = tuple(sorted(set(limits)))
    if not normalized_limits or normalized_limits != tuple(limits):
        raise ValueError("retrieval limits must be unique and increasing")
    if normalized_limits[0] < 1 or normalized_limits[-1] > 20:
        raise ValueError("retrieval limits must be between 1 and 20")
    case_ids = [case.id for case in evaluation_set.cases]
    expectation_ids = [expectation.case_id for expectation in expectations.expectations]
    if evaluation_set.suite != expectations.suite or case_ids != expectation_ids:
        raise ValueError("evaluation prompts and expectations must align")

    catalog = InMemoryCatalog.from_directory(directory)
    dataset_hash = dataset_sha256(directory)
    expectations_by_id = {
        expectation.case_id: expectation for expectation in expectations.expectations
    }
    return RetrievalLimitComparison(
        version=1,
        input_sha256=_input_sha256(dataset_hash, evaluation_set, expectations, normalized_limits),
        dataset_sha256=dataset_hash,
        record_count=len(catalog),
        prompt_count=len(evaluation_set.cases),
        prompts_version=evaluation_set.version,
        expectations_version=expectations.version,
        production_prefetch_limit=PRODUCTION_PREFETCH_LIMIT,
        serialization="compact sorted-key JSON catalog Lambda responses encoded as UTF-8",
        limits=[
            _measure_limit(catalog, evaluation_set, expectations_by_id, limit)
            for limit in normalized_limits
        ],
    )


def write_comparison(result: RetrievalLimitComparison, output_directory: Path) -> Path:
    """Write one content-addressed artifact without replacing prior measurements."""
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"retrieval-limits-{result.input_sha256[:12]}.json"
    content = f"{result.model_dump_json(indent=2)}\n"
    if output_path.exists():
        if output_path.read_text(encoding="utf-8") != content:
            raise ValueError("existing retrieval-limit artifact differs for the same inputs")
        return output_path
    output_path.write_text(content, encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    """Build the retrieval-limit comparison command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--expectations", type=Path, default=DEFAULT_EXPECTATIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--limits", nargs="+", type=int, default=list(DEFAULT_LIMITS))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the comparison and write its reproducible result artifact."""
    arguments = build_parser().parse_args(argv)
    directory = cast("Path | None", arguments.data_dir) or load_catalog_directory()
    evaluation_set = EvaluationSet.model_validate_json(cast(Path, arguments.prompts).read_bytes())
    expectations = TypeAdapter(EvaluationExpectations).validate_json(
        cast(Path, arguments.expectations).read_bytes()
    )
    result = compare_retrieval_limits(
        directory,
        evaluation_set,
        expectations,
        cast("list[int]", arguments.limits),
    )
    output_path = write_comparison(result, cast(Path, arguments.output_dir))
    print(output_path.relative_to(REPOSITORY))
    print(result.model_dump_json(indent=2, exclude={"limits": {"__all__": {"cases"}}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RetrievalLimitComparison", "compare_retrieval_limits", "write_comparison"]
