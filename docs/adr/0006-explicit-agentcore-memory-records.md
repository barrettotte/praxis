# ADR 0006: Explicit AgentCore Memory records

- Status: Accepted
- Date: 2026-08-30

## Context

Praxis benefits from remembering user preferences and prior project decisions
across Runtime sessions. The source catalog and its stable evidence identifiers
must remain authoritative in DynamoDB, and neither model output nor Gateway tool
results may silently become memory. Automatic conversational extraction would
mix these data classes because recommendation prompts contain retrieved catalog
evidence.

Memory writes also change persistent cloud state. They therefore need an
explicit application action, an idempotency key, and enough metadata to audit
the actor, session, operation, and record kind.

## Decision

- Use one OpenTofu-managed AgentCore Memory resource with actor-scoped
  `/actors/{actorId}/preferences/` and `/actors/{actorId}/decisions/`
  namespaces.
- Write direct long-term records with `BatchCreateMemoryRecords`. Do not attach
  an extraction strategy or save complete conversations, prompts, candidate
  responses, tool results, or catalog records.
- Allow only strict `preference` and `decision` payloads of at most 500
  characters. Reject stable catalog evidence identifiers on both writes and
  reads, and reject records outside their typed actor namespace.
- Give AgentCore Runtime only `RetrieveMemoryRecords` permission. The
  authenticated application boundary owns future writes after a distinct user
  action; the Runtime cannot create, update, or delete memory.
- Include actor, kind, operation, and session metadata on writes. Use the
  operation identifier as the service idempotency token.
- Retrieve a bounded actor-scoped set relevant to the current goal. Present it
  to the model as untrusted personalization context, separate from Gateway
  catalog evidence.

## Consequences

- Preferences and decisions can influence later sessions without turning
  AgentCore Memory into a second catalog or conversation store.
- Explicit records avoid model-based extraction cost and reduce the chance of
  prompt or evidence leakage, but the application must identify and approve
  each preference or selection it wants to retain.
- Actor IDs must come from the authenticated API boundary. Direct Runtime
  access remains limited to signed development verification.
- Direct records persist until explicitly deleted or the temporary development
  Memory resource is destroyed. The configured seven-day event expiry applies
  only if short-term events are introduced later.
