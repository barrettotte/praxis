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
make smoke-gateway-dev
make smoke-agent-gateway-dev
```

The final command uses the same SigV4 Strands MCP transport intended for the
AgentCore Runtime, invokes Nova Micro with the discovered tools, and requires at
least one Gateway tool call plus exactly three schema-valid candidates with an
evidence citation on each. It writes sanitized counts and tool-call metadata to
`docs/evidence/strands-gateway-tools-list.json` and
`docs/evidence/strands-gateway-agent-run.json`. Override its deterministic smoke
prompt with `PROMPT='your goal'` when needed.

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
