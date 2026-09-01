"""Amazon Bedrock AgentCore Runtime entry point."""

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, cast

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from praxis.agent.gateway import GatewayAgentRun, invoke_gateway_agent
from praxis.agent.memory import (
    AgentCoreMemoryStore,
    MemoryRecord,
    actor_namespace,
    memory_prompt_context,
)
from praxis.config import load_gateway_settings, load_memory_settings, load_settings

RuntimeInvoker = Callable[[str, Sequence[str]], GatewayAgentRun]
RuntimeHandler = Callable[[dict[str, object]], dict[str, object]]


class RuntimeApplication(Protocol):
    """Typed surface used from the AgentCore SDK application."""

    def entrypoint(self, handler: RuntimeHandler) -> RuntimeHandler: ...

    def run(self) -> None: ...


class RuntimeRequestError(ValueError):
    """Raised when an AgentCore invocation payload is invalid."""


class RuntimeMemory(Protocol):
    """Read-only memory surface available to the recommendation Runtime."""

    def recall(self, actor_id: str, query: str) -> tuple[MemoryRecord, ...]: ...


def _prompt_from_payload(payload: Mapping[str, object]) -> str:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeRequestError("prompt must be a non-empty string")
    return prompt.strip()


def _actor_from_payload(payload: Mapping[str, object]) -> str:
    actor_id = payload.get("actor_id")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise RuntimeRequestError("actor_id must be a non-empty string")
    normalized = actor_id.strip()
    try:
        actor_namespace(normalized)
    except ValueError as error:
        raise RuntimeRequestError("actor_id has an invalid format") from error
    return normalized


def invoke_runtime(
    payload: Mapping[str, object],
    invoke_agent: RuntimeInvoker | None = None,
    memory: RuntimeMemory | None = None,
) -> dict[str, object]:
    """Validate one request and return buffered, evidence-backed candidates."""
    prompt = _prompt_from_payload(payload)
    actor_id = _actor_from_payload(payload)
    if set(payload) != {"actor_id", "prompt"}:
        raise RuntimeRequestError("request contains unsupported fields")
    memory_store = memory
    if invoke_agent is None:
        agent_settings = load_settings()
        gateway_settings = load_gateway_settings()
        memory_store = memory_store or AgentCoreMemoryStore(load_memory_settings())
        memories = memory_store.recall(actor_id, prompt)
        run = invoke_gateway_agent(
            prompt,
            agent_settings,
            gateway_settings,
            memory_context=memory_prompt_context(memories),
        )
    else:
        memories = memory_store.recall(actor_id, prompt) if memory_store is not None else ()
        run = invoke_agent(prompt, memory_prompt_context(memories))

    candidates = run.candidates.model_dump(mode="json")["candidates"]
    evidence = [item.model_dump(mode="json") for item in run.evidence]
    tool_calls = [{"name": name, "count": count} for name, count in run.tool_calls]
    return {
        "candidates": candidates,
        "evidence": evidence,
        "memory": {"retrieved_count": len(memories)},
        "tool_calls": tool_calls,
    }


app = cast("RuntimeApplication", BedrockAgentCoreApp())


@app.entrypoint
def handle_invocation(payload: dict[str, object]) -> dict[str, object]:
    """Serve one AgentCore Runtime HTTP invocation."""
    return invoke_runtime(payload)


if __name__ == "__main__":
    app.run()
