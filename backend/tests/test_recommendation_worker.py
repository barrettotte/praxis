"""Tests for the SQS-triggered recommendation worker Lambda."""

from unittest.mock import Mock

import pytest

from praxis.api.jobs import RecommendationJob
from praxis.api.runtime import ApiRuntimeError, CreateSessionData
from praxis.functions import recommendation_worker

SESSION_ID = "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
CORRELATION_ID = "51f4a405-8835-411d-9821-5980d73f51f6"


def job() -> RecommendationJob:
    return RecommendationJob(
        session_id=SESSION_ID,
        goal="Learn compiler backends",
        correlation_id=CORRELATION_ID,
    )


def test_worker_handler_processes_one_validated_job(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[RecommendationJob] = []
    monkeypatch.setattr(recommendation_worker, "process_job", observed.append)

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

    recommendation_worker.process_job(job())

    invoke.assert_called_once_with(
        runtime,
        settings,
        "Learn compiler backends",
        SESSION_ID,
        CORRELATION_ID,
    )
    store.complete.assert_called_once_with(session, "Learn compiler backends")
    store.fail.assert_not_called()


def test_worker_records_safe_failed_state_for_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Mock()
    invoke = Mock(side_effect=ApiRuntimeError("sensitive provider detail"))
    monkeypatch.setattr(recommendation_worker, "create_session_store", Mock(return_value=store))
    monkeypatch.setattr(recommendation_worker, "runtime_client", Mock(return_value=Mock()))
    monkeypatch.setattr(recommendation_worker, "load_runtime_settings", Mock(return_value=Mock()))
    monkeypatch.setattr(recommendation_worker, "invoke_runtime", invoke)

    recommendation_worker.process_job(job())

    store.fail.assert_called_once_with(SESSION_ID)
    store.complete.assert_not_called()
