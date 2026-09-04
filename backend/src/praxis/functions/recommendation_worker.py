"""Consume queued recommendation jobs outside the API Gateway request deadline."""

from functools import cache

from praxis.api.jobs import RecommendationJob, parse_job_event
from praxis.api.runtime import (
    ApiRuntimeError,
    RuntimeClient,
    create_worker_runtime_client,
    invoke_runtime,
    load_runtime_settings,
)
from praxis.api.sessions import create_session_store


@cache
def runtime_client() -> RuntimeClient:
    """Reuse the long-deadline AgentCore client across warm worker invocations."""
    return create_worker_runtime_client()


def process_job(job: RecommendationJob) -> None:
    """Generate and persist one queued recommendation set."""
    store = create_session_store()
    try:
        session = invoke_runtime(
            runtime_client(),
            load_runtime_settings(),
            job.goal,
            job.session_id,
            job.correlation_id,
        )
    except ApiRuntimeError:
        store.fail(job.session_id)
        return
    store.complete(session, job.goal)


def lambda_handler(event: object, context: object) -> dict[str, int]:
    """Validate and process one SQS-delivered recommendation job."""
    del context
    process_job(parse_job_event(event))
    return {"processed": 1}
