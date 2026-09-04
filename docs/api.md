# Application API

The API Gateway HTTP API accepts Cognito JWT-authenticated JSON requests through
four explicit routes. Unknown routes stop at API Gateway, unauthenticated
declared-route requests return 401, and the Lambda rejects unknown fields and
query parameters without reflecting invalid input. The authorizer accepts only
tokens issued by the application user pool for its public browser client.

| Method | Path | JSON body |
| --- | --- | --- |
| `POST` | `/v1/sessions` | `{ "goal": "non-empty string" }` |
| `POST` | `/v1/sessions/{sessionId}/messages` | `{ "message": "non-empty string" }` |
| `GET` | `/v1/sessions/{sessionId}` | None |
| `POST` | `/v1/projects/{candidateId}/select` | `{ "sessionId": "UUIDv4" }` |

Every decoded JSON request body is limited to 16 KiB. The `goal` and `message`
fields are each limited to 4,000 characters; bodies at or below the byte limit
that violate a field contract remain invalid requests. `sessionId` path and body
values are canonical lowercase UUIDv4 strings.
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
resolve to those records. Runtime Memory and tool-call metrics are validated
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

Session creation allows a burst of one request and refills at 0.1 requests per
second. Requests above that route limit receive API Gateway's 429 response
before Lambda or Runtime invocation. Clients should wait before retrying and
must not treat throttling as a completed session.

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

A successful candidate-selection response contains the server-selected
candidate, its resolved evidence, and a generated project brief. The brief
defines its objective and bounded scope, a three-to-six-step technical approach,
assumptions, explicit exclusions, named deliverables, three to five ordered
milestones, two to four risks, and three to six acceptance criteria. Technical
approach steps name accessible tools or methods, inputs, and observable outputs.
Every milestone contains a deliverable and self-service verification method;
every acceptance criterion contains the condition and its verification method.
Feasibility-driven reframing must remain within the selected candidate's
declared scope and appear explicitly in the scope and exclusions.

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
| `413` | `payload_too_large` | The decoded JSON request body exceeds 16 KiB. |
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
