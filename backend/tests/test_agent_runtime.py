"""Tests for the AgentCore Runtime entry point."""

import json
import logging
from collections.abc import Sequence
from io import StringIO
from typing import Protocol, cast
from unittest.mock import patch

import pytest
from httpx import Client
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from starlette.exceptions import HTTPException
from starlette.testclient import TestClient
from starlette.types import ASGIApp

from praxis.agent import runtime
from praxis.agent.gateway import GatewayAgentRun
from praxis.agent.memory import MemoryRecord
from praxis.agent.runtime import RuntimeRequestError, app, invoke_runtime
from praxis.domain import (
    EvidenceCitation,
    ProjectCandidate,
    ProjectCandidateSet,
)
from praxis.domain.briefs import (
    ProjectAcceptanceCriterion,
    ProjectBrief,
    ProjectMilestone,
    ProjectRisk,
)
from praxis.domain.prompt_safety import SensitiveInputError
from praxis.tools.contracts import BookEvidence, Evidence


@pytest.mark.parametrize("outcome", ["success", "rejected", "error"])
def test_runtime_request_span_preserves_outcome_and_parent_without_content(outcome: str) -> None:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    local_tracer = provider.get_tracer("test.runtime")
    marker = "private synthetic request response and diagnostic"
    response: dict[str, object] = {"result": marker}
    failure = SensitiveInputError(marker) if outcome == "rejected" else RuntimeError(marker)

    def invoke(payload: dict[str, object]) -> dict[str, object]:
        assert payload == {"prompt": marker}
        with local_tracer.start_as_current_span("test.child"):
            pass
        if outcome != "success":
            raise failure
        return response

    try:
        with (
            patch.object(runtime, "tracer", local_tracer),
            patch.object(runtime, "invoke_runtime", side_effect=invoke),
            local_tracer.start_as_current_span("test.parent"),
        ):
            if outcome == "success":
                assert runtime.handle_invocation({"prompt": marker}) is response
            elif outcome == "rejected":
                with pytest.raises(HTTPException) as rejected:
                    runtime.handle_invocation({"prompt": marker})
                assert rejected.value.status_code == 400
                assert marker not in rejected.value.detail
            else:
                with pytest.raises(RuntimeError) as failed:
                    runtime.handle_invocation({"prompt": marker})
                assert failed.value is failure
        spans = {span.name: span for span in exporter.get_finished_spans()}
        request = spans["praxis.runtime.request"]
        assert request.attributes == {"praxis.outcome": outcome}
        assert request.events == ()
        assert request.status.status_code == (
            StatusCode.ERROR if outcome == "error" else StatusCode.UNSET
        )
        assert request.status.description is None
        assert request.parent == spans["test.parent"].context
        assert spans["test.child"].parent == request.context
        assert request.start_time is not None
        assert request.end_time is not None
        assert request.end_time >= request.start_time
        assert marker not in request.to_json()
    finally:
        provider.shutdown()


@pytest.mark.parametrize("outcome", ["success", "rejected", "error"])
def test_runtime_sdk_emits_json_outcomes(outcome: str) -> None:
    """Verify native JSON logging, including its exception-detail exposure limit."""
    sdk_logger = logging.getLogger("bedrock_agentcore.app")
    formatter = sdk_logger.handlers[0].formatter
    assert formatter is not None
    output = StringIO()
    capture = logging.StreamHandler(output)
    capture.setFormatter(formatter)
    content_marker = "synthetic request and response content"
    diagnostic = "synthetic provider diagnostic"
    failure: Exception | None = None
    if outcome == "rejected":
        failure = SensitiveInputError("Request content appears to contain credentials.")
    elif outcome == "error":
        failure = RuntimeError(diagnostic)
    sdk_logger.addHandler(capture)
    try:
        with (
            patch.object(
                runtime,
                "invoke_runtime",
                return_value={"result": content_marker},
                side_effect=failure,
            ),
            TestClient(cast("ASGIApp", app)) as client,
        ):
            response = cast("Client", client).post("/invocations", json={"prompt": content_marker})
    finally:
        sdk_logger.removeHandler(capture)
    assert response.status_code == {"success": 200, "rejected": 400, "error": 500}[outcome]
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    messages = {
        "success": "Invocation completed successfully",
        "rejected": "HTTP 400",
        "error": "Invocation failed",
    }
    matches = [record for record in records if record["message"].startswith(messages[outcome])]
    assert len(matches) == 1
    record = matches[0]
    assert record["logger"] == "bedrock_agentcore.app"
    assert record["level"] == {"success": "INFO", "rejected": "WARNING", "error": "ERROR"}[outcome]
    assert record["timestamp"]
    assert content_marker not in output.getvalue()
    if outcome == "error":
        assert record["errorMessage"] == diagnostic
        assert record["errorType"] == "RuntimeError"
        assert record["stackTrace"]


@pytest.mark.parametrize(
    "payload",
    [
        {"actor_id": "user-123", "prompt": "api_key=synthetic-credential"},
        {"operation": "create_project_brief", "goal": "api_key=synthetic-credential"},
        {"operation": "create_project_brief", "candidate": {"password": "synthetic-credential"}},
    ],
)
def test_runtime_http_rejects_credentials_before_validation_and_agent_work(
    payload: dict[str, object], caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch.object(runtime, "load_settings") as settings,
        patch.object(runtime, "AgentCoreMemoryStore") as memory,
        patch.object(runtime, "invoke_gateway_agent") as agent,
        patch.object(runtime, "generate_project_brief") as brief,
        TestClient(cast("ASGIApp", app)) as client,
    ):
        response = cast("Client", client).post("/invocations", json=payload)
    assert response.status_code == 400
    assert response.json() == {"error": "Request content appears to contain credentials."}
    for dependency in (settings, memory, agent, brief):
        dependency.assert_not_called()
    assert "synthetic-credential" not in caplog.text + response.text


class RuntimeRoute(Protocol):
    path: str
    methods: set[str] | None


class RoutedRuntimeApplication(Protocol):
    routes: list[RuntimeRoute]


def candidate_set() -> ProjectCandidateSet:
    return ProjectCandidateSet(
        candidates=[
            ProjectCandidate(
                title=f"Candidate {number}",
                summary="Build a focused compiler project.",
                rationale="The evidence provides relevant implementation context.",
                estimated_scope="multi-week",
                technologies=["Python"],
                first_milestone="Implement one instruction-selection rule.",
                evidence_citations=[
                    EvidenceCitation(
                        evidence_id="book:0f5ba253568e4836",
                        generated_connection="The evidence supports this learning path.",
                    )
                ],
            )
            for number in range(1, 4)
        ]
    )


def book_evidence() -> BookEvidence:
    """Return the catalog fact cited by the candidate fixture."""
    return BookEvidence(
        evidence_id="book:0f5ba253568e4836",
        kind="book",
        title="Compiler Backend Development",
        author="Quentin Colombet",
        year=2025,
        category="Compilers",
        tags=[],
    )


def project_brief() -> ProjectBrief:
    """Return one schema-valid generated project brief."""
    return ProjectBrief(
        objective="Build a small compiler backend.",
        scope="Implement one expression-lowering path over a weekend.",
        technical_approach=[
            "Define a JSON expression model and validate sample inputs.",
            "Lower expressions into target instructions with Python.",
            "Execute the instructions and compare their numeric result.",
        ],
        assumptions=[
            "Python and a local test runner are available.",
            "One expression form is enough for the exercise.",
        ],
        out_of_scope=[
            "Register allocation is outside this project.",
            "Multiple target architectures are outside this project.",
        ],
        deliverables=[
            "A documented input representation for expressions.",
            "A tested instruction selector with example output.",
        ],
        milestones=[
            ProjectMilestone(
                title=f"Milestone {number}",
                deliverable="A concrete implementation artifact.",
                verification="An automated check validates the artifact.",
            )
            for number in range(1, 4)
        ],
        risks=[
            ProjectRisk(risk=f"Risk {number}", mitigation="Use a bounded fallback.")
            for number in range(1, 3)
        ],
        acceptance_criteria=[
            ProjectAcceptanceCriterion(
                criterion=f"Criterion {number} has a measurable result.",
                verification="An automated test records the expected result.",
            )
            for number in range(1, 4)
        ],
    )


def test_runtime_app_exposes_agentcore_http_contract() -> None:
    routes = cast("RoutedRuntimeApplication", app).routes

    assert any(
        route.path == "/ping" and route.methods is not None and "GET" in route.methods
        for route in routes
    )
    assert any(
        route.path == "/invocations" and route.methods is not None and "POST" in route.methods
        for route in routes
    )


@pytest.mark.parametrize("payload", [{}, {"prompt": ""}, {"prompt": "  "}, {"prompt": 7}])
def test_invoke_runtime_rejects_invalid_prompts(payload: dict[str, object]) -> None:
    with pytest.raises(RuntimeRequestError, match="prompt must be a non-empty string"):
        invoke_runtime(payload, lambda _prompt, _memory: GatewayAgentRun(candidate_set(), ()))


@pytest.mark.parametrize("actor_id", [None, "", "user:other"])
def test_invoke_runtime_rejects_invalid_actor_ids(actor_id: object) -> None:
    with pytest.raises(RuntimeRequestError, match="actor_id"):
        invoke_runtime(
            {"actor_id": actor_id, "prompt": "compiler"},
            lambda _prompt, _memory: GatewayAgentRun(candidate_set(), ()),
        )


def test_invoke_runtime_returns_buffered_candidates_and_tool_metrics(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = "synthetic-credential-not-model-context"
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, marker)
    observed_prompts: list[str] = []
    observed_memory: list[tuple[str, ...]] = []

    def invoke_agent(prompt: str, memory: Sequence[str]) -> GatewayAgentRun:
        observed_prompts.append(prompt)
        observed_memory.append(tuple(memory))
        return GatewayAgentRun(
            candidates=candidate_set(),
            tool_calls=(("get_catalog_item", 1), ("search_catalog", 2)),
            evidence=(book_evidence(),),
        )

    response = invoke_runtime(
        {"actor_id": "user-123", "prompt": "  Recommend a compiler project  "},
        invoke_agent,
    )

    assert observed_prompts == ["Recommend a compiler project"]
    assert observed_memory == [()]
    candidates = response["candidates"]
    assert isinstance(candidates, list)
    assert len(cast("list[object]", candidates)) == 3
    assert response["tool_calls"] == [
        {"name": "get_catalog_item", "count": 1},
        {"name": "search_catalog", "count": 2},
    ]
    assert response["evidence"] == [book_evidence().model_dump(mode="json")]
    assert response["memory"] == {"retrieved_count": 0}
    captured = capsys.readouterr()
    assert marker not in repr(response) + captured.out + captured.err + caplog.text


def test_invoke_runtime_passes_only_typed_memory_to_the_agent() -> None:
    class FakeMemory:
        def recall(self, actor_id: str, query: str) -> tuple[MemoryRecord, ...]:
            assert actor_id == "user-123"
            assert query == "compiler"
            return (MemoryRecord(kind="preference", text="Prefer weekend scope."),)

    observed_context: list[Sequence[str]] = []

    def invoke_agent(_prompt: str, context: Sequence[str]) -> GatewayAgentRun:
        observed_context.append(context)
        return GatewayAgentRun(
            candidate_set(),
            (("search_catalog", 1),),
            (book_evidence(),),
        )

    response = invoke_runtime(
        {"actor_id": "user-123", "prompt": "compiler"},
        invoke_agent,
        FakeMemory(),
    )

    assert observed_context == [('{"kind":"preference","text":"Prefer weekend scope."}',)]
    assert response["memory"] == {"retrieved_count": 1}


def test_invoke_runtime_generates_brief_from_typed_server_context() -> None:
    selected = candidate_set().candidates[0]
    assert selected is not None
    observed: list[tuple[str, ProjectCandidate, tuple[Evidence, ...]]] = []

    def generate(
        goal: str,
        candidate: ProjectCandidate,
        evidence: Sequence[Evidence],
    ) -> ProjectBrief:
        observed.append((goal, candidate, tuple(evidence)))
        return project_brief()

    response = invoke_runtime(
        {
            "actor_id": "user-123",
            "operation": "create_project_brief",
            "goal": "Learn compiler backends over a weekend",
            "candidate": selected.model_dump(mode="json"),
            "evidence": [book_evidence().model_dump(mode="json")],
        },
        invoke_brief=generate,
    )

    assert observed == [("Learn compiler backends over a weekend", selected, (book_evidence(),))]
    assert response == {"brief": project_brief().model_dump(mode="json")}


@pytest.mark.parametrize(
    "payload",
    [
        {
            "actor_id": "user-123",
            "operation": "create_project_brief",
            "goal": "Learn compiler backends",
            "candidate": {},
            "evidence": [book_evidence().model_dump(mode="json")],
        },
        {
            "actor_id": "user-123",
            "operation": "create_project_brief",
            "goal": "Learn compiler backends",
            "candidate": candidate_set().candidates[0].model_dump(mode="json"),
            "evidence": [],
        },
    ],
)
def test_invoke_runtime_rejects_invalid_brief_context(payload: dict[str, object]) -> None:
    with pytest.raises(RuntimeRequestError, match="project brief input is invalid"):
        invoke_runtime(payload)


def test_invoke_runtime_rejects_brief_without_original_goal() -> None:
    with pytest.raises(RuntimeRequestError, match="unsupported fields"):
        invoke_runtime(
            {
                "actor_id": "user-123",
                "operation": "create_project_brief",
                "candidate": candidate_set().candidates[0].model_dump(mode="json"),
                "evidence": [book_evidence().model_dump(mode="json")],
            }
        )
