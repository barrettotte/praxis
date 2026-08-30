# Application API

The API Gateway HTTP API accepts IAM-signed JSON requests through four explicit
routes. Unknown routes stop at API Gateway, unsigned declared-route requests
return 403, and the Lambda rejects unknown fields and query parameters without
reflecting invalid input. Cognito JWT authorization replaces development IAM
authorization when the frontend authentication boundary is deployed.

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
`candidateId` is an opaque, URL-safe identifier of at most 64 letters, digits,
underscores, or hyphens. POST requests require an `application/json` content
type; API Gateway base64-encoded UTF-8 bodies are supported, with the limit
applied to their decoded bytes.

`POST /v1/sessions` invokes the version-pinned AgentCore Runtime and returns a
complete buffered response with a generated session ID and exactly three
validated, evidence-backed candidates. Runtime Memory and tool-call metrics are
validated internally but are not part of the public response. Other
structurally valid routes return the non-cacheable unavailable response until
their handlers are connected. Invalid requests return a fixed 400 response
without validation internals or submitted values.

Model-provider errors, Gateway or catalog-tool errors, Runtime timeouts, and
invalid Runtime output converge on the fixed `service_unavailable` response.
The API does not expose dependency names, provider codes, retry diagnostics,
tool output, prompts, exception text, or stack traces. Clients may retry with
backoff and use the response correlation header for investigation.

Session creation allows a burst of one request and refills at 0.1 requests per
second. Requests above that route limit receive API Gateway's 429 response
before Lambda or Runtime invocation. Clients should wait before retrying and
must not treat throttling as a completed session.

## Response envelopes

Successful responses place route-specific fields under `data`:

```json
{
  "data": {
    "sessionId": "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
  }
}
```

The session-create response also includes `data.candidates`, an array of three
objects using the project-candidate contract: `title`, `summary`, `rationale`,
`estimated_scope`, `technologies`, `first_milestone`, and one or more
`evidence_citations` containing stable evidence IDs and generated connections.

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
