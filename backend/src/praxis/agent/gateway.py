"""IAM-authenticated catalog transport for the shared candidate generator."""

import re
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import cast

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from strands import Agent
from strands.tools.mcp import MCPAgentTool, MCPClient, MCPTransport

from praxis.agent.factory import create_agent
from praxis.agent.generation import (
    EXPECTED_CATALOG_TOOLS as EXPECTED_CATALOG_TOOLS,
)
from praxis.agent.generation import (
    CandidatePlanningError,
    CandidateRun,
    generate_candidates,
)
from praxis.config import AgentSettings, GatewaySettings
from praxis.domain.prompt_safety import require_safe_content

GATEWAY_SIGNING_SERVICE = "bedrock-agentcore"
_CATALOG_TOOL_PATTERN = re.compile(
    rf"^.+___(?:{'|'.join(re.escape(name) for name in EXPECTED_CATALOG_TOOLS)})$"
)


@dataclass(frozen=True, slots=True)
class GatewayAgentSession:
    """Open Gateway connection and the Strands agent that uses it."""

    agent: Agent
    client: MCPClient
    tools: tuple[MCPAgentTool, ...]


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
        raise CandidatePlanningError(message)
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
) -> Generator[GatewayAgentSession]:
    """Keep the MCP connection alive for one Strands agent invocation scope."""
    client = create_gateway_client(gateway_settings)
    with client:
        tools = canonical_gateway_tools(client.list_tools_sync())
        yield GatewayAgentSession(
            agent=create_agent(agent_settings, tools=tools),
            client=client,
            tools=tools,
        )


def invoke_gateway_agent(
    prompt: str,
    agent_settings: AgentSettings,
    gateway_settings: GatewaySettings,
) -> CandidateRun:
    """Keep the authenticated MCP connection open throughout shared generation."""
    require_safe_content(prompt)
    with gateway_agent_session(agent_settings, gateway_settings) as session:
        search_tool = next(tool for tool in session.tools if tool.tool_name == "search_catalog")

        def search(arguments: dict[str, object]) -> dict[str, object]:
            return cast(
                "dict[str, object]",
                session.client.call_tool_sync(
                    tool_use_id="praxis-initial-search",
                    name=search_tool.mcp_tool.name,
                    arguments=arguments,
                    read_timeout_seconds=search_tool.timeout,
                ),
            )

        return generate_candidates(prompt, agent_settings, session.agent, search)
