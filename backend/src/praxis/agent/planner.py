"""Local catalog transport and evaluation metrics for shared candidate generation."""

from dataclasses import dataclass
from typing import cast

from praxis.agent.factory import create_agent
from praxis.agent.generation import CandidatePlanningError as CandidatePlanningError
from praxis.agent.generation import generate_candidates
from praxis.agent.local_catalog import local_catalog_tools
from praxis.catalog import InMemoryCatalog
from praxis.config import AgentSettings, load_settings
from praxis.domain import ProjectCandidateSet
from praxis.domain.prompt_safety import require_safe_content


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token counts reported by the model provider through Strands."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class CandidateGenerationMetrics:
    """Provider and Strands metrics for one structured generation."""

    token_usage: TokenUsage
    model_latency_ms: int
    time_to_first_byte_ms: int | None
    model_tool_calls: tuple[tuple[str, int], ...]
    cycle_count: int


@dataclass(frozen=True, slots=True)
class ProjectPlanningRun:
    """One observable local planning run."""

    candidates: ProjectCandidateSet
    retrieved_evidence_ids: tuple[str, ...]
    local_tool_calls: tuple[str, ...]
    generation_metrics: CandidateGenerationMetrics | None


def invoke_project_candidates(
    goal: str,
    catalog: InMemoryCatalog,
    settings: AgentSettings | None = None,
) -> ProjectCandidateSet:
    """Generate candidates using local catalog tools and the shared model workflow."""
    return invoke_project_candidates_with_trace(goal, catalog, settings).candidates


def invoke_project_candidates_with_trace(
    goal: str,
    catalog: InMemoryCatalog,
    settings: AgentSettings | None = None,
) -> ProjectPlanningRun:
    """Use the production generation policy with an in-memory tool transport."""
    require_safe_content(goal)
    configured_settings = settings or load_settings()
    tools = local_catalog_tools(catalog)
    search_tool = next(tool for tool in tools if tool.tool_name == "search_catalog")
    agent = create_agent(configured_settings, tools=tools)

    def search(arguments: dict[str, object]) -> dict[str, object]:
        return cast("dict[str, object]", search_tool.call(arguments, "praxis-initial-search"))

    run = generate_candidates(goal, configured_settings, agent, search)
    result = run.model_result
    if result is None:
        raise CandidatePlanningError("Generation returned no model metrics")
    usage = result.metrics.accumulated_usage
    metrics = result.metrics.accumulated_metrics
    return ProjectPlanningRun(
        candidates=run.candidates,
        retrieved_evidence_ids=tuple(item.evidence_id for item in run.evidence),
        local_tool_calls=tuple(name for name, count in run.tool_calls for _ in range(count)),
        generation_metrics=CandidateGenerationMetrics(
            token_usage=TokenUsage(
                input_tokens=usage["inputTokens"],
                output_tokens=usage["outputTokens"],
                total_tokens=usage["totalTokens"],
                cache_read_input_tokens=usage.get("cacheReadInputTokens", 0),
                cache_write_input_tokens=usage.get("cacheWriteInputTokens", 0),
            ),
            model_latency_ms=metrics["latencyMs"],
            time_to_first_byte_ms=metrics.get("timeToFirstByteMs"),
            model_tool_calls=tuple(
                sorted(
                    (name, tool.call_count) for name, tool in result.metrics.tool_metrics.items()
                )
            ),
            cycle_count=result.metrics.cycle_count,
        ),
    )
