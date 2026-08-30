# Development environment

This independent OpenTofu root owns temporary Praxis application resources in
`us-east-1`. It stores state in the encrypted, versioned bootstrap S3 bucket and
uses native S3 state locking. Initialize it after the bootstrap stack:

```shell
make tofu-init-dev
```

All resources use the `praxis-dev` name prefix and inherit the required
`Project`, `Environment`, and `ManagedBy` tags. Coding agents may plan and
inspect this environment, but the user must run every apply or destroy command
manually.

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

The AgentCore Gateway exposes an MCP endpoint protected by AWS IAM. Its service
role trust is restricted to AgentCore gateways in this account and region. The
catalog target advertises the four implemented read-only tools. OpenTofu
consumes the checked-in schema artifact generated from the strict Pydantic
contracts. The Gateway role can invoke only the catalog Lambda; it cannot invoke
ingestion or access DynamoDB directly. The Gateway accepts MCP versions
`2025-03-26`, `2025-06-18`, and `2025-11-25`; signed evidence captures remain
on `2025-03-26`, while the current Strands MCP client negotiates `2025-11-25`.

The AgentCore Runtime runs the digest-pinned Strands container with IAM inbound
authorization and public outbound networking. Its execution role can pull only
the agent image, invoke the configured Nova Micro model and catalog Gateway,
write Runtime logs, and submit ADOT traces to X-Ray. It has no direct access to
catalog storage or ingestion. The ADOT entrypoint exports evaluation-compatible
Strands spans correlated with AgentCore Runtime sessions to CloudWatch.
Session timeouts limit idle development cost. During apply, OpenTofu runs the
MMDSv2 compatibility update documented in
`docs/adr/0004-agentcore-runtime-deployment.md` and fails unless the Runtime
returns to `READY` with MMDSv2 enabled. The named `stable` endpoint targets the
explicitly configured immutable Runtime version and does not follow `DEFAULT`;
new versions require a separate reviewed promotion.
