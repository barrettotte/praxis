"""Tests for the SQS-triggered recommendation worker Lambda."""

import logging
from unittest.mock import Mock

import pytest

from praxis.api.jobs import ApiJobError, RecommendationJob
from praxis.api.runtime import ApiRuntimeError, CreateSessionData
from praxis.functions import recommendation_worker

SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"
ACTOR_ID = "7b9db85b-9448-4a41-9bb7-235a461429ae"


def job() -> RecommendationJob:
    return RecommendationJob(
        session_id=SESSION_ID,
        goal="Learn compiler backends",
        correlation_id=CORRELATION_ID,
        actor_id=ACTOR_ID,
    )


def test_worker_handler_processes_one_validated_job(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[RecommendationJob] = []

    def process(parsed: RecommendationJob) -> str:
        observed.append(parsed)
        return "ready"

    monkeypatch.setattr(recommendation_worker, "process_job", process)

    response = recommendation_worker.lambda_handler(
        {
            "Records": [
                {
                    "body": job().model_dump_json(),
                    "eventSource": "aws:sqs",
                }
            ]
        },
        object(),
    )

    assert response == {"processed": 1}
    assert observed == [job()]


def test_worker_completes_successful_runtime_session(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Mock()
    session = Mock(spec=CreateSessionData)
    runtime = Mock()
    settings = Mock()
    invoke = Mock(return_value=session)
    monkeypatch.setattr(recommendation_worker, "create_session_store", Mock(return_value=store))
    monkeypatch.setattr(recommendation_worker, "runtime_client", Mock(return_value=runtime))
    monkeypatch.setattr(recommendation_worker, "load_runtime_settings", Mock(return_value=settings))
    monkeypatch.setattr(recommendation_worker, "invoke_runtime", invoke)

    assert recommendation_worker.process_job(job()) == "ready"

    invoke.assert_called_once_with(
        runtime,
        settings,
        "Learn compiler backends",
        SESSION_ID,
        CORRELATION_ID,
    )
    store.complete.assert_called_once_with(session, ACTOR_ID, "Learn compiler backends")
    store.fail.assert_not_called()


@pytest.mark.parametrize("outcome", ["ready", "failed", "retry", "invalid"])
def test_delivery_logs_only_fixed_metadata(
    outcome: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    private_marker = "private payload and provider detail"
    failure = RuntimeError(private_marker)
    process = Mock(return_value=outcome, side_effect=failure if outcome == "retry" else None)
    monkeypatch.setattr(recommendation_worker, "process_job", process)
    event: dict[str, list[dict[str, str]]] = {
        "Records": [
            {
                "body": job().model_copy(update={"goal": private_marker}).model_dump_json(),
                "eventSource": "aws:sqs",
            }
        ]
    }
    if outcome == "invalid":
        event = {"Records": []}
    with caplog.at_level(logging.INFO, logger=recommendation_worker.__name__):
        if outcome in {"retry", "invalid"}:
            with pytest.raises((RuntimeError, ApiJobError)) as raised:
                recommendation_worker.lambda_handler(event, object())
            if outcome == "retry":
                assert raised.value is failure
        else:
            assert recommendation_worker.lambda_handler(event, object()) == {"processed": 1}
    records = [r for r in caplog.records if r.name == recommendation_worker.__name__]
    assert len(records) == 1
    record = records[0]
    expected = "retry" if outcome == "invalid" else outcome
    assert record.getMessage() == "recommendation_delivery"
    assert record.__dict__["outcome"] == expected
    assert record.__dict__["duration_ms"] >= 0
    assert record.levelno == (logging.ERROR if expected == "retry" else logging.INFO)
    assert record.exc_info is None
    assert private_marker not in str(record.__dict__)
    assert ACTOR_ID not in str(record.__dict__)
    assert SESSION_ID not in str(record.__dict__)


def test_worker_records_safe_failed_state_for_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Mock()
    invoke = Mock(side_effect=ApiRuntimeError("sensitive provider detail"))
    monkeypatch.setattr(recommendation_worker, "create_session_store", Mock(return_value=store))
    monkeypatch.setattr(recommendation_worker, "runtime_client", Mock(return_value=Mock()))
    monkeypatch.setattr(recommendation_worker, "load_runtime_settings", Mock(return_value=Mock()))
    monkeypatch.setattr(recommendation_worker, "invoke_runtime", invoke)

    assert recommendation_worker.process_job(job()) == "failed"

    store.fail.assert_called_once_with(SESSION_ID, ACTOR_ID)
    store.complete.assert_not_called()


def test_worker_does_not_acknowledge_unexpected_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Mock()
    monkeypatch.setattr(recommendation_worker, "create_session_store", lambda: store)
    monkeypatch.setattr(recommendation_worker, "runtime_client", Mock(return_value=Mock()))
    monkeypatch.setattr(recommendation_worker, "load_runtime_settings", Mock(return_value=Mock()))
    monkeypatch.setattr(
        recommendation_worker, "invoke_runtime", Mock(side_effect=RuntimeError("unexpected"))
    )

    with pytest.raises(RuntimeError, match="unexpected"):
        recommendation_worker.lambda_handler(
            {"Records": [{"body": job().model_dump_json(), "eventSource": "aws:sqs"}]},
            object(),
        )

    store.complete.assert_not_called()
    store.fail.assert_not_called()
