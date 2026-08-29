from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from strands.types.tools import AgentTool

from praxis.agent import factory
from praxis.config import AgentSettings


def test_create_agent_configures_strands_with_bedrock() -> None:
    settings = AgentSettings(
        model_id="amazon.nova-micro-v1:0",
        region="us-east-1",
    )

    with (
        patch.object(factory, "Session") as session_type,
        patch.object(factory, "BedrockModel") as model_type,
        patch.object(factory, "Agent") as agent_type,
    ):
        boto_session = session_type.return_value
        model = model_type.return_value
        expected_agent = agent_type.return_value

        agent = factory.create_agent(settings)

    assert agent is expected_agent
    session_type.assert_called_once_with(region_name="us-east-1")
    model_type.assert_called_once_with(
        boto_session=boto_session,
        model_id="amazon.nova-micro-v1:0",
        temperature=0.1,
    )
    agent_type.assert_called_once_with(
        model=model,
        tools=[],
        system_prompt=factory.SYSTEM_PROMPT,
        callback_handler=None,
    )


def test_create_agent_uses_nova_tool_calling_parameters() -> None:
    settings = AgentSettings(
        model_id="amazon.nova-micro-v1:0",
        region="us-east-1",
    )
    tool = cast("AgentTool", SimpleNamespace())

    with (
        patch.object(factory, "Session") as session_type,
        patch.object(factory, "BedrockModel") as model_type,
        patch.object(factory, "Agent"),
    ):
        factory.create_agent(settings, tools=[tool])

    model_type.assert_called_once_with(
        boto_session=session_type.return_value,
        model_id="amazon.nova-micro-v1:0",
        temperature=0,
        max_tokens=3000,
        additional_request_fields={"inferenceConfig": {"topK": 1}},
        streaming=False,
    )
