# Architecture

Praxis is a serverless, single-user project recommender in `us-east-1`. The
[README diagram](../README.md#architecture) shows the components and data flows.
AgentCore integration is a project objective, not a requirement imposed by catalog size.

## Application boundary

CloudFront serves React/TypeScript assets from a private S3 origin. Cognito
provides browser authentication; API Gateway validates JWTs before invoking the
API Lambda. Browsers receive neither AWS credentials nor direct Runtime access.

Recommendations and briefs use SQS and a worker Lambda so model execution does not need to
fit within an HTTP request. The API creates an expiring, subject-owned session;
the browser polls for ready or failed status. Selection sends identifiers only:
the API validates ownership and queues a separate brief job. The worker reloads
the owned candidate, goal, and evidence and persists the buffered brief for polling. Expiry and ownership are checked on reads, independent of
DynamoDB's asynchronous TTL deletion. See [API contracts](api.md).

## Agent and data

One Strands agent runs on Bedrock AgentCore Runtime with Nova Pro as the configured
default and one model-facing structured-output contract. Other models require
explicit evaluation before support; configuration alone does not establish
compatibility or useful output.

AgentCore Gateway exposes four read-only Lambda tools. Strict Pydantic contracts
remain authoritative when Gateway discovery schemas cannot express every bound.
Generated tool schemas are checked for drift locally. Local development binds the
same tools to an in-memory catalog and shares the deployed generation pipeline. An invocation-scoped ledger
rejects conflicting facts and citations not present in retrieved evidence.

The four source JSON files remain authoritative and read-only. S3 and DynamoDB
copies are disposable. DynamoDB uses `record_id` as its primary key and
`kind-date-index` for bounded queries; lexical matching and ranking happen in
application code. Filter expressions do not reduce evaluated-item read costs.
There is no semantic Knowledge Base or external content enrichment. Catalog
metadata supplies related resources, not proof of generated technical claims.

There is no cross-session personalization store. The application retains
expiring, subject-owned recommendation sessions for polling and brief selection.
The catalog is shared; additional users require an explicit catalog authorization
design. See [Runtime](agent-runtime.md).

## Deployment and constraints

OpenTofu manages on-demand services without a VPC, NAT gateway, provisioned
capacity, external write tools, or multi-agent orchestration. Managed services
reduce server operations but add cold starts, integration work, and AWS coupling.

Runtime uses a non-root ARM64 minimal image built with locked Python
dependencies. CPython is compiled from checksum-verified source on Ubuntu 24.04;
the shell-free serving rootfs contains libraries from that same distribution,
including vendor-maintained glibc security updates. Optional database,
terminal and GUI modules are excluded; UUID generation uses Python's fallback.
Base updates require native-import, TLS, startup, and vulnerability checks.
Deploy by immutable image digest. Development uses the automatically tracking
`DEFAULT` endpoint, without manual version selection or promotion. Pause submissions
and drain queued work during deployment; verify READY and MMDSv2 after the
provider compatibility update before resuming. IAM authorization still protects public-network
Runtime and Gateway endpoints.

Buffered output simplifies schema validation but provides no token streaming.
Retries can repeat paid inference, and budget alerts are not a spending cap.
Use non-sensitive inputs and review [security limits](security.md) and
[operating procedures](infrastructure-operations.md) before deployment.
