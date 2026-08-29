from typing import cast
from unittest.mock import MagicMock

import pytest
from strands import Agent
from strands.hooks import BeforeToolCallEvent

from praxis.agent.budget import ToolCallBudget, ToolCallBudgetError


def tool_event(name: str, state: dict[str, object]) -> BeforeToolCallEvent:
    return BeforeToolCallEvent(
        agent=cast("Agent", MagicMock()),
        selected_tool=None,
        tool_use={"name": name, "input": {}, "toolUseId": f"{name}-call"},
        invocation_state=state,
    )


def test_tool_call_budget_stops_before_executing_beyond_limit() -> None:
    budget = ToolCallBudget(maximum_calls=2, tool_names=frozenset({"search_catalog"}))
    invocation_state: dict[str, object] = {}

    budget.before_tool_call(tool_event("search_catalog", invocation_state))
    budget.before_tool_call(tool_event("search_catalog", invocation_state))

    with pytest.raises(ToolCallBudgetError, match="maximum 2 calls"):
        budget.before_tool_call(tool_event("search_catalog", invocation_state))


def test_tool_call_budget_excludes_internal_structured_output_tool() -> None:
    budget = ToolCallBudget(maximum_calls=1, tool_names=frozenset({"search_catalog"}))
    invocation_state: dict[str, object] = {}

    budget.before_tool_call(tool_event("ProjectCandidateSet", invocation_state))
    budget.before_tool_call(tool_event("search_catalog", invocation_state))


def test_tool_call_budget_is_scoped_to_one_invocation() -> None:
    budget = ToolCallBudget(maximum_calls=1, tool_names=frozenset({"search_catalog"}))

    budget.before_tool_call(tool_event("search_catalog", {}))
    budget.before_tool_call(tool_event("search_catalog", {}))


def test_tool_call_budget_requires_a_positive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        ToolCallBudget(maximum_calls=0, tool_names=frozenset({"search_catalog"}))
