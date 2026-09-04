# ADR 0006: Server-authoritative recommendation sessions

- Status: Accepted
- Date: 2026-08-31

## Context

The browser receives three generated candidates, then selects one for expansion
into a project brief. AgentCore Runtime session affinity routes invocations but
does not persist application results, and the Runtime creates a fresh Strands
agent for each request. Sending the complete candidate back from the browser
would allow client-controlled data to cross the application boundary as though
it were a prior model result.

The single-user MVP needs only brief continuity between recommendation and
selection. It does not need durable conversation history, provisioned capacity,
or a general-purpose workflow store.

## Decision

- The API assigns the identifiers `candidate_1` through `candidate_3` after it
  validates a Runtime recommendation response.
- The API Lambda creates a pending record, and the private recommendation
  worker stores the normalized original goal, each validated candidate set, and
  its resolved catalog evidence in a separate on-demand DynamoDB table keyed by
  Runtime session ID. Public session responses omit the retained goal.
- Records expire after one hour through a DynamoDB TTL attribute. The table has
  AWS-owned encryption, no point-in-time recovery, and no deletion protection
  because the data is generated, temporary, and reproducible.
- The selection request contains only the session ID and candidate ID. The API
  resolves the original goal, candidate, and evidence from its session table
  before invoking Runtime to generate a strict project brief.
- The brief Runtime path receives no Gateway tools. It can use only the
  original goal, server-selected generated candidate, and catalog facts already
  cited by that candidate, preserving the existing read-only evidence boundary.
- The API and recommendation-worker Lambdas receive only their required session
  operations. The Runtime receives no session-table permission, and the browser
  receives no AWS data-plane credentials.

## Consequences

- A client cannot substitute an arbitrary candidate or catalog record when it
  requests a project brief.
- The brief retains the user's constraints without writing prompts to AgentCore
  Memory or creating durable history; the goal expires with the session after
  one hour.
- Recommendation creation moves through pending, ready, or failed state as
  described by ADR 0018. Candidate selection is available only for ready state.
- Expired sessions require the user to request fresh candidates. DynamoDB TTL
  deletion is asynchronous, so the application also checks `expires_at` when it
  reads a record.
- This table is application workflow state, not authoritative catalog data or
  AgentCore Memory. It must remain separate from both boundaries.
- Durable multi-user histories or resumable workflows would require a new data
  model, authorization partitioning, retention policy, and a superseding ADR.
