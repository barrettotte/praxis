# Infrastructure operations

Praxis separates durable bootstrap resources from the disposable development
environment. The user must run every apply and teardown command manually after
inspecting its saved plan; coding agents may run only read-only checks and
plans.

## Prerequisites

Install the pinned toolchain, authenticate the MFA-protected development
profile, and confirm the expected non-root identity:

```shell
make bootstrap
aws login --profile praxis-dev --region us-east-1
aws sts get-caller-identity --profile praxis-dev --region us-east-1
make tofu-init
```

Override the default profile with `AWS_PROFILE=<profile>` on any Make command
when necessary. Never commit OpenTofu state, plans, credentials, or the budget
notification address. Each plan target removes its previous saved plan before
contacting AWS, so a failed or expired login cannot leave an older artifact
that appears ready to apply.

## Bootstrap lifecycle

The bootstrap root uses local state and owns the encrypted, versioned S3 state
bucket and the annual cost budget. Set the notification address only in the
shell, create and inspect a saved plan, and then apply that exact plan:

```shell
export TF_VAR_budget_notification_email="you@example.com"
make tofu-plan-bootstrap
tofu -chdir=infra/bootstrap show bootstrap.tfplan
make tofu-apply-bootstrap CONFIRM=apply-bootstrap
```

Keep `infra/bootstrap/terraform.tfstate` while bootstrap resources exist. After
the first bootstrap apply, initialize the development root against its S3
backend:

```shell
make tofu-init-dev
```

Bootstrap teardown is exceptional and must happen only after the development
environment has been destroyed and its state is no longer needed:

```shell
make tofu-plan-destroy-bootstrap
tofu -chdir=infra/bootstrap show bootstrap-destroy.tfplan
make tofu-destroy-bootstrap CONFIRM=destroy-bootstrap
```

The final command deletes the versioned state bucket and budget. The bucket is
configured for forced deletion, so its state history is not recoverable after
teardown.

## Development lifecycle

For each development change, initialize the remote backend, save and inspect a
plan, and manually apply that exact artifact:

```shell
make tofu-init-dev
make tofu-plan-dev
tofu -chdir=infra/environments/dev show dev.tfplan
make tofu-apply-dev CONFIRM=apply-dev
```

Catalog seeding is a separate, explicit write operation. After the ingestion
Lambda is deployed, review the source path shown by `make help`, then upload the
four files and invoke one complete reconciliation:

```shell
make seed-dev CONFIRM=seed-dev
```

The target reads the authoritative files without modifying them, uploads the
four disposable copies, and saves the Lambda response under `build/`. Override
`SOURCE_DATA_DIR` only when the sibling repository is in another location.
Run the seed target after initial deployment and whenever a reviewed plan
replaces the disposable catalog table.

Run deployed smoke checks manually because they invoke metered AWS services.
The Gateway check signs standard MCP `tools/list` and `tools/call` requests with
the active profile, verifies all four catalog tools are discoverable, and
confirms that every catalog tool returns evidence. It writes credential-free,
deterministic captures to `docs/evidence/gateway-tools-list.json` and
`docs/evidence/gateway-tool-calls.json`. It also verifies excessive, malformed,
and unsigned requests are rejected and records only sanitized outcomes in
`docs/evidence/gateway-negative-calls.json`. Client-observed HTTPS latency and
JSON request/raw response body sizes for each successful tool call are recorded
in `docs/evidence/gateway-tool-metrics.json`:

```shell
make smoke-catalog-dev
make smoke-api-access-logs-dev
make smoke-api-cors-dev
make smoke-api-lambda-dev
make smoke-api-gateway-dev
make smoke-api-payload-dev
make smoke-api-throttling-dev
make smoke-gateway-dev
make smoke-agent-gateway-dev
make smoke-memory-dev CONFIRM=smoke-memory-dev
make smoke-runtime-dev
make smoke-runtime-sessions-dev
make smoke-runtime-traces-dev
```

The API Gateway check signs its declared-route requests with the active AWS
profile, requires an unsigned request to fail before Lambda invocation, and
validates one complete buffered Runtime response without recording candidate or
session content. The access-log check verifies the stage's privacy-safe JSON
schema and seven-day retention, then correlates an unsigned 403 request with its
delivered CloudWatch record without invoking Lambda. Initial log delivery can
take up to two minutes. The CORS check requires an exact frontend origin and
proves an unrelated origin receives no allow-origin header; API Gateway answers
both preflights without Lambda. The throttling check reads the deployed stage and requires the
session route to match the reviewed rate and burst values without invoking the
API. The payload check invokes the private API Lambda with a body over 16 KiB
and requires a fixed 413 response, proving validation stopped before Runtime.
The direct API Lambda check exercises the Runtime-backed success path through
authenticated Lambda invocation. The successful Runtime calls are metered.

The Memory check has a distinct confirmation because its first run creates one
typed preference and one typed decision for a dedicated smoke actor. A
deterministic preflight makes later runs read-only once both records exist. It
requires actor-scoped semantic retrieval, exercises the catalog-identifier
rejection boundary, and writes only sanitized counts and kinds to
`docs/evidence/agentcore-memory.json`.

The agent-to-Gateway command uses the same SigV4 Strands MCP transport as the
AgentCore Runtime, invokes the configured Bedrock model with the discovered
tools, and requires at least one Gateway tool call plus exactly three
schema-valid candidates with an evidence citation on each. It writes sanitized
counts and tool-call metadata to
`docs/evidence/strands-gateway-tools-list.json` and
`docs/evidence/strands-gateway-agent-run.json`. Override its deterministic smoke
prompt with `PROMPT='your goal'` when needed.

The Runtime command signs `InvokeAgentRuntime` with the active AWS profile,
targets the named `stable` endpoint, and uses a new Runtime session ID. It
requires exactly three schema-valid cited candidates and at least one Gateway
tool call. The command prints endpoint-resolution and invocation stages and
enforces a three-minute wall-clock timeout. Its credential-free capture is
written to `docs/evidence/agentcore-runtime-invocation.json`; override the prompt with
`PROMPT='your goal'` or the deadline with `RUNTIME_SMOKE_TIMEOUT_SECONDS=seconds`
when needed.

The Runtime session check invokes the stable endpoint with two distinct session
IDs and catalog topics whose expected evidence does not overlap. It fails if
either response is invalid or their citations overlap, and writes a sanitized
capture without session IDs to
`docs/evidence/agentcore-runtime-session-isolation.json`.

## Runtime traces

CloudWatch Transaction Search must accept OTEL spans before Runtime trace
verification. This is a one-time account and Region setting. In the CloudWatch
console for `us-east-1`, open **Settings**, choose **X-Ray traces**, edit
**Transaction Search**, enable it for X-Ray users, and retain the free 1% trace
indexing setting. Wait until **Ingest OpenTelemetry spans** reports enabled.
AWS documents the same console procedure in its
[AgentCore observability guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html#enabling-transaction-search).

After deploying the ADOT-instrumented image and promoting its immutable Runtime
version, invoke and verify one evaluation-compatible trace:

```shell
make smoke-runtime-traces-dev
```

The command waits up to three minutes for ADOT delivery to the named Runtime
endpoint's CloudWatch `spans` stream, requires a session-correlated
`strands.telemetry.tracer` `invoke_agent` span for the deployed Runtime, and
writes sanitized metadata to
`docs/evidence/agentcore-runtime-traces.json`. It never records prompts,
responses, session IDs, trace IDs, span IDs, account IDs, or resource ARNs.
Override only the delivery wait with `RUNTIME_TRACE_TIMEOUT_SECONDS=seconds`.

## Deployed evaluation

Run the canonical ten-case evaluation manually after the stable endpoint and
its Strands traces are verified:

```shell
make eval-runtime-dev
```

This command performs ten metered Runtime invocations with isolated session IDs
and waits for a correlated CloudWatch trace after each invocation. It resolves
the endpoint qualifier, immutable Runtime version, and digest-pinned container
from OpenTofu state, then writes a versioned result under
`evals/project-recommendations/results/`. The artifact excludes AWS account,
resource, session, trace, and span identifiers. Use
`RUNTIME_EVAL_TRACE_TIMEOUT_SECONDS=seconds` to change the per-case trace wait.
The command reads the model ID and image digest from the immutable Runtime
version served by the endpoint, preventing manual metadata mismatches.

### Model selection and rollback

ADR 0005 defines Nova Lite (`amazon.nova-lite-v1:0`) as the default and Nova
Micro as the measured rollback model. Stage any future comparison model without
changing checked-in defaults by creating a saved plan override:

```shell
TF_VAR_agent_model_id=MODEL_ID make tofu-plan-dev
tofu -chdir=infra/environments/dev show dev.tfplan
make tofu-apply-dev CONFIRM=apply-dev
```

The stable endpoint remains on its pinned version while the new Runtime version
is staged. Inspect the immutable versions and select the highest version that
is `READY`, uses the intended model and image digest, and reports MMDSv2 as
`true`:

```shell
make inspect-runtime-versions-dev
```

Promote the reviewed version while retaining both overrides in the plan:

```shell
TF_VAR_agent_model_id=MODEL_ID \
  TF_VAR_agent_runtime_endpoint_version=VERSION \
  make tofu-plan-dev
tofu -chdir=infra/environments/dev show dev.tfplan
make tofu-apply-dev CONFIRM=apply-dev
make eval-runtime-dev
```

After capturing the comparison result, either adopt the measured model and
version in the checked-in defaults through a reviewed change, or restore the
current defaults with a normal plan and apply:

```shell
make tofu-plan-dev
tofu -chdir=infra/environments/dev show dev.tfplan
make tofu-apply-dev CONFIRM=apply-dev
```

Never change the default based on subjective output review alone. Compare
reliability, deterministic quality, evidence coverage, tool trajectory, latency,
and tokens on the canonical suite and record the decision in an ADR.

## Agent image publication

Build the AgentCore Runtime image, then preview its immutable ECR destination:

```shell
make agent-image
make preview-agent-image-dev
```

The image must be ARM64 and carry an OCI revision label matching `HEAD`. The
preview derives the ECR repository from OpenTofu state, uses the full Git commit
as the immutable `git-<sha>` tag for a clean worktree, and reports whether that
tag already exists. Images built with uncommitted inputs receive a warning and
an immutable `dirty-<image-id>` tag derived from their local OCI content rather
than a reproducible Git revision. After reviewing it, manually perform the
write:

```shell
make push-agent-image-dev CONFIRM=push-agent-image-dev
```

The push uses the active AWS profile only to obtain a short-lived ECR login,
logs the container client out afterward, and prints the registry digest. Runtime
infrastructure must reference that digest rather than a mutable local image
name.

The development Runtime configuration pins the published digest. Review its
execution-role policy, container URI, environment variables, session timeouts,
and the apply-time MMDSv2 compatibility update in the saved OpenTofu plan before
applying it. The apply waits for the Runtime to return to `READY` and verifies
that MMDSv2 is enabled. The compatibility update uses the same temporary AWS
profile as OpenTofu and performs no invocation.

The named `stable` Runtime endpoint uses the explicit
`agent_runtime_endpoint_version` value. Runtime configuration changes create a
new provider-managed version followed by an MMDSv2-enabled version, while the
endpoint remains on its prior target. Verify the replacement Runtime version is
`READY` with MMDSv2 enabled, then promote that version in a separate reviewed
plan. Never point application callers at the automatically moving `DEFAULT`
endpoint.

Before an extended pause or project completion, review and apply a saved
destroy plan:

```shell
make tofu-plan-destroy-dev
tofu -chdir=infra/environments/dev show dev-destroy.tfplan
make tofu-destroy-dev CONFIRM=destroy-dev
```

Development teardown removes all resources tracked by the development root,
including ECR repositories and their images. It intentionally preserves the
bootstrap S3 bucket, remote state history, cost budget, and local bootstrap
state because those belong to the independent bootstrap root.

Verify that only bootstrap resources remain:

```shell
tofu -chdir=infra/environments/dev state list
tofu -chdir=infra/bootstrap state list
```

The first command must print no managed resources. The second must continue to
list the state-bucket controls and budget until the bootstrap stack is
explicitly destroyed.
