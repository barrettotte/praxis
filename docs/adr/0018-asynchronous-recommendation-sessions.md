# ADR 0018: Asynchronous recommendation sessions

- Status: Accepted
- Date: 2026-09-01

## Context

Recommendation generation uses multiple managed-service and model calls. The
measured median fits inside one API Gateway HTTP request, but tail latency can
exceed the service's non-increasable 30-second integration limit. A 25-second
SDK deadline allows the API Lambda to return a safe error, but it cannot make a
slow valid generation complete within that synchronous boundary.

The application already has an expiring DynamoDB session record and a declared
session-status route. The single-user workflow does not need streaming tokens,
durable history, or a general workflow engine.

## Decision

- `POST /v1/sessions` creates a pending session, submits one job to an encrypted
  SQS queue, and returns `202 Accepted` with the session ID and `pending` status.
- The API binds each session to the validated Cognito JWT subject. The queue
  message contains only that subject, the validated goal, session ID, and
  correlation ID, and is retained for at most one day. The normalized goal and
  subject remain in the one-hour application session solely to preserve
  selection context and authorize access; neither is copied into logs,
  AgentCore Memory, or public responses.
- A dedicated Python 3.13 worker Lambda consumes one job at a time, invokes the
  version-pinned AgentCore Runtime with one 90-second SDK attempt, and completes
  within a 120-second Lambda deadline.
- The worker replaces the pending DynamoDB item with a schema-valid `ready`
  candidate set or marks it `failed` without dependency details. Session TTL
  remains one hour.
- `GET /v1/sessions/{sessionId}` returns `pending`, `ready`, or `failed`. Only a
  ready response includes candidates and resolved catalog evidence. Status and
  candidate-selection lookups require the caller's JWT subject to match the
  stored owner and otherwise return the same 404 response as an absent record.
- The browser polls the authenticated status route at a bounded interval while
  retaining its accessible progress state.
- The API role can send jobs and manage session state. A separate worker role
  can consume only this queue, invoke only the configured Runtime and endpoint,
  update only the session table, and write only its log group.
- Expected model, tool, and validation failures are recorded as a safe failed
  state and acknowledged. Unexpected worker failures may retry once before SQS
  moves the encrypted message to a dedicated dead-letter queue.

## Consequences

- Slow valid generations no longer compete with API Gateway's HTTP integration
  deadline.
- Session creation adds SQS and polling requests, one worker Lambda, a worker
  role, and a dead-letter queue. All use on-demand pricing and remain disposable
  with the development stack.
- The browser sees no partial model output. Candidate and brief payloads remain
  buffered and strictly validated.
- A failed or expired session requires a fresh goal submission. Public status
  records do not reveal whether the cause was the model, Gateway, a tool, or
  another dependency.
- Project-brief generation remains synchronous because its measured path fits
  comfortably inside the API deadline. It can adopt the same queue if evidence
  later shows otherwise.
