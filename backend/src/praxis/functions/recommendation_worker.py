"""Consume queued recommendation jobs outside the API Gateway request deadline."""

import logging
from functools import cache
from time import monotonic
from typing import Literal

from opentelemetry import trace

from praxis.api.jobs import RecommendationJob, job_trace_context, parse_job_event
from praxis.api.runtime import (
    ApiRuntimeError,
    RuntimeClient,
    create_worker_runtime_client,
    invoke_project_brief_runtime,
    invoke_runtime,
    load_runtime_settings,
)
from praxis.api.sessions import PendingSession, create_session_store
from praxis.functions.tracing import lambda_tracer

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
tracer = lambda_tracer(__name__)


@cache
def runtime_client() -> RuntimeClient:
    """Reuse the long-deadline AgentCore client across warm worker invocations."""
    return create_worker_runtime_client()


def process_job(job: RecommendationJob) -> Literal["ready", "failed"]:
    """Generate and persist one queued recommendation set."""
    store = create_session_store()
    if job.source_session_id is not None and job.candidate_id is not None:
        # Terminal/expired deliveries must not start another paid generation.
        if not isinstance(store.get_record(job.session_id, job.actor_id), PendingSession):
            return "ready"
        source = store.get(job.source_session_id, job.actor_id)
        candidate = source.selected_candidate(job.candidate_id) if source else None
        if source is None or candidate is None:
            store.fail(job.session_id, job.actor_id)
            return "failed"
        try:
            selection = invoke_project_brief_runtime(
                runtime_client(),
                load_runtime_settings(),
                job.session_id,
                source.goal,
                candidate,
                source.evidence_for(candidate),
                job.correlation_id,
            )
        except ApiRuntimeError:
            store.fail(job.session_id, job.actor_id)
            return "failed"
        store.complete_brief(selection, job.actor_id, source.goal)
        return "ready"
    try:
        session = invoke_runtime(
            runtime_client(),
            load_runtime_settings(),
            job.goal,
            job.session_id,
            job.correlation_id,
        )
    except ApiRuntimeError:
        store.fail(job.session_id, job.actor_id)
        return "failed"
    store.complete(session, job.actor_id, job.goal)
    return "ready"


def lambda_handler(event: object, context: object) -> dict[str, int]:
    """Validate and process one SQS-delivered recommendation job."""
    del context
    # Preserve SQS retries without recording exception text or the queued payload.
    with tracer.start_as_current_span(
        "praxis.worker.delivery",
        context=job_trace_context(event),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        started = monotonic()
        outcome = "retry"
        try:
            outcome = process_job(parse_job_event(event))
        finally:
            span.set_attribute("praxis.outcome", outcome)
            if outcome != "ready":
                span.set_status(trace.StatusCode.ERROR)
            logger.log(
                logging.ERROR if outcome == "retry" else logging.INFO,
                "recommendation_delivery",
                extra={"outcome": outcome, "duration_ms": round((monotonic() - started) * 1000)},
            )
    return {"processed": 1}
