# ADR 0010: API-to-Runtime invocation boundary

## Status

Superseded in part by ADR 0017 for inbound application authorization and ADR
0018 for asynchronous recommendation generation.

## Context

Session creation must turn a validated goal into three candidates through the
version-pinned AgentCore Runtime. The API previously had no downstream
permission, so its unauthenticated fixed response could not create metered model
work. Adding Runtime invocation without authorization would expose that work to
arbitrary internet callers before the Cognito boundary is available.

API Gateway HTTP integrations and the Lambda share a short request deadline.
The measured Runtime baseline usually completes within that window, but the API
must fail safely when a cold start or model call exceeds it.

## Decision

Protect all development HTTP API routes with AWS IAM authorization. Replace
this temporary SigV4 caller boundary with Cognito JWT authorization when the
frontend authentication flow is connected.

Allow the API Lambda role to call `bedrock-agentcore:InvokeAgentRuntime` on only
the configured Runtime and its named `stable` endpoint. The session-create
handler generates a UUIDv4 Runtime session ID, reads the single-user Memory
actor from deployment configuration, and sends only that actor plus the
validated goal to Runtime. It forwards the API correlation ID as W3C tracing
baggage rather than prompt content. It does not send `runtimeUserId`, which
would require the separate `InvokeAgentRuntimeForUser` permission.

Use a 25-second SDK read timeout with no SDK retries and a 29-second Lambda
timeout. A retry could outlive the Lambda deadline and bypass the fixed error
contract. Read and validate the entire Runtime response before constructing a
201 response. Return only the session ID and three schema-valid cited
candidates; keep Memory and tool-call measurements inside the service boundary.
Map configuration, SDK, HTTP, and response-validation failures to the fixed
`service_unavailable` response. This includes model-provider and Gateway/tool
failures surfaced by Runtime; never preserve their service codes, messages,
tool output, prompts, or stack traces in the public response.

AWS evaluates qualified Runtime calls against both the Runtime and endpoint
resources, so both ARNs appear in the identity policy, as described in the
[AgentCore resource-policy documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html).
The tracing baggage follows the context supported by
[`InvokeAgentRuntime`](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html).

## Consequences

- The new metered path is unavailable to anonymous callers.
- Development API smoke checks require a SigV4-capable AWS identity with
  `execute-api:Invoke` permission.
- The Lambda cannot invoke other Runtimes or unqualified endpoint resources.
- A slow Runtime call becomes a safe 503 rather than outliving the HTTP request.
- Buffered responses keep the frontend contract simple but provide no partial
  progress before all three candidates validate.
- Authentication claims can replace the configured actor later without letting
  clients choose another Memory namespace.
