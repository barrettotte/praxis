import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from strands.tools.mcp import MCPAgentTool, MCPTransport

from praxis.agent import gateway
from praxis.config import AgentSettings, GatewaySettings


def gateway_settings() -> GatewaySettings:
    return GatewaySettings(
        url="https://example.gateway.test/mcp",
        region="us-east-1",
        profile="praxis-dev",
    )


def catalog_tools() -> list[MCPAgentTool]:
    return cast(
        "list[MCPAgentTool]",
        [
            SimpleNamespace(tool_name=f"praxis-dev-catalog___{name}")
            for name in gateway.EXPECTED_CATALOG_TOOLS
        ],
    )


def test_create_gateway_client_uses_sigv4_and_catalog_allowlist() -> None:
    with (
        patch.object(gateway, "aws_iam_streamablehttp_client") as transport_type,
        patch.object(gateway, "MCPClient") as client_type,
    ):
        client = gateway.create_gateway_client(gateway_settings())
        transport = cast("Callable[[], MCPTransport]", client_type.call_args.args[0])
        transport_result = transport()

    assert client is client_type.return_value
    assert transport_result is transport_type.return_value
    transport_type.assert_called_once_with(
        endpoint="https://example.gateway.test/mcp",
        aws_service="bedrock-agentcore",
        aws_region="us-east-1",
        aws_profile="praxis-dev",
        timeout=20,
        sse_read_timeout=30,
    )
    client_type.assert_called_once()
    options = client_type.call_args.kwargs
    assert options["startup_timeout"] == 20
    assert options["application_name"] == "praxis-agent"
    allowed = cast("list[re.Pattern[str]]", options["tool_filters"]["allowed"])
    assert all(allowed[0].fullmatch(tool.tool_name) for tool in catalog_tools())
    assert not allowed[0].fullmatch("praxis-dev-github___create_issues")


def test_validate_gateway_tools_requires_exact_catalog_boundary() -> None:
    assert gateway.validate_gateway_tools(catalog_tools()) == tuple(catalog_tools())

    with pytest.raises(gateway.GatewayAgentError, match="expected read-only catalog boundary"):
        gateway.validate_gateway_tools(catalog_tools()[:-1])


def test_gateway_agent_session_keeps_client_open_while_constructing_agent() -> None:
    fake_client = MagicMock()
    tools = catalog_tools()
    fake_client.list_tools_sync.return_value = tools
    agent_settings = AgentSettings(
        model_id="amazon.nova-micro-v1:0",
        region="us-east-1",
    )

    with (
        patch.object(gateway, "create_gateway_client", return_value=fake_client),
        patch.object(gateway, "create_agent") as create_agent,
        gateway.gateway_agent_session(agent_settings, gateway_settings()) as agent,
    ):
        assert agent is create_agent.return_value

    fake_client.__enter__.assert_called_once_with()
    fake_client.__exit__.assert_called_once()
    create_agent.assert_called_once_with(agent_settings, tools=tuple(tools))
