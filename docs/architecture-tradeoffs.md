# Architectural tradeoffs

This guide summarizes accepted decisions for the single-user deployment. It
does not introduce a new architecture or certify production readiness. The
[README diagram](../README.md#architecture) shows component boundaries;
linked ADRs retain decision rationale and measurements.

| Choice | Benefit | Cost or limitation | Revisit when |
| --- | --- | --- | --- |
| [Serverless, single agent, no VPC](adr/0001-initial-architecture.md) | Disposable infrastructure without an always-running application server or NAT gateway. | Cold starts, managed-service integration, and AWS coupling; IAM protection is not a general egress restriction. | A measured availability, private-connectivity, or workflow requirement justifies a different topology. |
| [API boundary and queued recommendations](adr/0018-asynchronous-recommendation-sessions.md) | Cognito-subject-owned sessions; slow generation does not occupy the browser's initial HTTP request. | SQS, polling, failure state, and duplicate-delivery handling add complexity. Retries may repeat paid work. Brief selection remains synchronous. | Brief latency outgrows its deadline or duplicate processing becomes material. |
| [Buffered, non-conversational output](adr/0022-bounded-non-conversational-workflow.md) | Validate complete candidates and briefs before display; no accumulated chat context or summarization call. | Users wait without token-level progress; no conversational refinement. | Product requirements and measurements justify streaming or retained dialogue. |
| [Structured catalog retrieval](adr/0020-structured-catalog-retrieval.md) | Reproducible retrieval over owned JSON, without embeddings, remote enrichment, or a Bedrock Knowledge Base. | Sparse metadata and lexical matching limit semantic recall. A book title is not evidence of its full contents. | Richer owned text and retrieval evaluations justify semantic indexing and its cost. |
| [Bounded DynamoDB queries](adr/0002-dynamodb-catalog-access-patterns.md) | Stable evidence lookup and deterministic filters without another search service. | Filters can read nonmatching items; evaluated-item limits can omit matches as the catalog grows. | Read consumption, retrieval coverage, or latency exceeds the documented bounds. |
| [Strict Gateway contracts and read-only tools](adr/0003-agentcore-tool-contracts.md) | Separate model reasoning from authorized tool execution; validate citations against retrieved evidence. | Gateway discovery cannot express every runtime constraint. Citations establish provenance, not generated truth or feasibility. External writes are outside scope. | Contract or retrieval needs change; write workflows would require an explicit product-scope decision. |
| [Explicit Memory records](adr/0006-explicit-agentcore-memory-records.md) | Preferences and decisions remain separate from catalog facts and conversation transcripts; Runtime cannot write them. | Personalization requires explicit record management. The application uses a deployment-wide Memory actor, despite subject-owned sessions. | Before adding another user, design and verify authenticated per-user Memory isolation. |
| [Measured Nova Pro default](adr/0025-nova-pro-default-model.md) | Better structured-output reliability in the controlled comparison; model ID stays configurable. | More expensive inference than Lite; valid output does not guarantee a useful brief. | A controlled evaluation supports another default, not merely a cheaper token price. |
| [Scoped prompt-attack guardrail](adr/0026-versioned-prompt-attack-guardrail.md) | Screens the marked user goal while retaining legitimate technical subject matter. | Adds latency/cost; does not classify all retrieved context or ensure output safety. Independent schema, tool, and evidence checks remain necessary. | Measured attacks or false positives justify a reviewed policy change. |
| [Private S3 origin and CloudFront](adr/0019-private-s3-cloudfront-frontend.md) | Static HTTPS delivery without an application origin server. | Publication and invalidation are separate operations; browser code cannot keep secrets. CORS is not authorization. | A demonstrated rendering, domain, or edge-control requirement changes hosting needs. |

## Assurance and operating limits

The [threat model](threat-model.md) and [residual-risk register](residual-risks.md)
describe gaps these choices do not resolve: container advisories, telemetry
privacy, tenancy, duplicate inference, and incomplete deployed verification.
Documenting a tradeoff does not accept a security exception.

Use [local checks and existing evaluation evidence](../evals/README.md#cost-and-token-controls)
before requesting paid measurements. Budget notifications and per-request bounds
are not a hard spending cap. A proposed change needs an ADR when it changes
component, trust, data, or deployment boundaries; it also needs corresponding
diagram updates and verification appropriate to the changed behavior.
