import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import Tool as MCPTool
from strands.tools.mcp import MCPAgentTool, MCPClient, MCPTransport

from praxis.agent import gateway
from praxis.config import AgentSettings, GatewaySettings


def gateway_settings() -> GatewaySettings:
    return GatewaySettings(
        url="https://example.gateway.test/mcp",
        region="us-east-1",
        profile="praxis-dev",
    )


def catalog_tools() -> list[MCPAgentTool]:
    client = cast("MCPClient", MagicMock())
    return [
        MCPAgentTool(
            MCPTool(
                name=f"praxis-dev-catalog___{name}",
                description=f"Invoke {name}.",
                inputSchema={"type": "object"},
            ),
            client,
        )
        for name in gateway.EXPECTED_CATALOG_TOOLS
    ]


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
    tools = catalog_tools()
    assert gateway.validate_gateway_tools(tools) == tuple(tools)

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
    model_tools = cast("tuple[MCPAgentTool, ...]", create_agent.call_args.kwargs["tools"])
    assert tuple(tool.tool_name for tool in model_tools) == gateway.EXPECTED_CATALOG_TOOLS
    assert tuple(tool.mcp_tool.name for tool in model_tools) == tuple(
        tool.tool_name for tool in tools
    )


def test_invoke_gateway_agent_keeps_session_open_during_model_invocation() -> None:
    class StubAgentResult:
        def __init__(self) -> None:
            self.metrics = SimpleNamespace(
                tool_metrics={
                    "praxis-dev-catalog___search_catalog": SimpleNamespace(call_count=1),
                    "praxis-dev-catalog___get_catalog_item": SimpleNamespace(call_count=0),
                }
            )

        def __str__(self) -> str:
            return "Evidence-backed recommendation"

    fake_agent = MagicMock()
    fake_agent.return_value = StubAgentResult()
    session = MagicMock()
    session.__enter__.return_value = fake_agent
    agent_settings = AgentSettings(
        model_id="amazon.nova-micro-v1:0",
        region="us-east-1",
    )

    with patch.object(gateway, "gateway_agent_session", return_value=session):
        result = gateway.invoke_gateway_agent(
            "Recommend a compiler project",
            agent_settings,
            gateway_settings(),
        )

    session.__enter__.assert_called_once_with()
    session.__exit__.assert_called_once()
    fake_agent.assert_called_once_with("Recommend a compiler project")
    assert result.response == "Evidence-backed recommendation"
    assert result.tool_calls == (("praxis-dev-catalog___search_catalog", 1),)
