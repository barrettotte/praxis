"""Strands integration with the IAM-authenticated AgentCore Gateway."""

import re
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import cast

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from strands import Agent
from strands.agent.agent_result import AgentResult
from strands.tools.mcp import MCPAgentTool, MCPClient, MCPTransport
from strands.types.exceptions import EventLoopException, StructuredOutputException

from praxis.agent.budget import ToolCallBudgetError
from praxis.agent.factory import create_agent
from praxis.config import AgentSettings, GatewaySettings
from praxis.domain import (
    CandidateOutputValidationError,
    ProjectCandidateSet,
    validate_candidate_output,
)
from praxis.domain.candidate_validation import JsonValue

GATEWAY_SIGNING_SERVICE = "bedrock-agentcore"
EXPECTED_CATALOG_TOOLS = (
    "get_catalog_item",
    "score_project_candidates",
    "search_catalog",
    "summarize_experience",
)
_CATALOG_TOOL_PATTERN = re.compile(
    rf"^.+___(?:{'|'.join(re.escape(name) for name in EXPECTED_CATALOG_TOOLS)})$"
)


class GatewayAgentError(RuntimeError):
    """Raised when Gateway behavior violates the agent's expected tool boundary."""


@dataclass(frozen=True, slots=True)
class GatewayAgentRun:
    """Observable result of one Strands invocation through AgentCore Gateway."""

    candidates: ProjectCandidateSet
    tool_calls: tuple[tuple[str, int], ...]


def create_gateway_client(settings: GatewaySettings) -> MCPClient:
    """Create a Strands MCP client whose HTTP requests use AWS SigV4."""

    def transport() -> MCPTransport:
        return aws_iam_streamablehttp_client(
            endpoint=settings.url,
            aws_service=GATEWAY_SIGNING_SERVICE,
            aws_region=settings.region,
            aws_profile=settings.profile,
            timeout=20,
            sse_read_timeout=30,
        )

    return MCPClient(
        transport,
        startup_timeout=20,
        tool_filters={"allowed": [_CATALOG_TOOL_PATTERN]},
        application_name="praxis-agent",
    )


def validate_gateway_tools(
    tools: Sequence[MCPAgentTool],
) -> tuple[MCPAgentTool, ...]:
    """Require exactly the four read-only catalog tools before model invocation."""
    validated = tuple(tools)
    suffixes = tuple(sorted(tool.tool_name.rpartition("___")[2] for tool in validated))
    if suffixes != EXPECTED_CATALOG_TOOLS:
        message = (
            "AgentCore Gateway tools do not match the expected read-only catalog boundary: "
            f"{suffixes}"
        )
        raise GatewayAgentError(message)
    return validated


def canonical_gateway_tools(
    tools: Sequence[MCPAgentTool],
) -> tuple[MCPAgentTool, ...]:
    """Use canonical model-facing names while preserving Gateway routing names."""
    return tuple(
        MCPAgentTool(
            tool.mcp_tool,
            tool.mcp_client,
            name_override=tool.tool_name.rpartition("___")[2],
            timeout=tool.timeout,
        )
        for tool in validate_gateway_tools(tools)
    )


def discover_gateway_tool_names(settings: GatewaySettings) -> tuple[str, ...]:
    """Discover and validate tool names using the production Strands transport."""
    client = create_gateway_client(settings)
    with client:
        tools = validate_gateway_tools(client.list_tools_sync())
        return tuple(sorted(tool.tool_name for tool in tools))


@contextmanager
def gateway_agent_session(
    agent_settings: AgentSettings,
    gateway_settings: GatewaySettings,
) -> Generator[Agent]:
    """Keep the MCP connection alive for one Strands agent invocation scope."""
    client = create_gateway_client(gateway_settings)
    with client:
        tools = canonical_gateway_tools(client.list_tools_sync())
        yield create_agent(agent_settings, tools=tools)


def validate_gateway_candidate_result(result: AgentResult) -> ProjectCandidateSet:
    """Require every Gateway-backed proposal to satisfy the candidate contract."""
    output = result.structured_output
    if output is None:
        raise GatewayAgentError("Strands returned no structured project candidates")
    try:
        payload = cast("JsonValue", output.model_dump(mode="json"))
        return validate_candidate_output(payload)
    except CandidateOutputValidationError as error:
        raise GatewayAgentError("Strands returned invalid structured project candidates") from error


def invoke_gateway_agent(
    prompt: str,
    agent_settings: AgentSettings,
    gateway_settings: GatewaySettings,
) -> GatewayAgentRun:
    """Invoke Strands while its IAM-authenticated MCP connection remains open."""
    with gateway_agent_session(agent_settings, gateway_settings) as agent:
        try:
            result = agent(prompt, structured_output_model=ProjectCandidateSet)
        except ToolCallBudgetError as error:
            raise GatewayAgentError(str(error)) from error
        except EventLoopException as error:
            if isinstance(error.original_exception, ToolCallBudgetError):
                raise GatewayAgentError(str(error.original_exception)) from error
            raise
        except StructuredOutputException as error:
            raise GatewayAgentError(
                "Strands could not produce structured project candidates"
            ) from error
    candidates = validate_gateway_candidate_result(result)
    tool_calls = tuple(
        sorted(
            (name, metrics.call_count)
            for name, metrics in result.metrics.tool_metrics.items()
            if name in EXPECTED_CATALOG_TOOLS and metrics.call_count > 0
        )
    )
    return GatewayAgentRun(candidates=candidates, tool_calls=tool_calls)
