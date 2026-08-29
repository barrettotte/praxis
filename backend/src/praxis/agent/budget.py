"""Per-invocation limits for model-selected tools."""

from dataclasses import dataclass
from typing import cast

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookRegistry
from strands.types.tools import ToolResult

from praxis.tools.contracts import (
    CONTRACTS_BY_NAME,
    GetCatalogItemOutput,
    ScoreProjectCandidatesOutput,
    SearchCatalogOutput,
    SummarizeExperienceOutput,
    ToolName,
    validate_tool_output,
)

_TOOL_CALL_COUNT_KEY = "praxis.catalog_tool_call_count"
_CATALOG_RESULT_COUNT_KEY = "praxis.catalog_result_count"


class ToolCallBudgetError(RuntimeError):
    """Raised before a model-selected tool would exceed its invocation budget."""


@dataclass(frozen=True, slots=True)
class ToolCallBudget:
    """Enforce a hard call limit for a named set of external tools."""

    maximum_calls: int
    tool_names: frozenset[str]

    def __post_init__(self) -> None:
        if self.maximum_calls < 1:
            raise ValueError("maximum_calls must be positive")

    def register_hooks(self, registry: HookRegistry, **_: object) -> None:
        """Register the pre-execution budget check with Strands."""
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)

    def before_tool_call(self, event: BeforeToolCallEvent) -> None:
        """Count a bounded tool or stop before executing beyond the limit."""
        tool_name = event.tool_use["name"]
        if tool_name not in self.tool_names:
            return

        calls = int(event.invocation_state.get(_TOOL_CALL_COUNT_KEY, 0))
        if calls >= self.maximum_calls:
            message = (
                f"Catalog tool-call budget exhausted: maximum {self.maximum_calls} calls "
                "per invocation"
            )
            raise ToolCallBudgetError(message)
        event.invocation_state[_TOOL_CALL_COUNT_KEY] = calls + 1


@dataclass(frozen=True, slots=True)
class CatalogResultBudget:
    """Limit evidence records returned to the model during one invocation."""

    maximum_results: int

    def __post_init__(self) -> None:
        if self.maximum_results < 1:
            raise ValueError("maximum_results must be positive")

    def register_hooks(self, registry: HookRegistry, **_: object) -> None:
        """Register the post-execution result check with Strands."""
        registry.add_callback(AfterToolCallEvent, self.after_tool_call)

    def after_tool_call(self, event: AfterToolCallEvent) -> None:
        """Replace a malformed or over-budget catalog result before model delivery."""
        tool_name = event.tool_use["name"]
        if tool_name not in CONTRACTS_BY_NAME or event.result["status"] != "success":
            return

        raw_result = cast("dict[str, object]", event.result)
        structured_content = raw_result.get("structuredContent")
        try:
            result_count = _catalog_result_count(
                cast("ToolName", tool_name),
                structured_content,
            )
        except (TypeError, ValueError):
            event.result = _error_result(
                event,
                "Catalog tool returned an invalid structured result",
            )
            return

        prior_count = int(event.invocation_state.get(_CATALOG_RESULT_COUNT_KEY, 0))
        if prior_count + result_count > self.maximum_results:
            event.result = _error_result(
                event,
                f"Catalog result budget exhausted: maximum {self.maximum_results} records "
                "per invocation",
            )
            return
        event.invocation_state[_CATALOG_RESULT_COUNT_KEY] = prior_count + result_count


def _catalog_result_count(tool_name: ToolName, payload: object) -> int:
    """Validate one strict tool result and count its evidence-bearing records."""
    validated = validate_tool_output(tool_name, payload)
    match validated:
        case SearchCatalogOutput():
            return len(validated.results)
        case GetCatalogItemOutput():
            return 1
        case SummarizeExperienceOutput():
            return len(validated.matches)
        case ScoreProjectCandidatesOutput():
            return sum(len(score.evidence_ids) for score in validated.scores)
        case _:
            raise TypeError(f"Unsupported catalog result type: {type(validated).__name__}")


def _error_result(event: AfterToolCallEvent, message: str) -> ToolResult:
    """Return an error without retaining rejected catalog content."""
    return {
        "toolUseId": event.tool_use["toolUseId"],
        "status": "error",
        "content": [{"text": message}],
    }
