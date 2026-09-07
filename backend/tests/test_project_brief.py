"""Tests for strict generated project-brief contracts."""

import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError
from strands.agent.agent_result import AgentResult
from strands.types.exceptions import MaxTokensReachedException

from praxis.agent import brief
from praxis.config import AgentSettings
from praxis.domain import EvidenceCitation, ProjectCandidate
from praxis.domain.briefs import ProjectBrief
from praxis.domain.prompt_safety import SensitiveInputError
from praxis.tools.contracts import BookEvidence


def valid_brief() -> dict[str, object]:
    return {
        "objective": "Build a small compiler backend that lowers one expression form.",
        "scope": "Implement and test one target instruction-selection path over a weekend.",
        "technical_approach": [
            "Define a JSON expression model and validate sample inputs with Pydantic.",
            "Lower each expression into a small target-instruction list with Python.",
            "Execute the instruction list in a test interpreter and compare its numeric result.",
        ],
        "assumptions": [
            "Python 3.13 and a local test runner are available.",
            "One arithmetic expression form is sufficient for the exercise.",
        ],
        "out_of_scope": [
            "Register allocation and machine-code emission are excluded.",
            "Production optimization and multiple target architectures are excluded.",
        ],
        "deliverables": [
            "A documented intermediate expression representation.",
            "A tested instruction-selection implementation and example output.",
        ],
        "milestones": [
            {
                "title": "Define input",
                "deliverable": "A documented input expression grammar.",
                "verification": "Example valid and invalid expressions pass parser tests.",
            },
            {
                "title": "Lower expression",
                "deliverable": "An instruction selector for one expression form.",
                "verification": "A snapshot test matches the expected target instructions.",
            },
            {
                "title": "Verify output",
                "deliverable": "An automated executable-output test suite.",
                "verification": "The suite executes emitted output and checks its result.",
            },
        ],
        "risks": [
            {"risk": "The target is too broad.", "mitigation": "Support one expression form."},
            {"risk": "Output is hard to debug.", "mitigation": "Keep readable snapshots."},
        ],
        "acceptance_criteria": [
            {
                "criterion": "One supported expression compiles to the expected instructions.",
                "verification": "Compare emitted instructions with a committed snapshot.",
            },
            {
                "criterion": "Invalid input produces a stable diagnostic without output.",
                "verification": "Run parameterized invalid-input tests and assert the diagnostic.",
            },
            {
                "criterion": "The emitted program returns the expected arithmetic result.",
                "verification": "Execute the generated program in the test harness.",
            },
        ],
    }


def candidate() -> ProjectCandidate:
    return ProjectCandidate(
        title="Compiler backend exercise",
        summary="Build a compact compiler backend exercise.",
        rationale="It provides focused compiler implementation practice.",
        estimated_scope="weekend",
        technologies=["Python"],
        first_milestone="Implement one instruction-selection rule.",
        evidence_citations=[
            EvidenceCitation(
                evidence_id="book:0f5ba253568e4836",
                generated_connection="The book provides relevant backend context.",
            )
        ],
    )


def evidence() -> BookEvidence:
    return BookEvidence(
        evidence_id="book:0f5ba253568e4836",
        kind="book",
        title="Compiler Backend Development",
        author="Quentin Colombet",
        year=2025,
        category="Compilers",
        tags=[],
    )


def settings() -> AgentSettings:
    return AgentSettings(model_id="amazon.nova-pro-v1:0", region="us-east-1")


def test_brief_agent_configures_versioned_guardrail() -> None:
    configured = AgentSettings(
        model_id="amazon.nova-pro-v1:0",
        region="us-east-1",
        guardrail_id="guardrail-123",
        guardrail_version="7",
    )

    with (
        patch.object(brief, "Session") as session_type,
        patch.object(brief, "BedrockModel") as model_type,
        patch.object(brief, "Agent") as agent_type,
    ):
        brief.create_brief_agent(configured)

    model_type.assert_called_once_with(
        boto_session=session_type.return_value,
        model_id="amazon.nova-pro-v1:0",
        guardrail_id="guardrail-123",
        guardrail_version="7",
        guardrail_trace="enabled",
        guardrail_latest_message=False,
        temperature=0,
        max_tokens=3000,
        additional_request_fields={"inferenceConfig": {"topK": 1}},
        streaming=False,
    )
    agent_type.assert_called_once_with(
        model=model_type.return_value,
        tools=[],
        system_prompt=brief.BRIEF_SYSTEM_PROMPT,
        callback_handler=None,
    )


def test_project_brief_output_uses_direct_schema() -> None:
    output = ProjectBrief.model_validate(valid_brief())

    assert output.model_dump(mode="json") == valid_brief()


def test_project_brief_output_rejects_incomplete_content() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        ProjectBrief.model_validate({"objective": "Incomplete"})


@pytest.mark.parametrize("source", ["goal", "candidate", "evidence"])
def test_brief_screens_all_model_context_before_agent_creation(source: str) -> None:
    marker = "api_key=synthetic-credential"
    selected = candidate()
    item = evidence()
    if source == "candidate":
        selected = selected.model_copy(update={"summary": marker})
    if source == "evidence":
        item = item.model_copy(update={"title": marker})
    with patch.object(brief, "create_brief_agent") as create, pytest.raises(SensitiveInputError):
        brief.invoke_project_brief(
            marker if source == "goal" else "compiler", selected, [item], settings()
        )
    create.assert_not_called()


def test_invokes_deterministic_brief_agent_with_server_context() -> None:
    structured_output = ProjectBrief.model_validate(valid_brief())
    agent_result = cast("AgentResult", SimpleNamespace(structured_output=structured_output))

    with patch.object(brief, "create_brief_agent") as create_agent:
        create_agent.return_value.return_value = agent_result
        result = brief.invoke_project_brief(
            "Learn compiler backends over a weekend",
            candidate(),
            [evidence()],
            settings(),
        )

    invocation = create_agent.return_value.call_args
    assert invocation is not None
    prompt = cast("str", invocation.args[0])
    goal, context = prompt.split(
        "\n\nGenerate the project brief from this server-validated context:\n",
        maxsplit=1,
    )
    assert goal == "Learn compiler backends over a weekend"
    payload = json.loads(context)
    assert payload["selected_candidate"]["title"] == "Compiler backend exercise"
    assert payload["catalog_evidence"][0]["evidence_id"] == "book:0f5ba253568e4836"
    assert invocation.kwargs == {
        "structured_output_model": ProjectBrief,
        "limits": {"turns": 3},
    }
    assert result.model_dump(mode="json") == valid_brief()


def test_brief_guardrail_assesses_only_original_goal() -> None:
    structured_output = ProjectBrief.model_validate(valid_brief())
    agent_result = cast("AgentResult", SimpleNamespace(structured_output=structured_output))
    configured = AgentSettings(
        model_id="amazon.nova-pro-v1:0",
        region="us-east-1",
        guardrail_id="guardrail-123",
        guardrail_version="7",
    )

    with patch.object(brief, "create_brief_agent") as create_agent:
        create_agent.return_value.return_value = agent_result
        brief.invoke_project_brief(
            "Learn compiler backends over a weekend",
            candidate(),
            [evidence()],
            configured,
        )

    invocation = create_agent.return_value.call_args
    assert invocation is not None
    prompt = cast("list[dict[str, object]]", invocation.args[0])
    assert prompt[0] == {
        "guardContent": {"text": {"text": "Learn compiler backends over a weekend"}}
    }
    assert "book:0f5ba253568e4836" in cast("str", prompt[1]["text"])


def test_retries_transient_model_tool_sequence_failure() -> None:
    structured_output = ProjectBrief.model_validate(valid_brief())
    agent_result = cast("AgentResult", SimpleNamespace(structured_output=structured_output))
    transient_error = ClientError(
        {
            "Error": {
                "Code": "ModelErrorException",
                "Message": "Model produced invalid sequence as part of ToolUse.",
            }
        },
        "Converse",
    )

    with patch.object(brief, "create_brief_agent") as create_agent:
        create_agent.return_value.side_effect = [transient_error, agent_result]
        result = brief.invoke_project_brief(
            "Learn compiler backends over a weekend",
            candidate(),
            [evidence()],
            settings(),
        )

    assert create_agent.call_count == 2
    assert result.model_dump(mode="json") == valid_brief()


def test_does_not_retry_or_accept_partial_brief_after_token_exhaustion() -> None:
    with patch.object(brief, "create_brief_agent") as create_agent:
        create_agent.return_value.side_effect = MaxTokensReachedException("Output limit reached")
        with pytest.raises(MaxTokensReachedException):
            brief.invoke_project_brief(
                "Learn compiler backends over a weekend",
                candidate(),
                [evidence()],
                settings(),
            )

    create_agent.assert_called_once_with(settings())
    create_agent.return_value.assert_called_once()


def test_does_not_retry_unrelated_bedrock_failure() -> None:
    provider_error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "Denied"}},
        "Converse",
    )

    with patch.object(brief, "create_brief_agent") as create_agent:
        create_agent.return_value.side_effect = provider_error
        with pytest.raises(brief.ProjectBriefAgentError, match="Bedrock could not produce"):
            brief.invoke_project_brief(
                "Learn compiler backends over a weekend",
                candidate(),
                [evidence()],
                settings(),
            )

    assert create_agent.call_count == 1


def test_rejects_candidate_without_resolved_evidence() -> None:
    with pytest.raises(brief.ProjectBriefAgentError, match="evidence is unavailable"):
        brief.invoke_project_brief("Learn compiler backends", candidate(), [], settings())


def test_brief_quality_guidance_does_not_add_a_serving_rejection() -> None:
    payload = valid_brief()
    milestones = cast("list[dict[str, str]]", payload["milestones"])
    milestones[0]["verification"] = "The examples are functional and complete."

    output = ProjectBrief.model_validate(payload)

    assert output.milestones[0].verification == milestones[0]["verification"]


def test_project_brief_output_rejects_external_expert_verification() -> None:
    payload = valid_brief()
    milestones = cast("list[dict[str, str]]", payload["milestones"])
    milestones[0]["verification"] = "Peer review by a chemistry or physics expert."

    with pytest.raises(ValidationError, match="external expert"):
        ProjectBrief.model_validate(payload)


@pytest.mark.parametrize(
    "objective",
    [
        "To learn enough chemistry to design a battery.",
        "Understand the principles of quantum mechanics.",
    ],
)
def test_project_brief_output_rejects_learning_only_objective(objective: str) -> None:
    payload = valid_brief()
    payload["objective"] = objective

    with pytest.raises(ValidationError, match="artifact or observable result"):
        ProjectBrief.model_validate(payload)


def test_project_brief_output_rejects_subjective_acceptance_criterion() -> None:
    payload = valid_brief()
    criteria = cast("list[dict[str, str]]", payload["acceptance_criteria"])
    criteria[0]["criterion"] = "The user has a solid understanding of quantum mechanics."

    with pytest.raises(ValidationError, match="observable artifact or result"):
        ProjectBrief.model_validate(payload)


def test_project_brief_output_accepts_learning_tied_to_artifacts() -> None:
    payload = valid_brief()
    payload["objective"] = (
        "Learn quantum mechanics by producing a simulation report and comparison dataset."
    )

    output = ProjectBrief.model_validate(payload)

    assert output.objective == payload["objective"]


def test_compact_brief_defaults_optional_sections_and_round_trips() -> None:
    payload = valid_brief()
    optional = ("technical_approach", "assumptions", "out_of_scope", "risks")
    for name in optional:
        payload.pop(name)
    for name in ("deliverables", "milestones", "acceptance_criteria"):
        payload[name] = cast("list[object]", payload[name])[:1]

    parsed = ProjectBrief.model_validate(payload)
    serialized = parsed.model_dump(mode="json")

    assert all(serialized[name] == [] for name in optional)
    assert type(parsed).model_validate_json(parsed.model_dump_json()) == parsed
    assert len(parsed.milestones) == 1


@pytest.mark.parametrize("field", ["deliverables", "milestones", "acceptance_criteria"])
def test_compact_brief_requires_nonempty_core_lists(field: str) -> None:
    payload = valid_brief()
    payload[field] = []
    with pytest.raises(ValidationError):
        ProjectBrief.model_validate(payload)


@pytest.mark.parametrize("field", ["technical_approach", "assumptions", "out_of_scope", "risks"])
def test_optional_brief_sections_reject_null(field: str) -> None:
    payload = valid_brief()
    payload[field] = None
    with pytest.raises(ValidationError):
        ProjectBrief.model_validate(payload)


def test_full_brief_preserves_optional_sections() -> None:
    payload = valid_brief()
    parsed = ProjectBrief.model_validate(payload)
    assert parsed.model_dump(mode="json") == payload


def test_project_brief_output_rejects_unknown_alias() -> None:
    payload = valid_brief()
    payload["exclusions"] = payload.pop("out_of_scope")
    with pytest.raises(ValidationError, match="Extra inputs"):
        ProjectBrief.model_validate(payload)
