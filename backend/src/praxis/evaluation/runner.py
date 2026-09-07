"""Run and score the repeatable local candidate baseline."""

import hashlib
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from time import perf_counter

from praxis.agent.planner import ProjectPlanningRun, invoke_project_candidates_with_trace
from praxis.catalog import InMemoryCatalog
from praxis.config import AgentSettings
from praxis.evaluation.models import (
    CaseExpectation,
    EvaluationCategory,
    EvaluationExpectations,
    EvaluationSet,
)
from praxis.evaluation.results import (
    BaselineMetadata,
    BaselineResult,
    BaselineSummary,
    CitationResolutionResult,
    DatasetIdentity,
    DeploymentIdentity,
    EvaluationCaseResult,
    MechanicalChecks,
    RetrievalRelevanceResult,
    SourceIdentity,
    TokenUsageResult,
    ToolCallCount,
)

type PlanningInvoker = Callable[[str, InMemoryCatalog, AgentSettings | None], ProjectPlanningRun]

DATASET_FILES = ("books.json", "projects.json", "bytes.json", "museum.json")
SOURCE_PATHS = (
    Path("backend/src/praxis"),
    Path("evals/project-recommendations/business-assertions.json"),
    Path("evals/project-recommendations/prompts.json"),
    Path("evals/project-recommendations/expectations.json"),
    Path("pyproject.toml"),
    Path("uv.lock"),
)


def _hash_files(files: Iterable[Path], *, relative_to: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        relative_path = path.relative_to(relative_to)
        digest.update(relative_path.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def dataset_identity(directory: Path, catalog: InMemoryCatalog) -> DatasetIdentity:
    """Identify the exact authoritative catalog used by an evaluation."""
    paths = [directory / name for name in DATASET_FILES]
    return DatasetIdentity(
        label="authoritative-sibling-catalog",
        record_count=len(catalog),
        sha256=_hash_files(paths, relative_to=directory),
    )


def _source_files(repository: Path) -> list[Path]:
    files: list[Path] = []
    for source_path in SOURCE_PATHS:
        path = repository / source_path
        if path.is_dir():
            files.extend(candidate for candidate in path.rglob("*.py") if candidate.is_file())
        elif path.is_file():
            files.append(path)
    return files


def _git_output(repository: Path, *arguments: str) -> str:
    git = shutil.which("git")
    if git is None:
        message = "git is required to identify the evaluated source"
        raise RuntimeError(message)
    completed = subprocess.run(  # noqa: S603
        (git, *arguments),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def source_identity(repository: Path) -> SourceIdentity:
    """Identify the repository revision and evaluation-relevant source content."""
    revision = _git_output(repository, "rev-parse", "HEAD")
    dirty = bool(_git_output(repository, "status", "--short", "--untracked-files=all"))
    return SourceIdentity(
        git_revision=revision,
        working_tree_dirty=dirty,
        sha256=_hash_files(_source_files(repository), relative_to=repository),
    )


def _tool_counts(names: Iterable[str]) -> list[ToolCallCount]:
    return [ToolCallCount(tool=name, calls=count) for name, count in sorted(Counter(names).items())]


def _trajectory_met(expectation: CaseExpectation, observed: Iterable[str]) -> bool:
    counts = Counter(observed)
    expected_tools = {call.tool for call in expectation.trajectory}
    return set(counts) <= expected_tools and all(
        call.minimum_calls <= counts[call.tool] <= call.maximum_calls
        for call in expectation.trajectory
    )


def _mechanical_checks(run: ProjectPlanningRun, expectation: CaseExpectation) -> MechanicalChecks:
    cited_ids = {
        reference.evidence_id
        for candidate in run.candidates.candidates
        for reference in candidate.evidence_citations
    }
    expected_records = {record.evidence_id: record.kind for record in expectation.evidence.any_of}
    matched_ids = cited_ids & expected_records.keys()
    matched_kinds = {expected_records[evidence_id] for evidence_id in matched_ids}
    expected_evidence_met = (
        len(matched_ids) >= expectation.evidence.minimum_matches
        and set(expectation.evidence.required_kinds) <= matched_kinds
    )
    checks = (
        True,
        cited_ids <= set(run.retrieved_evidence_ids),
        expected_evidence_met,
        _trajectory_met(expectation, run.local_tool_calls),
    )
    return MechanicalChecks(
        structured_output_valid=checks[0],
        citation_ids_retrieved=checks[1],
        expected_evidence_met=checks[2],
        expected_trajectory_met=checks[3],
    )


def _failed_checks() -> MechanicalChecks:
    return MechanicalChecks(
        structured_output_valid=False,
        citation_ids_retrieved=False,
        expected_evidence_met=False,
        expected_trajectory_met=False,
    )


def measure_retrieval_relevance(
    retrieved_evidence_ids: Iterable[str],
    expectation: CaseExpectation,
) -> RetrievalRelevanceResult:
    """Measure ranked retrieval against the case's curated relevant records."""
    retrieved = list(retrieved_evidence_ids)
    relevant = {record.evidence_id for record in expectation.evidence.any_of}
    matched = relevant & set(retrieved)
    first_relevant_rank = next(
        (rank for rank, evidence_id in enumerate(retrieved, start=1) if evidence_id in relevant),
        None,
    )
    return RetrievalRelevanceResult(
        retrieved_count=len(retrieved),
        curated_relevant_count=len(relevant),
        matched_count=len(matched),
        precision_at_k=len(matched) / len(retrieved) if retrieved else 0.0,
        expected_evidence_coverage=len(matched) / len(relevant),
        reciprocal_rank=1 / first_relevant_rank if first_relevant_rank is not None else 0.0,
    )


def measure_citation_resolution(
    run: ProjectPlanningRun,
) -> CitationResolutionResult:
    """Measure ID membership in retrieval, not whether sources support generated claims."""
    citations = [
        citation
        for candidate in run.candidates.candidates
        for citation in candidate.evidence_citations
    ]
    retrieved = set(run.retrieved_evidence_ids)
    resolved_count = sum(citation.evidence_id in retrieved for citation in citations)
    citation_count = len(citations)
    unsupported_count = citation_count - resolved_count
    return CitationResolutionResult(
        citation_count=citation_count,
        resolved_citation_count=resolved_count,
        unresolved_citation_count=unsupported_count,
        citation_resolution_rate=resolved_count / citation_count if citation_count else 0.0,
    )


def _run_case(
    prompt: str,
    case_id: str,
    category: EvaluationCategory,
    expectation: CaseExpectation,
    catalog: InMemoryCatalog,
    settings: AgentSettings,
    invoker: PlanningInvoker,
) -> EvaluationCaseResult:
    started = perf_counter()
    try:
        run = invoker(prompt, catalog, settings)
    except Exception as error:  # Evaluation must preserve failures and continue the suite.
        elapsed_ms = round((perf_counter() - started) * 1_000)
        return EvaluationCaseResult(
            case_id=case_id,
            category=category,
            succeeded=False,
            candidates=None,
            retrieved_evidence_ids=[],
            cited_evidence_ids=[],
            local_tool_calls=[],
            model_tool_calls=[],
            wall_latency_ms=elapsed_ms,
            model_latency_ms=None,
            time_to_first_byte_ms=None,
            token_usage=None,
            cycle_count=None,
            checks=_failed_checks(),
            retrieval_relevance=None,
            citation_resolution=None,
            error_type=type(error).__name__,
            error_message=str(error),
        )

    elapsed_ms = round((perf_counter() - started) * 1_000)
    metrics = run.generation_metrics
    cited_ids = sorted(
        {
            reference.evidence_id
            for candidate in run.candidates.candidates
            for reference in candidate.evidence_citations
        }
    )
    return EvaluationCaseResult(
        case_id=case_id,
        category=category,
        succeeded=True,
        candidates=run.candidates,
        retrieved_evidence_ids=list(run.retrieved_evidence_ids),
        cited_evidence_ids=cited_ids,
        local_tool_calls=_tool_counts(run.local_tool_calls),
        model_tool_calls=(
            [ToolCallCount(tool=name, calls=count) for name, count in metrics.model_tool_calls]
            if metrics
            else []
        ),
        wall_latency_ms=elapsed_ms,
        model_latency_ms=metrics.model_latency_ms if metrics else None,
        time_to_first_byte_ms=metrics.time_to_first_byte_ms if metrics else None,
        token_usage=(
            TokenUsageResult(
                input_tokens=metrics.token_usage.input_tokens,
                output_tokens=metrics.token_usage.output_tokens,
                total_tokens=metrics.token_usage.total_tokens,
                cache_read_input_tokens=metrics.token_usage.cache_read_input_tokens,
                cache_write_input_tokens=metrics.token_usage.cache_write_input_tokens,
            )
            if metrics
            else None
        ),
        cycle_count=metrics.cycle_count if metrics else None,
        checks=_mechanical_checks(run, expectation),
        retrieval_relevance=measure_retrieval_relevance(run.retrieved_evidence_ids, expectation),
        citation_resolution=measure_citation_resolution(run),
    )


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _summary(results: list[EvaluationCaseResult]) -> BaselineSummary:
    retrieval_results = [
        result.retrieval_relevance for result in results if result.retrieval_relevance is not None
    ]
    citation_results = [
        result.citation_resolution for result in results if result.citation_resolution is not None
    ]
    citation_count = sum(result.citation_count for result in citation_results)
    resolved_citation_count = sum(result.resolved_citation_count for result in citation_results)
    unresolved_citation_count = sum(result.unresolved_citation_count for result in citation_results)
    return BaselineSummary(
        case_count=len(results),
        success_count=sum(result.succeeded for result in results),
        expected_evidence_pass_count=sum(result.checks.expected_evidence_met for result in results),
        expected_trajectory_pass_count=sum(
            result.checks.expected_trajectory_met for result in results
        ),
        wall_latency_p50_ms=_percentile([result.wall_latency_ms for result in results], 0.5),
        wall_latency_p95_ms=_percentile([result.wall_latency_ms for result in results], 0.95),
        total_tokens=sum(
            result.token_usage.total_tokens for result in results if result.token_usage
        ),
        total_local_tool_calls=sum(
            call.calls for result in results for call in result.local_tool_calls
        ),
        total_model_tool_calls=sum(
            call.calls for result in results for call in result.model_tool_calls
        ),
        average_retrieval_precision_at_k=(
            sum(result.precision_at_k for result in retrieval_results) / len(results)
        ),
        average_expected_evidence_coverage=(
            sum(result.expected_evidence_coverage for result in retrieval_results) / len(results)
        ),
        mean_reciprocal_rank=(
            sum(result.reciprocal_rank for result in retrieval_results) / len(results)
        ),
        citation_count=citation_count,
        resolved_citation_count=resolved_citation_count,
        unresolved_citation_count=unresolved_citation_count,
        citation_resolution_rate=(
            resolved_citation_count / citation_count if citation_count else 0.0
        ),
    )


def run_baseline(
    evaluation_set: EvaluationSet,
    expectations: EvaluationExpectations,
    catalog: InMemoryCatalog,
    catalog_directory: Path,
    repository: Path,
    settings: AgentSettings,
    invoker: PlanningInvoker = invoke_project_candidates_with_trace,
    deployment: DeploymentIdentity | None = None,
) -> BaselineResult:
    """Run all cases independently and return a versioned measurement artifact."""
    expectations_by_id = {
        expectation.case_id: expectation for expectation in expectations.expectations
    }
    results: list[EvaluationCaseResult] = []
    for index, case in enumerate(evaluation_set.cases, start=1):
        print(f"[{index}/{len(evaluation_set.cases)}] {case.id}", file=sys.stderr, flush=True)
        results.append(
            _run_case(
                case.prompt,
                case.id,
                case.category,
                expectations_by_id[case.id],
                catalog,
                settings,
                invoker,
            )
        )
    return BaselineResult(
        suite=evaluation_set.suite,
        prompts_version=evaluation_set.version,
        expectations_version=expectations.version,
        result_version=5,
        metadata=BaselineMetadata(
            generated_at=datetime.now(UTC),
            model_id=settings.model_id,
            region=settings.region,
            dataset=dataset_identity(catalog_directory, catalog),
            source=source_identity(repository),
            deployment=deployment,
        ),
        summary=_summary(results),
        cases=results,
    )


__all__ = [
    "PlanningInvoker",
    "dataset_identity",
    "measure_citation_resolution",
    "measure_retrieval_relevance",
    "run_baseline",
    "source_identity",
]
