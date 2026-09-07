# Application API

The API Gateway HTTP API accepts Cognito JWT-authenticated JSON requests through
three explicit routes. Unknown routes stop at API Gateway, unauthenticated
declared-route requests return 401, and the Lambda rejects unknown fields and
query parameters without reflecting invalid input. The authorizer accepts only
tokens issued by the application user pool for its public browser client.
The Lambda binds every short-lived session to the validated token subject.
Requests made by another subject receive the same `not_found` response as an
absent or expired session, including candidate-selection requests.

| Method | Path | JSON body |
| --- | --- | --- |
| `POST` | `/v1/sessions` | `{ "goal": "non-empty string" }` |
| `GET` | `/v1/sessions/{sessionId}` | None |
| `POST` | `/v1/projects/{candidateId}/select` | `{ "sessionId": "UUIDv4" }` |

Every decoded JSON request body is limited to 16 KiB. The `goal` field is limited
to 4,000 characters; bodies at or below the byte limit that violate a field
contract remain invalid requests. `sessionId` path and body values are canonical
lowercase UUIDv4 strings.
`candidateId` is one of the server-assigned identifiers `candidate_1` through
`candidate_3`. POST requests require an `application/json` content type; API
Gateway base64-encoded UTF-8 bodies are supported, with the limit applied to
their decoded bytes.

`POST /v1/sessions` creates an expiring pending session, queues a private
recommendation job, and returns `202 Accepted` with `sessionId` and status
`pending`. `GET /v1/sessions/{sessionId}` returns `pending`, `ready`, or
`failed`. A ready response contains exactly three validated, evidence-backed
candidates plus the one to three cited catalog fact records under `evidence`.
The adapter removes internal search scores and rejects citations that do not
resolve to those records. Runtime tool-call metrics are validated
internally but are not part of the public response. The normalized goal is
retained only in the expiring application session so candidate selection can
produce a goal-aligned brief; session responses do not return it. Invalid
requests return a fixed 400 response without validation internals or submitted
values.

Queue or session-store failures before job acceptance converge on the fixed
`service_unavailable` response. Model-provider errors, Gateway or catalog-tool
errors, Runtime timeouts, and invalid Runtime output produce only a `failed`
session status. The API does not expose dependency names, provider codes, retry
diagnostics, tool output, prompts, exception text, or stack traces. Clients may
submit a new goal after a failed state and use correlation headers for
investigation.

Session creation and candidate selection each target a burst of one request
and a rate of 0.1 requests per second. API Gateway applies these limits on a
best-effort basis and can return 429 before invoking Lambda. The browser does
not automatically resubmit failed POST requests; users can retry afterward.

## Response envelopes

Successful responses place route-specific fields under `data`:

```json
{
  "data": {
    "sessionId": "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4",
    "status": "pending"
  }
}
```

A pending session-create response includes only `data.sessionId` and
`data.status`. A ready session-status response adds `data.candidates`, an array
of three objects using the project-candidate contract: `title`, `summary`,
`rationale`, `estimated_scope`, `technologies`, `first_milestone`, and one or
more `evidence_citations` containing stable evidence IDs and generated
connections. `data.evidence` contains the separately validated book, project,
technical-note, or museum records referenced by those citations.

Candidate selection returns `202 Accepted` with a new job `sessionId` and
`pending` status. Poll that identifier through the existing session GET route.
A `brief_ready` response contains the server-selected candidate, its resolved
evidence, and a generated project brief. A `failed` response exposes no provider
details. The original recommendation session remains available for another selection.
Each selection creates a distinct expiring job; repeat clicks can repeat paid work.
Terminal job redeliveries skip inference, but concurrent queue deliveries are not
an exactly-once guarantee. The brief
defines its objective and bounded scope, one to six deliverables, one to five
ordered milestones, and one to six acceptance criteria. Each milestone contains
a title, implementation deliverable, and self-service verification method; each
acceptance criterion contains a condition and verification method.

Assumptions (up to five), exclusions (up to five), risks (up to four), and a
technical approach (up to six) may be omitted by the generator. The API serializes
these as empty arrays and the frontend hides empty sections. Populated sections
in saved briefs remain valid. Feasibility-driven reframing must be explicit in
scope; related catalog resources do not verify generated technical procedures.

Deploy the API/worker and Runtime as a compatible request/response contract.
Runtime candidate requests contain only `prompt`; responses contain only
`candidates`, `evidence`, and `tool_calls`. Both sides reject unsupported fields.
Selection clients must handle a pending job and poll for `brief_ready`; they must
not expect a completed brief in the POST response. The API role only accesses
sessions and SQS; only the worker invokes Runtime and reads source sessions.
For incompatible changes, pause submissions and drain queued work, deploy matching
artifacts and verify the live DEFAULT Runtime version and complete flow
before resuming traffic. Do not remove a service dependency while a serving version
still requires it. Frontend/API brief schemas must also remain compatible.
Deployment, resource deletion, and metered verification require their usual approvals.

Errors contain a stable machine-readable code and safe display text:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "Invalid request."
  }
}
```

| HTTP status | Error code | Meaning |
| --- | --- | --- |
| `400` | `invalid_request` | The request violates the public contract. |
| `400` | `sensitive_input` | Remove recognizable credentials from the goal before resubmitting. |
| `413` | `payload_too_large` | The decoded JSON request body exceeds 16 KiB. |
| `404` | `not_found` | The session is absent, expired, or owned by another subject. |
| `503` | `service_unavailable` | Recommendation generation or its dependencies are temporarily unavailable. |

All Lambda responses are UTF-8 JSON, explicitly mark `isBase64Encoded` false,
and use `cache-control: no-store`. Error responses never include validation
internals, submitted values, stack traces, or service exception text.

## Correlation IDs

Clients may send `x-correlation-id` as a canonical lowercase UUIDv4. The API
returns that value in the `x-correlation-id` response header on both success and
error responses. Without the header, the API uses API Gateway's trusted request
ID. An invalid client value produces the fixed `invalid_request` response with
a trusted fallback ID, preventing untrusted header content from being reflected.
Correlation IDs remain transport metadata and do not appear in response bodies.
The Runtime adapter forwards the selected ID as W3C tracing baggage so the
downstream invocation can be correlated without adding it to the agent prompt.

## Verification

`make test` exercises the request validator, Lambda dispatcher, Runtime adapter,
strict downstream response validation, and public response envelope in one
process without AWS credentials or model calls. The deployed
`make smoke-dev SUITE=api` check separately verifies API authorization and the
complete API Gateway-to-Runtime success path.
The default smoke checks anonymous rejection and CORS without submitting a valid
goal. Local tests cover payload limits, credential screening, and cross-subject
status and selection rejection.
