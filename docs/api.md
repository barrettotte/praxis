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
