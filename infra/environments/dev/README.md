# Development environment

This independent OpenTofu root owns temporary Praxis application resources in
`us-east-1`. It stores state in the encrypted, versioned bootstrap S3 bucket and
uses native S3 state locking. Initialize it after the bootstrap stack:

```shell
make tofu-init-dev
```

All resources use the `praxis-dev` name prefix and inherit the required
`Project`, `Environment`, and `ManagedBy` tags. A coding agent may apply the
exact saved plan it generated, reviewed, and summarized. Teardown requires
explicit user approval for each run.

See `docs/infrastructure-operations.md` for the guarded plan, apply, and
teardown procedures. Teardown requires a separately reviewed saved destroy plan.

The agent image repository uses immutable tags, scan-on-push, S3-managed
AES-256 encryption, and a lifecycle policy that removes untagged images after
seven days and retains at most ten images. `force_delete` permits the guarded
development teardown target to remove the repository and its temporary images.

The source-data bucket holds reproducible copies of the four authoritative JSON
inputs. It uses an AWS-generated suffix for global name uniqueness, S3-managed
AES-256 encryption, bucket-owner enforcement, blocked public access, and a
TLS-only bucket policy. Versioning is intentionally disabled because source
history belongs in the sibling repository; `force_destroy` ensures development
teardown removes copied objects with the bucket.

The catalog table uses on-demand billing, a `record_id` partition key, and the
`kind-date-index` GSI defined in
`docs/adr/0002-dynamodb-catalog-access-patterns.md`. AWS-owned encryption is
enabled. Point-in-time recovery and deletion protection are intentionally off
because the table is a reproducible development copy and must not obstruct the
guarded teardown workflow.

The private catalog Lambda uses the reproducible Python 3.13 package built by
`make package-functions`. Its execution role can only read individual catalog
items, query the catalog GSI, and write to the function's seven-day log group.
The function has a 15-second hard timeout; its AWS client uses bounded connect,
read, and retry settings and stops new catalog reads with six seconds remaining
so it can return a safe structured error. The development account's concurrency
quota provides the execution ceiling, and no public invocation permission is
created.

The ingestion Lambda is also private and manually invoked. Its independent role
can read only the four expected source objects, scan and batch-write only the
catalog table, and write to its own seven-day log group. No bucket notification
or schedule can trigger ingestion unexpectedly.

The application API Lambda uses an independent deployment ZIP with locked
validation dependencies and no function URL. Its execution role can write only
to its seven-day log group and invoke the configured Runtime plus its stable
endpoint. A low-cost API Gateway HTTP API invokes it through payload format 2.0
on three explicit Cognito JWT-authorized application routes. The authorizer is
bound to the application user pool and public browser client. The default stage
deploys OpenTofu-managed route changes automatically; unauthenticated
declared-route requests return 401, and undeclared routes return 404 without
invoking the function. The Lambda validates the route, path identifiers, content
type, query parameters, and strict JSON body. It rejects decoded bodies over 16 KiB before
JSON parsing or Runtime invocation and limits goal text to 4,000 characters.
Session creation stores a pending session, sends one validated job
to an encrypted SQS queue, and returns 202 without waiting for model work. A
dedicated worker Lambda invokes Runtime with a deployment-owned single-user
actor, the generated UUIDv4 session, one 90-second SDK attempt, and a 120-second
Lambda timeout. It validates the complete Runtime response before writing ready
candidate data or a detail-free failed state. Success and error payloads use the
envelopes documented in `docs/api.md`; fixed machine-readable error codes remain
separate from safe display text. The API Lambda propagates a
valid client UUIDv4 correlation ID or uses API Gateway's request ID, returning
the selected value as response metadata and forwarding it as tracing baggage
without placing it in response bodies or prompts. Model, Gateway, tool,
timeout, and invalid-output failures share one fixed 503 envelope that omits
downstream exception details.

The session-create route has a burst limit of one and a steady rate of 0.1
requests per second. API Gateway rejects excess requests before Lambda
invocation, limiting accidental concurrent model work while leaving other
routes available for their own handler-specific limits.

API Gateway handles browser preflight requests and permits only the deployed
CloudFront HTTPS origin and the configured local development origin, which
defaults to `http://localhost:5173`. Only GET, POST, and OPTIONS plus the
authorization, content-type, and correlation headers are allowed. CORS is a
browser boundary and does not replace API authorization.

The production Vite bundle is stored in a disposable, encrypted S3 bucket with
all public access blocked. A CloudFront distribution reads it with signed origin
access control requests, redirects viewers to HTTPS, applies managed caching and
security-header policies, and returns `index.html` for unknown SPA routes. The
distribution uses its default certificate and domain rather than adding DNS or
certificate resources. OpenTofu manages hosting infrastructure but not asset
objects; `make deploy-frontend-dev CONFIRM=deploy-frontend-dev` performs the
explicit build, upload, and cache invalidation.

The default API stage writes structured access records to a dedicated
CloudWatch log group with seven-day retention. Records contain request IDs,
route templates, status, latency, and byte counts only; they omit bodies,
prompts, raw paths, caller identities, IP addresses, user agents, and error
text.

All project-owned CloudWatch log groups use service-managed encryption and
seven-day retention. AgentCore creates Runtime endpoint groups outside the AWS
provider's resource lifecycle, so an idempotent OpenTofu provisioner applies
the same retention to the `DEFAULT` and `stable` groups after endpoint changes.
The account-level `aws/spans` group is shared and remains outside this stack.

The Cognito Lite user pool is an admin-provisioned, single-user directory with
case-insensitive email sign-in, verified-email recovery, and no public
self-registration. OpenTofu manages no user or password, and deletion
protection remains inactive so guarded development teardown removes the pool.
The public browser client has no secret, permits only SRP and refresh-token
authentication, and uses one-hour access and ID tokens plus a seven-day refresh
token. Its non-secret identifier is available from the
`cognito_frontend_client_id` output. The API JWT authorizer is a separate
resource.

The AgentCore Gateway exposes an MCP endpoint protected by AWS IAM. Its service
role trust is restricted to AgentCore gateways in this account and region. The
catalog target advertises the four implemented read-only tools. OpenTofu
consumes the checked-in schema artifact generated from the strict Pydantic
contracts. The Gateway role can invoke only the catalog Lambda; it cannot invoke
ingestion or access DynamoDB directly. The Gateway accepts MCP versions
`2025-03-26`, `2025-06-18`, and `2025-11-25`; signed evidence captures remain
on `2025-03-26`, while the current Strands MCP client negotiates `2025-11-25`.

API, recommendation worker, Runtime, Gateway, catalog, and ingestion workloads
each use a distinct execution role with an OpenTofu-owned inline policy. The
configuration smoke suite reads the active role from every service and rejects
shared roles, unexpected bindings, and managed-policy attachments.

The AgentCore Runtime runs the digest-pinned Strands container with IAM inbound
authorization and public outbound networking. Its execution role can pull only
the agent image, invoke the configured Nova Pro model, retain Nova Lite and Nova
Micro as measured rollback models, invoke the catalog Gateway, read Memory only
for the application and verification actors, write only its generated Runtime
log groups, and submit ADOT traces to X-Ray. It has no direct access to catalog
storage or ingestion. The ADOT entrypoint exports evaluation-compatible Strands
spans correlated with AgentCore Runtime sessions to CloudWatch.

Every Runtime model request uses an immutable OpenTofu-managed Bedrock
Guardrail version. Its Classic-tier text prompt-attack filter blocks direct and
indirect instruction-override attempts at high strength. Output evaluation and
broad topic or harmful-content filters remain disabled to avoid screening valid
technical project domains and unnecessary guardrail charges. Strict schemas,
evidence validation, and tool allowlists remain independently authoritative.
Session timeouts limit idle development cost. During apply, OpenTofu runs the
MMDSv2 compatibility update documented in
`docs/adr/0004-agentcore-runtime-deployment.md` and fails unless the Runtime
returns to `READY` with MMDSv2 enabled. The named `stable` endpoint targets the
explicitly configured immutable Runtime version and does not follow `DEFAULT`;
new versions require a separate reviewed promotion.
The `smoke-runtime-auth-dev` target checks the deployed stable version and
proves a direct unsigned request is rejected before container dispatch.
