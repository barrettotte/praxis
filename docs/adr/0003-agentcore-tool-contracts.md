# ADR 0003: AgentCore tool contracts

- Status: Accepted
- Date: 2026-08-20

## Context

AgentCore Gateway Lambda targets advertise input and output schemas, but the
Gateway `SchemaDefinition` supports only types, descriptions, properties,
required fields, and array items. It cannot express all runtime constraints
needed by Praxis, including forbidden extra fields, string patterns, enums, and
numeric or collection bounds.

The tool boundary must remain strict even when the discovery schema is less
expressive. Retrieved facts must also remain distinct from generated analysis.

## Decision

- Strict Pydantic models are the canonical input and output contracts for all
  Gateway tools.
- Full Draft 2020-12 JSON Schemas are generated from those models for local
  validation and contract testing.
- AgentCore tool definitions are generated from the same models by projecting
  only the schema fields accepted by Gateway. Runtime validation remains
  authoritative for constraints the Gateway schema cannot represent.
- The generated `infra/schemas/agentcore-tools.json` artifact is checked in so
  OpenTofu plans remain deterministic and repository checks detect contract
  drift before deployment.
- `search_catalog` and `get_catalog_item` return bounded evidence projections
  without storage or provenance metadata.
- `summarize_experience` and `score_project_candidates` report deterministic,
  factual overlap with historical projects. They do not generate recommendations
  or make model-based quality judgments.
- The agent keeps an invocation-scoped ledger of returned evidence IDs and stable
  facts. It rejects conflicting facts for one ID and final citations absent from
  that ledger; an empty or conflicted ledger cannot produce recommendations.
- Optional values that are empty or absent are omitted from evidence projections
  rather than placed in agent context as empty strings or nulls.
- Known validation, lookup, timeout, and dependency failures are normalized to
  stable public error codes. Original exceptions remain chained for Lambda logs,
  while AgentCore converts the safe Lambda error into its MCP error response.
- The catalog Lambda combines its 15-second hard limit with bounded DynamoDB
  connect/read retries and a six-second remaining-time guard between reads.

The current AWS contract is documented in the
[AgentCore Lambda target guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)
and the
[SchemaDefinition API reference](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_SchemaDefinition.html).

## Consequences

- Tests must detect drift between strict runtime contracts and Gateway tool
  definitions.
- Lambda handlers must validate decoded Gateway events and responses with the
  canonical models before returning data.
- Tool callers receive retry guidance without storage identifiers, request
  values, stack traces, or SDK exception text.
- Gateway discovery communicates field shapes but cannot replace runtime
  enforcement of limits, patterns, enums, or extra-field rejection.
- Experience scoring remains auditable through stable evidence IDs and cannot be
  mistaken for an LLM recommendation.
- Recommendation grounding is enforced against current-invocation tool results,
  independent of model instructions.
