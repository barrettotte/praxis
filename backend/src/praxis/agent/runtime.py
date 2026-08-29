"""Amazon Bedrock AgentCore Runtime entry point."""

from collections.abc import Callable, Mapping
from typing import Protocol, cast

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from praxis.agent.gateway import GatewayAgentRun, invoke_gateway_agent
from praxis.config import load_gateway_settings, load_settings

RuntimeInvoker = Callable[[str], GatewayAgentRun]
RuntimeHandler = Callable[[dict[str, object]], dict[str, object]]


class RuntimeApplication(Protocol):
    """Typed surface used from the AgentCore SDK application."""

    def entrypoint(self, handler: RuntimeHandler) -> RuntimeHandler: ...

    def run(self) -> None: ...


class RuntimeRequestError(ValueError):
    """Raised when an AgentCore invocation payload is invalid."""


def _prompt_from_payload(payload: Mapping[str, object]) -> str:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeRequestError("prompt must be a non-empty string")
    return prompt.strip()


def invoke_runtime(
    payload: Mapping[str, object],
    invoke_agent: RuntimeInvoker | None = None,
) -> dict[str, object]:
    """Validate one request and return buffered, evidence-backed candidates."""
    prompt = _prompt_from_payload(payload)
    if invoke_agent is None:
        agent_settings = load_settings()
        gateway_settings = load_gateway_settings()
        run = invoke_gateway_agent(prompt, agent_settings, gateway_settings)
    else:
        run = invoke_agent(prompt)

    candidates = run.candidates.model_dump(mode="json")["candidates"]
    tool_calls = [{"name": name, "count": count} for name, count in run.tool_calls]
    return {"candidates": candidates, "tool_calls": tool_calls}


app = cast("RuntimeApplication", BedrockAgentCoreApp())


@app.entrypoint
def handle_invocation(payload: dict[str, object]) -> dict[str, object]:
    """Serve one AgentCore Runtime HTTP invocation."""
    return invoke_runtime(payload)


if __name__ == "__main__":
    app.run()
