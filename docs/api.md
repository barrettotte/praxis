# Application API

The API Gateway HTTP API accepts JSON through four explicit routes. Unknown
routes stop at API Gateway, and the Lambda rejects unknown fields and query
parameters without reflecting invalid input.

| Method | Path | JSON body |
| --- | --- | --- |
| `POST` | `/v1/sessions` | `{ "goal": "non-empty string" }` |
| `POST` | `/v1/sessions/{sessionId}/messages` | `{ "message": "non-empty string" }` |
| `GET` | `/v1/sessions/{sessionId}` | None |
| `POST` | `/v1/projects/{candidateId}/select` | `{ "sessionId": "UUIDv4" }` |

`sessionId` path and body values are canonical lowercase UUIDv4 strings.
`candidateId` is an opaque, URL-safe identifier of at most 64 letters, digits,
underscores, or hyphens. POST requests require an `application/json` content
type; API Gateway base64-encoded UTF-8 bodies are supported.

Structurally valid requests return the non-cacheable unavailable response until
their application handlers are connected. Invalid requests return a fixed 400
response without validation internals or submitted values.

## Response envelopes

Successful responses place route-specific fields under `data`:

```json
{
  "data": {
    "sessionId": "6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
  }
}
```

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
| `503` | `service_unavailable` | The requested application handler is unavailable. |

All Lambda responses are UTF-8 JSON, explicitly mark `isBase64Encoded` false,
and use `cache-control: no-store`. Error responses never include validation
internals, submitted values, stack traces, or service exception text.
