"""Tests for the API Lambda's bounded AgentCore Runtime adapter."""

import json
from typing import Protocol, cast

import pytest
from botocore.config import Config
from botocore.exceptions import ClientError, ReadTimeoutError

from praxis.api import runtime as api_runtime
from praxis.api.runtime import (
    ApiRuntimeError,
    ApiRuntimeSettings,
    SessionCandidate,
    create_runtime_client,
    create_worker_runtime_client,
    invoke_project_brief_runtime,
    invoke_runtime,
    load_runtime_settings,
)
from praxis.tools.contracts import BookEvidence

RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example-runtime"
SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"


class ObservedRuntimeConfig(Protocol):
    """Botocore options inspected at the Runtime client boundary."""

    connect_timeout: int
    read_timeout: int
    retries: dict[str, object]


class FakeBody:
    """In-memory stand-in for botocore's streaming response body."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class FakeRuntimeClient:
    """Capture one Runtime invocation and return a configured response."""

    def __init__(self, response: dict[str, object] | Exception) -> None:
        self.response = response
        self.request: dict[str, object] | None = None

    def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]:
        self.request = kwargs
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def candidate(number: int) -> dict[str, object]:
    """Return one schema-valid Runtime candidate."""
    return {
        "title": f"Candidate {number}",
        "summary": "Build a focused compiler project.",
        "rationale": "The evidence provides relevant implementation context.",
        "estimated_scope": "multi-week",
        "technologies": ["Python"],
        "first_milestone": "Implement one instruction-selection rule.",
        "evidence_citations": [
            {
                "evidence_id": "book:0f5ba253568e4836",
                "generated_connection": "The evidence supports this learning path.",
            }
        ],
    }


def valid_response() -> dict[str, object]:
    """Return a buffered response matching the deployed Runtime contract."""
    payload: dict[str, object] = {
        "candidates": [candidate(number) for number in range(1, 4)],
        "evidence": [
            {
                "evidence_id": "book:0f5ba253568e4836",
                "kind": "book",
                "title": "Compiler Backend Development",
                "author": "Quentin Colombet",
                "year": 2025,
                "category": "Compilers",
                "tags": [],
            }
        ],
        "memory": {"retrieved_count": 1},
        "tool_calls": [{"name": "search_catalog", "count": 1}],
    }
    return {
        "contentType": "application/json",
        "response": FakeBody(json.dumps(payload).encode()),
        "runtimeSessionId": SESSION_ID,
        "statusCode": 200,
    }


def valid_brief_response() -> dict[str, object]:
    """Return a buffered Runtime response containing one strict project brief."""
    return {
        "contentType": "application/json",
        "response": FakeBody(
            json.dumps(
                {
                    "brief": {
                        "objective": "Build a small compiler backend.",
                        "scope": "Implement one expression-lowering path over a weekend.",
                        "technical_approach": [
                            "Define a JSON expression model and validate sample inputs.",
                            "Lower expressions into target instructions with Python.",
                            "Execute the instructions and compare their numeric result.",
                        ],
                        "assumptions": [
                            "Python and a local test runner are available.",
                            "One expression form is enough for the exercise.",
                        ],
                        "out_of_scope": [
                            "Register allocation is outside this project.",
                            "Multiple target architectures are outside this project.",
                        ],
                        "deliverables": [
                            "A documented input representation for expressions.",
                            "A tested instruction selector with example output.",
                        ],
                        "milestones": [
                            {
                                "title": f"Milestone {number}",
                                "deliverable": "A concrete implementation artifact.",
                                "verification": "An automated check validates the artifact.",
                            }
                            for number in range(1, 4)
                        ],
                        "risks": [
                            {
                                "risk": f"Risk {number}",
                                "mitigation": "Use a bounded fallback.",
                            }
                            for number in range(1, 3)
                        ],
                        "acceptance_criteria": [
                            {
                                "criterion": f"Criterion {number} has a measurable result.",
                                "verification": "An automated test records the expected result.",
                            }
                            for number in range(1, 4)
                        ],
                    }
                }
            ).encode()
        ),
        "runtimeSessionId": SESSION_ID,
        "statusCode": 200,
    }


def settings() -> ApiRuntimeSettings:
    return ApiRuntimeSettings(
        runtime_arn=RUNTIME_ARN,
        qualifier="stable",
        actor_id="praxis-single-user",
    )


def test_loads_complete_runtime_settings() -> None:
    assert (
        load_runtime_settings(
            {
                "PRAXIS_API_ACTOR_ID": "praxis-single-user",
                "PRAXIS_AGENT_RUNTIME_ARN": RUNTIME_ARN,
                "PRAXIS_AGENT_RUNTIME_QUALIFIER": "stable",
            }
        )
        == settings()
    )


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {
            "PRAXIS_API_ACTOR_ID": "user:other",
            "PRAXIS_AGENT_RUNTIME_ARN": RUNTIME_ARN,
            "PRAXIS_AGENT_RUNTIME_QUALIFIER": "stable",
        },
    ],
)
def test_rejects_invalid_runtime_settings(environment: dict[str, str]) -> None:
    with pytest.raises(ApiRuntimeError, match="invalid Runtime configuration"):
        load_runtime_settings(environment)


def test_runtime_client_stops_before_the_api_lambda_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    expected_client = FakeRuntimeClient(valid_response())

    class FakeSession:
        def client(self, service_name: str, *, config: Config) -> FakeRuntimeClient:
            observed.update(service_name=service_name, config=config)
            return expected_client

    monkeypatch.setattr(api_runtime, "Session", FakeSession)

    assert create_runtime_client() is expected_client
    assert observed["service_name"] == "bedrock-agentcore"
    config = cast("ObservedRuntimeConfig", observed["config"])
    assert config.connect_timeout == 3
    assert config.read_timeout == 25
    assert config.retries == {"mode": "standard", "total_max_attempts": 1}

    assert create_worker_runtime_client() is expected_client
    worker_config = cast("ObservedRuntimeConfig", observed["config"])
    assert worker_config.connect_timeout == 3
    assert worker_config.read_timeout == 90
    assert worker_config.retries == {"mode": "standard", "total_max_attempts": 1}


def test_invokes_runtime_and_returns_only_public_session_data() -> None:
    client = FakeRuntimeClient(valid_response())

    result = invoke_runtime(
        client,
        settings(),
        "  Recommend a compiler project  ",
        SESSION_ID,
        CORRELATION_ID,
    )

    assert client.request == {
        "accept": "application/json",
        "agentRuntimeArn": RUNTIME_ARN,
        "baggage": f"praxis.correlation_id={CORRELATION_ID}",
        "contentType": "application/json",
        "payload": b'{"actor_id":"praxis-single-user","prompt":"Recommend a compiler project"}',
        "qualifier": "stable",
        "runtimeSessionId": SESSION_ID,
    }
    assert result.model_dump(mode="json", by_alias=True) == {
        "sessionId": SESSION_ID,
        "candidates": [
            {"candidateId": f"candidate_{number}", **candidate(number)} for number in range(1, 4)
        ],
        "evidence": [
            {
                "evidence_id": "book:0f5ba253568e4836",
                "kind": "book",
                "title": "Compiler Backend Development",
                "author": "Quentin Colombet",
                "year": 2025,
                "category": "Compilers",
                "tags": [],
            }
        ],
    }


def test_invokes_runtime_for_selected_candidate_brief() -> None:
    client = FakeRuntimeClient(valid_brief_response())
    selected = SessionCandidate.model_validate(
        {"candidate_id": "candidate_2", **candidate(2)},
    )
    evidence = BookEvidence(
        evidence_id="book:0f5ba253568e4836",
        kind="book",
        title="Compiler Backend Development",
        author="Quentin Colombet",
        year=2025,
        category="Compilers",
        tags=[],
    )

    result = invoke_project_brief_runtime(
        client,
        settings(),
        SESSION_ID,
        "Learn compiler backends over a weekend",
        selected,
        [evidence],
        CORRELATION_ID,
    )

    assert client.request is not None
    payload = json.loads(cast("bytes", client.request["payload"]))
    assert payload == {
        "actor_id": "praxis-single-user",
        "operation": "create_project_brief",
        "goal": "Learn compiler backends over a weekend",
        "candidate": candidate(2),
        "evidence": [evidence.model_dump(mode="json")],
    }
    assert result.session_id == SESSION_ID
    assert result.candidate_id == "candidate_2"
    assert result.candidate == selected
    assert len(result.brief.milestones) == 3
    assert result.evidence == [evidence]


def test_rejects_citations_without_a_matching_fact_record() -> None:
    response = valid_response()
    body = cast("FakeBody", response["response"])
    payload = cast("dict[str, object]", json.loads(body.read()))
    payload["evidence"] = [
        {
            "evidence_id": "book:0000000000000001",
            "kind": "book",
            "title": "Unrelated book",
            "author": None,
            "year": 2020,
            "category": None,
            "tags": [],
        }
    ]
    response["response"] = FakeBody(json.dumps(payload).encode())

    with pytest.raises(ApiRuntimeError, match="invalid response"):
        invoke_runtime(
            FakeRuntimeClient(response),
            settings(),
            "compiler",
            SESSION_ID,
            CORRELATION_ID,
        )


def test_percent_encodes_gateway_correlation_id_in_tracing_baggage() -> None:
    client = FakeRuntimeClient(valid_response())

    invoke_runtime(client, settings(), "compiler", SESSION_ID, "MqgCjHCKoAMEPLw=")

    assert client.request is not None
    assert client.request["baggage"] == "praxis.correlation_id=MqgCjHCKoAMEPLw%3D"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({"statusCode": 503}, "invocation failed"),
        (
            {
                "contentType": "text/plain",
                "response": FakeBody(b"not JSON"),
                "runtimeSessionId": SESSION_ID,
                "statusCode": 200,
            },
            "invalid response",
        ),
        (
            {
                "contentType": "application/json",
                "response": FakeBody(b'{"candidates":[]}'),
                "runtimeSessionId": SESSION_ID,
                "statusCode": 200,
            },
            "invalid response",
        ),
        (
            {
                **valid_response(),
                "runtimeSessionId": "51f4a405-8835-411d-9821-5980d73f51f6",
            },
            "invalid response",
        ),
    ],
)
def test_rejects_runtime_failures(response: dict[str, object], message: str) -> None:
    client = FakeRuntimeClient(response)
    with pytest.raises(ApiRuntimeError, match=message):
        invoke_runtime(client, settings(), "compiler", SESSION_ID, CORRELATION_ID)
    assert client.request is not None


@pytest.mark.parametrize(
    ("code", "detail"),
    [
        ("ModelErrorException", "sensitive model provider detail"),
        ("RuntimeClientError", "sensitive Gateway tool detail"),
    ],
    ids=["model", "tool"],
)
def test_hides_model_and_tool_runtime_errors(code: str, detail: str) -> None:
    error = ClientError(
        {"Error": {"Code": code, "Message": detail}},
        "InvokeAgentRuntime",
    )

    with pytest.raises(ApiRuntimeError, match="invocation failed") as captured:
        invoke_runtime(
            FakeRuntimeClient(error),
            settings(),
            "compiler",
            SESSION_ID,
            CORRELATION_ID,
        )

    assert detail not in str(captured.value)
    assert code not in str(captured.value)


def test_hides_invalid_runtime_response_content() -> None:
    marker = "sensitive model or tool output"
    response = {
        **valid_response(),
        "response": FakeBody(marker.encode()),
    }

    with pytest.raises(ApiRuntimeError, match="invalid response") as captured:
        invoke_runtime(
            FakeRuntimeClient(response),
            settings(),
            "compiler",
            SESSION_ID,
            CORRELATION_ID,
        )

    assert marker not in str(captured.value)


def test_timeout_while_reading_runtime_body_returns_safe_error() -> None:
    class TimedOutBody:
        def read(self) -> bytes:
            raise ReadTimeoutError(endpoint_url="https://sensitive.example.com")

    client = FakeRuntimeClient({**valid_response(), "response": TimedOutBody()})
    with pytest.raises(ApiRuntimeError, match="invalid response") as captured:
        invoke_runtime(client, settings(), "compiler", SESSION_ID, CORRELATION_ID)

    assert "sensitive" not in str(captured.value)
