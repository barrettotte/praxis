"""Amazon Bedrock AgentCore Runtime entry point."""

from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Protocol, cast

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from opentelemetry import trace
from pydantic import Field, TypeAdapter, ValidationError
from starlette.exceptions import HTTPException

from praxis.agent.brief import invoke_project_brief as generate_project_brief
from praxis.agent.gateway import invoke_gateway_agent
from praxis.agent.generation import CandidateRun
from praxis.config import load_gateway_settings, load_settings
from praxis.domain import ProjectCandidate
from praxis.domain.briefs import ProjectBrief
from praxis.domain.prompt_safety import SensitiveInputError, require_safe_content
from praxis.tools.contracts import Evidence

RuntimeInvoker = Callable[[str], CandidateRun]
BriefInvoker = Callable[[str, ProjectCandidate, Sequence[Evidence]], ProjectBrief]
RuntimeHandler = Callable[[dict[str, object]], dict[str, object]]
type BriefGoal = Annotated[str, Field(min_length=1, max_length=4_000)]
_EVIDENCE_LIST_ADAPTER = TypeAdapter[Annotated[list[Evidence], Field(min_length=1, max_length=3)]](
    Annotated[list[Evidence], Field(min_length=1, max_length=3)]
)
_BRIEF_GOAL_ADAPTER: TypeAdapter[str] = TypeAdapter(BriefGoal)
tracer = trace.get_tracer(__name__)


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
    invoke_brief: BriefInvoker | None = None,
) -> dict[str, object]:
    """Validate one request and return a buffered recommendation or project brief."""
    require_safe_content(payload)
    if payload.get("operation") == "create_project_brief":
        if set(payload) != {"candidate", "evidence", "goal", "operation"}:
            raise RuntimeRequestError("request contains unsupported fields")
        try:
            goal = _BRIEF_GOAL_ADAPTER.validate_python(payload.get("goal"), strict=True)
            candidate = ProjectCandidate.model_validate(payload.get("candidate"))
            evidence = _EVIDENCE_LIST_ADAPTER.validate_python(payload.get("evidence"), strict=True)
        except ValidationError as error:
            raise RuntimeRequestError("project brief input is invalid") from error
        cited_ids = {citation.evidence_id for citation in candidate.evidence_citations}
        if not cited_ids <= {item.evidence_id for item in evidence}:
            raise RuntimeRequestError("project brief evidence is unavailable")
        if invoke_brief is None:
            settings = load_settings()
            brief = generate_project_brief(goal, candidate, evidence, settings)
        else:
            brief = invoke_brief(goal, candidate, evidence)
        return {"brief": brief.model_dump(mode="json")}

    prompt = _prompt_from_payload(payload)
    if set(payload) != {"prompt"}:
        raise RuntimeRequestError("request contains unsupported fields")
    if invoke_agent is None:
        run = invoke_gateway_agent(prompt, load_settings(), load_gateway_settings())
    else:
        run = invoke_agent(prompt)

    candidates = run.candidates.model_dump(mode="json")["candidates"]
    evidence = [item.model_dump(mode="json") for item in run.evidence]
    tool_calls = [{"name": name, "count": count} for name, count in run.tool_calls]
    return {
        "candidates": candidates,
        "evidence": evidence,
        "tool_calls": tool_calls,
    }


app = cast("RuntimeApplication", BedrockAgentCoreApp())


@app.entrypoint
def handle_invocation(payload: dict[str, object]) -> dict[str, object]:
    """Serve one AgentCore Runtime HTTP invocation."""
    # Automatic exception events/status descriptions can contain private SDK input.
    with tracer.start_as_current_span(
        "praxis.runtime.request", record_exception=False, set_status_on_exception=False
    ) as span:
        outcome = "error"
        try:
            response = invoke_runtime(payload)
            outcome = "success"
            return response
        except SensitiveInputError:
            outcome = "rejected"
            raise HTTPException(
                400, detail="Request content appears to contain credentials."
            ) from None
        finally:
            span.set_attribute("praxis.outcome", outcome)
            if outcome == "error":
                span.set_status(trace.StatusCode.ERROR)


if __name__ == "__main__":
    app.run()
