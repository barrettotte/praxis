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
    DatasetIdentity,
    EvaluationCaseResult,
    QualityResult,
    SourceIdentity,
    TokenUsageResult,
    ToolCallCount,
)

type PlanningInvoker = Callable[[str, InMemoryCatalog, AgentSettings | None], ProjectPlanningRun]

ACTION_WORDS = frozenset(
    {
        "build",
        "create",
        "display",
        "implement",
        "load",
        "parse",
        "produce",
        "render",
        "return",
        "run",
        "test",
        "write",
    }
)
DATASET_FILES = ("books.json", "projects.json", "bytes.json", "museum.json")
SOURCE_PATHS = (
    Path("backend/src/praxis"),
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


def _dataset_identity(directory: Path, catalog: InMemoryCatalog) -> DatasetIdentity:
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


def _source_identity(repository: Path) -> SourceIdentity:
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


def _concrete_milestones(run: ProjectPlanningRun) -> bool:
    for candidate in run.candidates.candidates:
        words = candidate.first_milestone.casefold().replace("-", " ").split()
        normalized_words = {word.strip(".,:;!?()[]{}") for word in words}
        if len(words) < 6 or not normalized_words & ACTION_WORDS:
            return False
    return True


def _quality(run: ProjectPlanningRun, expectation: CaseExpectation) -> QualityResult:
    cited_ids = {
        reference.evidence_id
        for candidate in run.candidates.candidates
        for reference in candidate.evidence
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
        _concrete_milestones(run),
    )
    return QualityResult(
        structured_output_valid=checks[0],
        citations_grounded=checks[1],
        expected_evidence_met=checks[2],
        expected_trajectory_met=checks[3],
        concrete_first_milestones=checks[4],
        score=sum(checks) / len(checks),
    )


def _failure_quality() -> QualityResult:
    return QualityResult(
        structured_output_valid=False,
        citations_grounded=False,
        expected_evidence_met=False,
        expected_trajectory_met=False,
        concrete_first_milestones=False,
        score=0.0,
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
            quality=_failure_quality(),
            error_type=type(error).__name__,
            error_message=str(error),
        )

    elapsed_ms = round((perf_counter() - started) * 1_000)
    metrics = run.generation_metrics
    cited_ids = sorted(
        {
            reference.evidence_id
            for candidate in run.candidates.candidates
            for reference in candidate.evidence
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
        quality=_quality(run, expectation),
    )


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _summary(results: list[EvaluationCaseResult]) -> BaselineSummary:
    return BaselineSummary(
        case_count=len(results),
        success_count=sum(result.succeeded for result in results),
        average_quality_score=sum(result.quality.score for result in results) / len(results),
        expected_evidence_pass_count=sum(
            result.quality.expected_evidence_met for result in results
        ),
        expected_trajectory_pass_count=sum(
            result.quality.expected_trajectory_met for result in results
        ),
        concrete_milestone_pass_count=sum(
            result.quality.concrete_first_milestones for result in results
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
    )


def run_baseline(
    evaluation_set: EvaluationSet,
    expectations: EvaluationExpectations,
    catalog: InMemoryCatalog,
    catalog_directory: Path,
    repository: Path,
    settings: AgentSettings,
    invoker: PlanningInvoker = invoke_project_candidates_with_trace,
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
        result_version=1,
        metadata=BaselineMetadata(
            generated_at=datetime.now(UTC),
            model_id=settings.model_id,
            region=settings.region,
            dataset=_dataset_identity(catalog_directory, catalog),
            source=_source_identity(repository),
        ),
        summary=_summary(results),
        cases=results,
    )


__all__ = ["PlanningInvoker", "run_baseline"]
