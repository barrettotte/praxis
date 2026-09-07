"""Run the project-recommendation evaluation against AgentCore Runtime."""

import argparse
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import TypeAdapter

from praxis.agent.planner import CandidateGenerationMetrics, ProjectPlanningRun, TokenUsage
from praxis.agent.runtime_smoke import (
    LogsClient,
    RuntimeClient,
    RuntimeTraceResult,
    RuntimeTraceSpan,
    create_logs_client,
    create_runtime_client,
    invoke_runtime_endpoint,
    runtime_trace_log_group,
    wait_for_runtime_traces,
)
from praxis.catalog import InMemoryCatalog
from praxis.config import AgentSettings, load_catalog_directory
from praxis.evaluation.agentcore import (
    MANAGED_EVALUATORS,
    AgentCoreEvaluationClient,
    evaluate_runtime_trace,
)
from praxis.evaluation.models import (
    EvaluationBusinessAssertions,
    EvaluationExpectations,
    EvaluationSet,
)
from praxis.evaluation.results import (
    AgentCoreEvaluationResult,
    AgentCoreEvaluatorSummary,
    BaselineResult,
    DeploymentIdentity,
    EvaluationCaseResult,
    TokenUsageResult,
)
from praxis.evaluation.runner import run_baseline

REPOSITORY = Path(__file__).parents[4]
DEFAULT_PROMPTS = REPOSITORY / "evals" / "project-recommendations" / "prompts.json"
DEFAULT_EXPECTATIONS = REPOSITORY / "evals" / "project-recommendations" / "expectations.json"
DEFAULT_BUSINESS_ASSERTIONS = (
    REPOSITORY / "evals" / "project-recommendations" / "business-assertions.json"
)
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY / "build" / "evals"
GATEWAY_TOOL_ALIASES = {"summarize_experience": "compare_project_history"}


def _empty_assertions() -> dict[str, tuple[str, ...]]:
    return {}


def _empty_evaluations() -> dict[str, tuple[AgentCoreEvaluationResult, ...]]:
    return {}


class RuntimeEvaluationError(RuntimeError):
    """Raised when Runtime telemetry cannot produce comparable evaluation metrics."""


def _integer_attribute(span: RuntimeTraceSpan, name: str) -> int | None:
    """Read one non-boolean integer span attribute."""
    value = span.attributes.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def trace_generation_metrics(trace: RuntimeTraceResult) -> CandidateGenerationMetrics:
    """Convert correlated Strands spans into the local baseline metric contract."""
    strands_spans = tuple(
        span for span in trace.spans if span.scope.name == "strands.telemetry.tracer"
    )
    agent_spans = tuple(
        span
        for span in strands_spans
        if span.attributes.get("gen_ai.operation.name") == "invoke_agent"
    )
    if len(agent_spans) != 1:
        raise RuntimeEvaluationError("Runtime trace must contain exactly one Strands agent span")
    agent_span = agent_spans[0]
    input_tokens = _integer_attribute(agent_span, "gen_ai.usage.input_tokens")
    output_tokens = _integer_attribute(agent_span, "gen_ai.usage.output_tokens")
    total_tokens = _integer_attribute(agent_span, "gen_ai.usage.total_tokens")
    if input_tokens is None or output_tokens is None or total_tokens is None:
        raise RuntimeEvaluationError("Runtime agent span is missing token usage")

    model_latency_ms = 0
    model_tool_names: list[str] = []
    cycle_count = 0
    time_to_first_byte_ms: int | None = None
    for span in strands_spans:
        operation = span.attributes.get("gen_ai.operation.name")
        if operation == "chat":
            request_duration = _integer_attribute(span, "gen_ai.server.request.duration")
            if request_duration is not None:
                model_latency_ms += request_duration
            elif span.duration_nano is not None:
                model_latency_ms += round(span.duration_nano / 1_000_000)
            if time_to_first_byte_ms is None:
                time_to_first_byte_ms = _integer_attribute(
                    span, "gen_ai.server.time_to_first_token"
                )
        elif operation == "execute_tool":
            tool_name = span.attributes.get("gen_ai.tool.name")
            if isinstance(tool_name, str):
                model_tool_names.append(tool_name)
        elif operation == "execute_event_loop_cycle":
            cycle_count += 1

    if model_latency_ms == 0 or cycle_count == 0:
        raise RuntimeEvaluationError("Runtime trace is missing Strands latency or cycle metrics")
    model_tool_calls = tuple(sorted(Counter(model_tool_names).items()))
    return CandidateGenerationMetrics(
        token_usage=TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cache_read_input_tokens=(
                _integer_attribute(agent_span, "gen_ai.usage.cache_read_input_tokens") or 0
            ),
            cache_write_input_tokens=(
                _integer_attribute(agent_span, "gen_ai.usage.cache_write_input_tokens") or 0
            ),
        ),
        model_latency_ms=model_latency_ms,
        time_to_first_byte_ms=time_to_first_byte_ms,
        model_tool_calls=model_tool_calls,
        cycle_count=cycle_count,
    )


@dataclass(frozen=True, slots=True)
class RuntimeEvaluationInvoker:
    """Adapt signed Runtime responses and Strands spans to the baseline runner."""

    runtime_client: RuntimeClient
    logs_client: LogsClient
    runtime_arn: str
    qualifier: str
    trace_timeout_seconds: int
    evaluation_client: AgentCoreEvaluationClient | None = None
    assertions_by_prompt: dict[str, tuple[str, ...]] = field(default_factory=_empty_assertions)
    evaluations_by_prompt: dict[str, tuple[AgentCoreEvaluationResult, ...]] = field(
        default_factory=_empty_evaluations
    )

    def __call__(
        self,
        prompt: str,
        _catalog: InMemoryCatalog,
        _settings: AgentSettings | None,
    ) -> ProjectPlanningRun:
        """Invoke one isolated Runtime session and return comparable measurements."""
        session_id = str(uuid4())
        trace_start_time_ms = int(time.time() * 1_000)
        result = invoke_runtime_endpoint(
            self.runtime_client,
            self.runtime_arn,
            self.qualifier,
            prompt,
            session_id,
        )
        trace = wait_for_runtime_traces(
            self.logs_client,
            runtime_trace_log_group(self.runtime_arn, self.qualifier),
            self.runtime_arn,
            session_id,
            trace_start_time_ms,
            self.trace_timeout_seconds,
        )
        if self.evaluation_client is not None:
            assertions = self.assertions_by_prompt.get(prompt)
            if not assertions:
                raise RuntimeEvaluationError("Runtime evaluation prompt lacks business assertions")
            self.evaluations_by_prompt[prompt] = evaluate_runtime_trace(
                self.evaluation_client,
                trace,
                session_id,
                assertions,
            )
        gateway_tool_calls = tuple(
            GATEWAY_TOOL_ALIASES.get(tool_call.name, tool_call.name)
            for tool_call in result.tool_calls
            for _ in range(tool_call.count)
        )
        return ProjectPlanningRun(
            candidates=result.candidates,
            retrieved_evidence_ids=result.retrieved_evidence_ids,
            local_tool_calls=gateway_tool_calls,
            generation_metrics=trace_generation_metrics(trace),
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the deployed evaluation command-line parser."""
    parser = argparse.ArgumentParser(
        description="Run the project-candidate baseline against AgentCore Runtime."
    )
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--qualifier", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--container-digest", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile")
    parser.add_argument("--trace-timeout-seconds", type=int, default=180)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--expectations", type=Path, default=DEFAULT_EXPECTATIONS)
    parser.add_argument("--business-assertions", type=Path, default=DEFAULT_BUSINESS_ASSERTIONS)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run all prompts through isolated Runtime sessions and save one result artifact."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.trace_timeout_seconds < 1:
        parser.error("trace timeout must be positive")

    prompts_path = cast(Path, arguments.prompts)
    expectations_path = cast(Path, arguments.expectations)
    assertions_path = cast(Path, arguments.business_assertions)
    data_directory = cast("Path | None", arguments.data_dir) or load_catalog_directory()
    output_directory = cast(Path, arguments.output_dir)
    evaluation_set = TypeAdapter(EvaluationSet).validate_json(prompts_path.read_bytes())
    expectations = TypeAdapter(EvaluationExpectations).validate_json(expectations_path.read_bytes())
    business_assertions = TypeAdapter(EvaluationBusinessAssertions).validate_json(
        assertions_path.read_bytes()
    )
    case_ids = [case.id for case in evaluation_set.cases]
    if case_ids != [expectation.case_id for expectation in expectations.expectations]:
        parser.error("prompt and expectation case IDs do not align")
    if case_ids != [case.case_id for case in business_assertions.cases]:
        parser.error("prompt and business-assertion case IDs do not align")

    settings = AgentSettings(model_id=arguments.model_id, region=arguments.region)
    deployment = DeploymentIdentity(
        endpoint_qualifier=arguments.qualifier,
        runtime_version=arguments.runtime_version,
        container_digest=arguments.container_digest,
    )
    data_plane_client = create_runtime_client(arguments.profile, arguments.region)
    assertions_by_id = {
        case.case_id: tuple(assertion.requirement for assertion in case.assertions)
        for case in business_assertions.cases
    }
    invoker = RuntimeEvaluationInvoker(
        runtime_client=data_plane_client,
        logs_client=create_logs_client(arguments.profile, arguments.region),
        runtime_arn=arguments.runtime_arn,
        qualifier=arguments.qualifier,
        trace_timeout_seconds=arguments.trace_timeout_seconds,
        evaluation_client=cast("AgentCoreEvaluationClient", data_plane_client),
        assertions_by_prompt={
            case.prompt: assertions_by_id[case.id] for case in evaluation_set.cases
        },
    )
    result = run_baseline(
        evaluation_set=evaluation_set,
        expectations=expectations,
        catalog=InMemoryCatalog.from_directory(data_directory),
        catalog_directory=data_directory,
        repository=REPOSITORY,
        settings=settings,
        invoker=invoker,
        deployment=deployment,
    )
    result = attach_agentcore_evaluations(
        result,
        evaluation_set,
        invoker.evaluations_by_prompt,
    )
    output_path = write_result(result, output_directory)
    print(output_path.relative_to(REPOSITORY))
    print(result.summary.model_dump_json(indent=2))
    return 0


def _agentcore_summary(
    cases: Sequence[EvaluationCaseResult],
) -> list[AgentCoreEvaluatorSummary]:
    """Aggregate sanitized managed-evaluator results without retaining trace data."""
    all_results = [evaluation for case in cases for evaluation in case.agentcore_evaluations]
    summaries: list[AgentCoreEvaluatorSummary] = []
    for evaluator_id in MANAGED_EVALUATORS:
        results = [result for result in all_results if result.evaluator_id == evaluator_id]
        score_count = sum(result.score_count for result in results)
        weighted_score = sum(
            (result.average_score or 0.0) * result.score_count for result in results
        )
        summaries.append(
            AgentCoreEvaluatorSummary(
                evaluator_id=evaluator_id,
                completed_case_count=sum(result.status == "completed" for result in results),
                failed_case_count=sum(result.status == "failed" for result in results),
                result_count=sum(result.result_count for result in results),
                score_count=score_count,
                average_score=weighted_score / score_count if score_count else None,
                token_usage=TokenUsageResult(
                    input_tokens=sum(result.token_usage.input_tokens for result in results),
                    output_tokens=sum(result.token_usage.output_tokens for result in results),
                    total_tokens=sum(result.token_usage.total_tokens for result in results),
                ),
            )
        )
    return summaries


def attach_agentcore_evaluations(
    result: BaselineResult,
    evaluation_set: EvaluationSet,
    evaluations_by_prompt: dict[str, tuple[AgentCoreEvaluationResult, ...]],
) -> BaselineResult:
    """Attach managed scores to their cases and produce a versioned aggregate."""
    evaluations_by_case = {
        case.id: list(evaluations_by_prompt.get(case.prompt, ())) for case in evaluation_set.cases
    }
    cases = [
        case.model_copy(update={"agentcore_evaluations": evaluations_by_case.get(case.case_id, [])})
        for case in result.cases
    ]
    summary = result.summary.model_copy(update={"agentcore_evaluations": _agentcore_summary(cases)})
    return result.model_copy(update={"result_version": 5, "summary": summary, "cases": cases})


def write_result(result: BaselineResult, output_directory: Path) -> Path:
    """Write an immutable deployed evaluation artifact."""
    deployment = result.metadata.deployment
    if deployment is None:
        raise RuntimeEvaluationError("Deployed evaluation result lacks deployment identity")
    timestamp = result.metadata.generated_at.strftime("%Y%m%dT%H%M%SZ")
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"agentcore-v{deployment.runtime_version}-{timestamp}.json"
    with output_path.open("x", encoding="utf-8") as output:
        output.write(result.model_dump_json(indent=2))
        output.write("\n")
    return output_path


if __name__ == "__main__":
    raise SystemExit(main())
