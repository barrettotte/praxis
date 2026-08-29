"""Per-invocation limits for model-selected tools."""

from dataclasses import dataclass

from strands.hooks import BeforeToolCallEvent, HookRegistry

_TOOL_CALL_COUNT_KEY = "praxis.catalog_tool_call_count"


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
