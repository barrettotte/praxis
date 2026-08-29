"""Strands integration with the IAM-authenticated AgentCore Gateway."""

import re
from collections.abc import Generator, Sequence
from contextlib import contextmanager

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from strands import Agent
from strands.tools.mcp import MCPAgentTool, MCPClient, MCPTransport

from praxis.agent.factory import create_agent
from praxis.config import AgentSettings, GatewaySettings

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
    """Raised when Gateway discovery violates the agent's expected tool boundary."""


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
        tools = validate_gateway_tools(client.list_tools_sync())
        yield create_agent(agent_settings, tools=tools)
