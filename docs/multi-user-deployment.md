# Multi-user deployment requirements

Praxis is a single-user demonstration. This document identifies work required
before widening access; it is not an accepted deployment design or a claim that
these controls exist. Keep the [current architecture](../README.md#architecture)
and [read-only tool boundary](adr/0003-agentcore-tool-contracts.md) unchanged
until a scoped proposal is approved.

## Identity and data isolation

The API binds session access to the validated Cognito JWT subject. However,
[deployment configuration](../infra/environments/dev/locals.tf) supplies one
`praxis-single-user` actor to API and worker Runtime calls. The catalog is also
a shared personal dataset without per-user document permissions. Adding another
Cognito account would not create isolated personalization or private retrieval.

Before implementation, choose whether users share one authorized catalog or
belong to separate organizations with distinct data. Define organization
membership, administrative roles, and removal/revocation behavior. These are
product and security decisions, not values the model or browser may choose.

| Boundary | Required change | Verification required before widening access |
| --- | --- | --- |
| Authentication and membership | Define the approved identity provider, MFA, provisioning, deprovisioning, and session/token response policy. Derive user and organization scope from verified identity and server-side authorization. | Reject invalid issuers/audiences, disabled membership, and forged organization fields; test the stated revocation behavior. |
| API → session store → queue → worker | Carry authenticated scope through recommendation creation, status, and selection. Preserve ownership checks on reads and conditional writes; do not rely on UUID secrecy. | Two-user and two-organization tests reject substituted session/candidate IDs, mismatched queued ownership, and expired state. |
| API/worker → Runtime → Memory | Replace the deployment-wide actor with a trusted scoped identity, including brief generation. Review service-role authority as well as namespace checks. Choose application-enforced sharing or stronger resource/role separation explicitly. | Deny cross-user recall even with a guessed actor ID; reject spoofed Runtime context and verify permissions match the chosen isolation model. |
| Runtime → Gateway → catalog | Enforce source permissions before evidence enters model context. A model-provided filter is not authorization. Carry trusted scope separately from tool arguments; preserve permission checks on direct evidence lookup and selection. | Unauthorized records never reach search output, summaries, scoring, citations, or brief context, including guessed evidence IDs and changed permissions. |
| Telemetry and exports | Define readers, content capture, redaction limits, retention, deletion, and audit access for each store. Keep tokens and unnecessary identity/content out of diagnostics. | Verify cross-organization reader denial and the lifecycle of logs, traces, queues, Memory, backups, and exported evaluations; session TTL alone is insufficient. |

## Reliability, cost, and operations

- Add per-user or organization admission limits and usage attribution with a
  documented cost ceiling policy. Existing route throttles and budget alerts
  do not enforce total spending or fair access.
- Design a conditional work claim and duplicate-handling policy before scaling
  workers. Conditional completion alone does not prevent repeated inference.
  Test concurrent deliveries, crashes, claim expiry, and brief-selection retries;
  do not claim exactly-once model execution across an external service call.
- Define availability and recovery objectives. Measure queue age, tail latency,
  errors, and recovery behavior under representative concurrency before choosing
  capacity changes or moving brief generation to the queue.
- Replace disposable-development assumptions with reviewed backup, restoration,
  deletion-protection, and retention policies for data that cannot be recreated.
  Verify restore procedures rather than treating backup configuration as proof.
- Separate deployment and application administration, verify hosted CI and
  artifact promotion, resolve container findings or obtain scoped owner-approved
  exceptions, and assign incident response and rollback ownership.

## Enterprise retrieval mapping

The transferable pattern is **retrieve authorized evidence, generate a proposal,
validate citations, and let a person review it**. It does not require a vector
database. Praxis uses structured lexical retrieval, not a Bedrock Knowledge Base;
the [retrieval decision](adr/0020-structured-catalog-retrieval.md) remains in force.
The examples below are analogies, not implemented connectors or new inputs.

| Praxis input or operation | Enterprise analogue | Additional requirement |
| --- | --- | --- |
| Books: bibliographic metadata | Approved reference or standards catalog | Distinguish a reference listing from licensed full text; never infer unseen contents. |
| Projects: descriptions and technology metadata | Internal solution inventory or delivery case studies | Preserve ownership, source revision, access policy, and whether a solution is still supported. |
| Bytes: technical notes and experiments | Runbooks, troubleshooting notes, and engineering lessons | Track review status and freshness; retrieved procedures remain untrusted model context. |
| Museum: computing objects and descriptions | Asset or equipment inventory | Separate descriptive facts from current operational status and permitted use. |
| Manual JSON ingestion with provenance | Controlled import from approved systems of record | Define synchronization, deletions, permission changes, and source-version lineage; cloud indexes remain derived copies. |
| Read-only Gateway search and lookup | Authorization-enforcing retrieval API | Apply caller permissions before returning evidence, including direct ID lookup, not as a model-selected filter. |
| Three candidates and a selected brief | Evidence-backed options and a human-reviewed implementation proposal | Keep generated conclusions distinct from facts; do not automatically execute plans or create external work items. |

Preserve the source-to-citation boundary when adapting this workflow. If richer
documents eventually require chunks, retain a resolvable document/revision and
passage locator as well as access policy. Do not reuse the current record-ID
scheme as proof of document versioning or permission enforcement. Recheck
authorization when resolving citations and generating a brief; cached results
must not bypass revocation or expose another user's evidence.

Evaluate retrieval separately from generation: relevant authorized evidence,
missing/obsolete records, denied documents, conflicting sources, citation
resolution, unsupported claims, latency, and usage all need coverage. The
[evaluation guide](../evals/README.md) provides the current distinction between
retrieval relevance, citation provenance, and semantic quality. Extend local
fixtures before an approved paid comparison; a fluent answer is not a retrieval
pass, and a valid citation does not establish that a claim follows from it.

Richer owned text plus a measured lexical-retrieval gap could justify evaluating
semantic or hybrid retrieval through a superseding ADR. Record-count growth alone
does not justify that change. Licensing, access control, deletion, provenance,
and cost remain requirements regardless of the search technology. Memory stays
explicit personalization, not an authoritative enterprise knowledge store.

## Conditional production evolution

This logical diagram is a proposal, **not deployed topology**. Arrows show
request/data flow, not a claim that services share a network. The identity and
authorization changes above are prerequisites for every path.

```text
Browser -- approved identity provider
   |
   | verified identity at application boundary
   v
API Gateway -> API Lambda: membership, admission, ownership
                   |                         |
                   | recommendations         | selected brief
                   v                         |
          Scoped sessions + queue            |
                   |                         |
                   v                         |
          Worker: claim + retry policy       |
                   |                         |
                   +------------+------------+
                                | trusted user/organization context
                                v
                     AgentCore Runtime / Strands
                        |       |       |
                        |       |       +--> Scoped Memory reads
                        |       +----------> Guarded Bedrock inference
                        v
                 AgentCore Gateway: read-only tools
                        |
                 Authorization-enforcing retrieval
                        |
                        +--> Authorized shared/partitioned catalog
                        |
                        `..> ONLY IF a private source is required:
                             +-- Customer private network ----------+
                             | Read-only connector -> Private source |
                             +---------------------------------------+

API / worker / Runtime / tools -> Access-controlled logs and traces
                                 Retention, alerts, usage attribution
```

The dotted branch is conditional. If an approved source cannot be reached
through the existing managed-service path, place only the connector that needs
private reachability in the appropriate network. Its invocation path, DNS,
routes, source credentials, and supported service connectivity need a separate
validated design; the diagram does not select a particular endpoint mechanism.
Do not move the browser, identity service, or all managed services into a VPC
box merely to label the system “enterprise.”

Before approving that branch, document the source and traffic requirement,
authentication and record-level authorization, allowed destinations, failure
behavior, and recurring network cost. Verify denied routes as well as successful
reads. Private reachability does not prevent data leakage through an authorized
model request or an overly broad tool response.

If the requirement instead prohibits public service endpoints or requires
controlled outbound traffic from Runtime itself, assess that path independently.
Confirm service/region support, ingress and egress behavior, and cost before
proposing network changes. A private source connector alone does not satisfy
either requirement. No NAT gateway or private endpoint is provisioned by default.

## Approval boundary

Resolve the [residual-risk register](residual-risks.md), especially Memory
isolation, telemetry privacy, browser security, and duplicate paid work. Add
cross-user adversarial fixtures locally before requesting explicitly approved
metered load or model tests. Shared caches and evaluation datasets also need
scope checks; never turn one user's context into another user's evidence.

A multi-user proposal needs an ADR covering the chosen tenancy model, identity
propagation, authorization enforcement, costs, migration, and rollback. Private
networking is a separate requirement decision, not a substitute for data
authorization. No VPC, extra agent, write integration, or semantic knowledge
base is implied by supporting additional users.
