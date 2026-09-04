# ADR 0022: Bounded non-conversational workflow

## Status

Accepted

## Context

Praxis creates recommendations from one goal and creates a project brief from
one server-owned candidate selection. Each operation invokes the model once
with bounded evidence. The browser never submits dialogue history, the Runtime
does not accept it, and AgentCore Memory stores only explicit preferences and
prior decisions. A declared follow-up-message API route had no implementation
or frontend caller and always returned a service-unavailable response.

Conversation summarization is useful when accumulated dialogue competes for a
model's context window. Applying it here would introduce a second generated
representation, token cost, and information-loss risk without reducing any
context currently sent by the application.

## Decision

Keep recommendation generation and project-brief generation as separate,
bounded one-shot model operations. Expose only session creation, session status,
and candidate selection routes. Remove the unused follow-up-message route and
do not add conversation summarization.

AgentCore Memory remains separate from conversation state and continues to
provide only explicit actor-scoped preferences and prior decisions. A future
conversational workflow requires its own product requirement, context-retention
policy, privacy analysis, and measured summary-versus-full-history evaluation.

## Consequences

- Model context remains bounded by the goal, validated evidence, maintained
  instructions, and explicit memory records.
- The public API no longer advertises an operation that cannot succeed.
- There is no summarization model call, summary persistence, or risk that a
  generated summary silently drops a user constraint.
- Follow-up refinement would require a deliberate API and evaluation design
  instead of reusing the current short-lived recommendation session implicitly.
