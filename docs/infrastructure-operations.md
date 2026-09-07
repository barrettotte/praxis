# Infrastructure operations

Praxis separates durable bootstrap resources from the disposable development
environment. A coding agent may apply the exact saved plan it generated,
reviewed, and summarized. Configuration or state changes require a regenerated
plan and another review. Teardown and other destructive operations require
explicit user approval for each run; other AWS mutations remain manual unless
the user explicitly requests them.

Smoke commands print concise outcomes; temporary HTTP bodies and tokens are removed
on exit. Review image scan findings before explicitly confirming publication.

## Prerequisites

The development root requires an explicit `agent_image_digest`. Set it in ignored
`infra/environments/dev/deployment.auto.tfvars` using the adjacent example file.
The `DEFAULT` endpoint follows Runtime updates automatically. Pause submissions
and drain queued work before applying; verify READY and MMDSv2 before resuming.
Never reuse a saved plan after changing configuration or state.

`make package-functions` and `make package-api-lambda` use the same Lambda packager
with explicit handler profiles. Each ZIP includes its locked SDK and validation
dependencies, passes imports without development site-packages, and uses normalized
timestamps and file ordering for reproducible hashes.

### Account access

The personal development account uses an MFA-protected IAM user in the
`praxis-dev` group with `SignInLocalDevelopmentAccess` and
`AdministratorAccess`. Do not create access keys or use root for routine work.
This broad operator permission is a development convenience, not the permission
model for application roles. Keep root MFA-protected.
Use `aws login --profile praxis-dev --region us-east-1` for short-lived
credentials and repeat it when the session expires. Verify the expected
non-root identity before planning or applying.

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

Run deployed checks through suites that keep non-inference, metered inference,
and mutating operations visibly separate:

| Command | Coverage | Model inference |
| --- | --- | --- |
| `make smoke-dev` | Frontend delivery, private origin, anonymous API rejection, CORS | No |
| `make smoke-dev SUITE=tools` | Gateway authorization, discovery, catalog search/lookup | No |
| `make smoke-dev SUITE=api` | Authenticated recommendation and brief; requires access token | Yes |
| `make smoke-dev SUITE=runtime` | Direct Runtime diagnostic; optional `VERIFY_RUNTIME_TRACES=true` | Yes |
| `make smoke-agent-container` | Network-isolated local image health | No |

Smoke checks verify representative connections and access boundaries, not every
input permutation or infrastructure setting. Use local tests for validation,
reviewed OpenTofu drift plans for configuration, and bounded log inspection for
delivery problems. None of these substitutes for the others.

To obtain the short-lived Cognito access token, sign in through the Praxis
frontend, open the browser developer console, and run:

```javascript
const tokenKey = Object.keys(sessionStorage).find(
  (key) =>
    key.startsWith("CognitoIdentityServiceProvider.") && key.endsWith(".accessToken"),
);
if (!tokenKey) throw new Error("Sign in to Praxis before retrieving a token.");
copy(sessionStorage.getItem(tokenKey));
```

Load the copied token into the shell without placing it in command history. For
zsh:

```zsh
read -rs 'PRAXIS_ACCESS_TOKEN?Cognito access token: '
printf '\n'
export PRAXIS_ACCESS_TOKEN
```

For Bash:

```bash
read -rsp "Cognito access token: " PRAXIS_ACCESS_TOKEN
printf '\n'
export PRAXIS_ACCESS_TOKEN
```

Run `make smoke-dev SUITE=api`, then remove the token with
`unset PRAXIS_ACCESS_TOKEN`. Use the Cognito access token rather than the ID
token. Access tokens expire after one hour; sign in again when the token is no
longer accepted. Do not store a token in `.env` or commit it.

The API smoke script removes the token from its child-process environment and
passes it to `jq` over stdin to build a private temporary curl configuration;
it is not a command-line argument. The configuration is removed on normal exit
or a trapped failure. Do not run authenticated scripts with `bash -x`, curl
verbose/trace options, or AWS debug logging. See
[credential isolation and trace limits](agent-runtime.md#credential-isolation)
before sharing logs or evaluation captures.

Run `./scripts/smoke/smoke-dev.sh --help` for the same suite list. Narrow
scripts in `scripts/smoke/` remain available for diagnosing one failed check,
but they are not separate Make targets.

## Frontend deployment

OpenTofu creates the private frontend bucket, CloudFront origin access control,
distribution, and exact API CORS origins. Static files remain a separate,
explicit release operation. After applying the reviewed infrastructure plan,
build with the deployed public identifiers and publish the bundle:

```shell
make deploy-frontend-dev CONFIRM=deploy-frontend-dev
make smoke-dev
```

The deployment target synchronizes `frontend/dist/` into the private bucket and
invalidates the CloudFront distribution. It never embeds AWS credentials,
passwords, tokens, or other secrets. Retrieve the browser URL at any time with:

```shell
AWS_PROFILE=praxis-dev tofu -chdir=infra/environments/dev output -raw frontend_url
```

The default smoke checks application-shell and SPA delivery, direct S3 rejection,
anonymous API rejection, and allowed/denied CORS preflights. It submits no valid goal.
The tools suite signs MCP discovery and a catalog search/lookup round trip.
The API suite checks one pending-to-ready recommendation and selected brief,
plus safe rejection responses. It does not exercise every tool or response permutation.

`make check` injects transport timeouts and throttling errors into the API,
worker, and catalog adapters. Expected worker failures become a safe `failed`
session and are acknowledged; brief failures return 503 while preserving the
stored candidates. Catalog storage failures are retryable, and its remaining-time
guard rejects work before accessing storage. The browser stops pending-session
polling after 60 attempts and does not automatically retry POST requests on 429.
These are deterministic failure tests, not live Lambda saturation or hard-timeout
experiments. A hard worker termination cannot write a failed status; its SQS
message remains subject to redelivery and dead-letter handling, and the browser
can reach its polling limit while the stored session still says `pending`.

The worker emits one `recommendation_delivery` application log per completed
handler attempt using Python logging and Lambda's configured JSON log format.
Its custom fields are `outcome` (`ready`, `failed`, or `retry`) and elapsed
`duration_ms`. `ready` means candidates were stored; `failed` means a safe failure
state was stored and the message is acknowledged. `retry` is ERROR-level and
means an exception escaped; SQS redelivery/dead-letter policy determines what
happens next. Other outcomes are INFO-level. Lambda supplies invocation metadata;
the application record omits goals, subjects, session IDs, headers, results,
and exception text. It does not change root logging or dependency verbosity.
Hard termination can prevent this event, and SDK or platform exception records
are outside its privacy contract. Use invocation metadata to investigate rather
than enabling payload logging. Local tests verify these fields and unchanged
exception propagation; deployed log capture requires publishing the API/worker ZIP.

The API Lambda emits one `api_request` event with `outcome`, `status_code`, and
`duration_ms`. Returned responses have outcome `responded`; status below 400 is
INFO, 4xx is WARNING, and 5xx is ERROR. An escaping exception is ERROR with
`unhandled_error` and a null status, not a claim that an HTTP response was sent.
The wrapper returns responses unchanged and preserves exception propagation.
It does not log request/response bodies, routes, identity, headers, correlation
IDs, or exception details. Use Lambda invocation metadata for investigation and
API Gateway access logs for route-level metadata. Rejections before Lambda do
not produce this application event; hard termination may also prevent it.
As with worker events, this contract does not sanitize platform or SDK logs.

The catalog Lambda emits one `catalog_request` event with `outcome` and
`duration_ms`, including failures during configuration or SDK setup. Success is
INFO; `INVALID_ARGUMENTS` and `NOT_FOUND` are WARNING; `TIMEOUT`,
`DEPENDENCY_FAILURE`, and `INTERNAL_ERROR` are ERROR. These are the existing
normalized tool error codes, not provider messages. The event excludes tool
arguments, tool names, evidence IDs/records, and exception text. Both direct
invocations and Gateway calls use this Lambda boundary. Logging preserves
the existing response and error conversion; hard termination and SDK/platform
diagnostics have the same limitations described above. Build the catalog and
ingestion artifact with `make package-functions`; deployed verification remains
separate from local packaging and tests.

The ingestion Lambda emits one `catalog_ingestion` event with `outcome`,
`duration_ms`, and aggregate `records_accepted`, `records_written`,
`records_deleted`, and `records_rejected`. `updated` is INFO and means the
snapshot and report completed; `rejected` is WARNING and means validation
prevented snapshot replacement. `error` is ERROR and preserves the escaping
exception. Without a completed report, counts are null: a failed write or report
operation may already have changed some records. This is not a rollback or
transaction guarantee. Source names, paths, records, validation details, and
exception text are omitted from the application event. Lambda responses and
stored reports retain their existing contract. Hard termination may prevent
logging, and platform/SDK diagnostics remain outside this privacy contract.

### Operational alarms

Operational alarm definitions live in `infra/environments/dev/alarms.tf`. The
HTTP API alarm evaluates the API-wide `5xx / Count` percentage over five minutes:
at least five requests and a rate of 5% or more trigger the alarm. Missing data
and periods with fewer than five requests do not breach. This is a development
noise threshold, not an availability SLO: a single failed low-volume request can
go unalerted. API polling and unauthorized requests are also in the denominator.
Direct Lambda checks and asynchronous worker failures are outside this metric;
consult the status logs and worker diagnostics separately. No new custom or
detailed route metrics are enabled. CloudWatch alarm charges may apply.

Operational alarms use a development-owned SNS topic restricted to the exact
API alarm and account. Supply `TF_VAR_budget_notification_email` for development
plans as well as bootstrap plans, using the same recipient. To reuse the single
recipient recorded in private local bootstrap state without printing it:

```shell
export TF_VAR_budget_notification_email="$(jq -er '[.resources[] | select(.type == "aws_budgets_budget" and .name == "mvp") | .instances[].attributes.notification[].subscriber_email_addresses[]] | unique | if length == 1 then .[0] else error("Expected one budget recipient") end' infra/bootstrap/terraform.tfstate)"
make tofu-plan-dev
```

Run from the repository root with shell tracing disabled. If bootstrap state is
unavailable, supply the known budget recipient privately instead. Never commit
the address, state, or saved plan. After the reviewed plan is applied, open the
SNS subscription email and choose **Confirm subscription**. Then verify the
subscription and, with separate approval, notification delivery; a successful
apply alone is insufficient. Confirm before teardown: the provider cannot
individually unsubscribe a pending email subscription, though deleting its
development topic removes associated subscriptions. No automatic remediation
or teardown action is configured. See the
[notification boundary](infrastructure-operations.md).

The bootstrap's unfiltered annual $10 budget retains actual-spend notifications
at 50% and 100%; it includes other account workloads, has reporting delay, and
does not impose a spending cap. It is not a daily anomaly detector. Budget email
delivery and operational SNS notifications are independent.

References: [HTTP API metrics](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-metrics.html)
and [alarm missing-data behavior](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/alarms-and-missing-data.html).

### Operations dashboard

`infra/environments/dev/dashboard.tf` defines the `praxis-dev-operations`
CloudWatch dashboard. After a reviewed plan is applied, find it under CloudWatch
Dashboards using `tofu output -raw operations_dashboard_name` from the development
root with `AWS_PROFILE=praxis-dev`. Definition validation is not proof that live
panels contain data; verify against existing activity before declaring it ready.

The one-hour default view shows Lambda duration p95, model input/output token
sums, Lambda execution errors, catalog invocations, and aggregate API response
statuses. Important interpretation boundaries:

- Lambda duration measures each component, not browser-to-result latency.
- Bedrock tokens cover every caller of the configured model in the account and
  Region, including local runs. They are not project-attributed or a billing report.
- Lambda errors exclude handled 503 responses; the API status panel includes
  them using structured `api_request` records. Pre-handler failures remain in
  the Lambda error panel; API Gateway rejections are not API handler responses.
- Catalog invocations include direct checks and failed calls. They exclude local
  agent tools and are not a count of model-selected tools or per-tool operations.
- Missing data is not a zero-error result. No synthetic traffic is necessary
  merely to populate charts; select an existing activity window.

The dashboard uses existing metrics and one Logs Insights aggregate query, with
no new custom metrics or content logging. The query displays only counts grouped
by status and outcome, never raw log messages. Dashboard and query charges may
apply; keep the range short, disable console auto-refresh, and close the dashboard
when finished. Query execution and rendered-panel checks remain separate from
local template validation.

Sources: [CloudWatch dashboard syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Dashboard-Body-Structure.html)
and [Bedrock runtime metrics](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-runtime-metrics.html).

## Runtime diagnostic

`make smoke-dev SUITE=runtime` invokes one fresh session through the development
endpoint and validates its candidates, citations, and tool counts. Override its prompt with `PROMPT='your goal'` or
its wall-clock deadline with `RUNTIME_SMOKE_TIMEOUT_SECONDS=seconds`.

## Runtime traces

`runtime_tracing.tf` configures managed `InvokeAgentRuntime` service-span delivery
separately from the container's ADOT application spans. It uses a `TRACES` source
and `XRAY` destination without enabling `APPLICATION_LOGS` or `USAGE_LOGS`.
See [AWS Runtime service-span documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html).
Configuration validation alone does not verify service support, successful
delivery, or the worker-to-Runtime parent chain; check deployed spans before
claiming complete linkage.

Catalog application spans read `_X_AMZN_TRACE_ID` from the Lambda runtime on
each invocation. They accept only valid trace/parent IDs with an explicit
sampling decision, ignore extension fields, and never extract context from tool
arguments. Missing or invalid metadata starts an independent trace. Unsampled
parents produce no recorded catalog span; this is not itself an export failure.
See [trusted trace propagation](agent-runtime.md).

Gateway service tracing is managed by `gateway_tracing.tf`: a `TRACES` delivery
source, an `XRAY` destination, and their delivery connection. This is separate
from client-side MCP instrumentation and requires existing Transaction Search
configuration. It does not enable Gateway `APPLICATION_LOGS`, change indexing,
or create another log group. Trace ingestion remains usage-based.
See [AWS trace-delivery setup](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html).
Deployment and retained service spans must be verified independently; enabling
delivery does not automatically make catalog application spans inherit a parent.

For collector-exported Lambda spans, inspect the confirmed Transaction Search
log group **`aws/spans` (no leading slash)**. It is distinct from the
resource-specific AgentCore Runtime span log group. X-Ray summary search only
covers the configured indexed percentage, so an empty summary result alone is
not evidence of export failure. Use a bounded time window and event limit:

```sh
aws logs filter-log-events --profile praxis-dev --region us-east-1 \
  --log-group-name aws/spans \
  --start-time START_EPOCH_MS --end-time END_EPOCH_MS \
  --filter-pattern '"praxis.catalog.request"' --limit 2 --no-paginate
```

Replace the timestamp placeholders with the invocation window. Do not increase
indexing or repeat model calls just to populate summary search. See
[AWS span storage documentation](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search-ingesting-span-log-groups.html).
X-Ray conversion can alter the stored representation: API spans were observed
with an empty top-level `name`, identity retained in `_aws.xray.name`, and
HTTP 4xx mapped to stored ERROR status. The application span contract below
describes the SDK output before that conversion.

API and worker handlers create internal OpenTelemetry spans using the active
provider, without configuring an exporter or extracting browser trace headers:

| Span | Attributes | ERROR status |
| --- | --- | --- |
| `praxis.api.request` | `praxis.outcome`: `responded` or `unhandled_error`; `http.response.status_code` only when a response exists | Returned 5xx or escaping exception |
| `praxis.worker.delivery` | `praxis.outcome`: `ready`, `failed`, or `retry` | Stored failure or escaping exception |
| `praxis.catalog.request` | `praxis.outcome`: `success` or a normalized catalog error code | Any failed tool request, including invalid arguments |

Other outcomes retain UNSET status. Span timestamps supply duration; automatic
exception events and status descriptions are disabled. No request/response
content, identity, route, or diagnostic text is attached. Existing application
logs and exception/retry behavior are unchanged. A stored worker failure is an
ERROR span even though its acknowledged-delivery log is INFO. These contracts
do not scrub dependency spans or platform diagnostics, and hard termination
can prevent span completion.

The worker Runtime adapter forwards the active OpenTelemetry W3C
`traceparent` through the SDK's `traceParent` parameter for recommendations and
briefs, plus an equivalent X-Ray `traceId` header for the AWS service boundary.
Both representations preserve the same trace, parent, and sampling flag and are
omitted when no valid context exists. It does not copy incoming browser
headers, vendor `tracestate`, or arbitrary baggage; the existing encoded
`praxis.correlation_id` baggage remains separate.

The API adds active server-generated `traceparent` as an SQS String message
attribute, leaving the job body unchanged. The single-record worker uses that
validated identity as its remote parent, preserving sampling without accepting
vendor state or baggage. Absent or malformed metadata starts an independent
trace; it neither invalidates the job nor inherits another delivery's context.
See [trusted trace propagation](agent-runtime.md).

The Lambda package includes a locked SDK and HTTP/protobuf exporter. Its
application-only provider is enabled by `PRAXIS_LAMBDA_TRACING=true` inside Lambda;
without that opt-in, handlers use the existing active provider. It synchronously
hands spans to `127.0.0.1:4318` with a 2-second exporter timeout and does not
inherit proxy/netrc settings or arbitrary exporter headers. No automatic library
instrumentation or metrics are enabled. The provider requires a collector
extension. OpenTofu attaches a pinned collector-only layer to API, worker, and
catalog, with only `xray:PutTraceSegments` and `xray:PutTelemetryRecords` added to
their execution roles. The packaged `collector.yaml` accepts loopback OTLP and
exports directly to X-Ray; remote export latency can delay the local response.
There are no metrics, batch processors, or debug payload exporters.
Ingestion shares the ZIP but does not enable tracing or attach the extension.
End-to-end linkage verification remains pending.
Local tests exercise queue propagation and both Runtime call paths without AWS.

The catalog handler also uses the active provider but does not extract context
from tool arguments or assume Gateway forwards a parent. Its local span contract
is verified separately; a deployed Runtime-to-Gateway-to-catalog parent chain is
not yet established.

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
make smoke-dev SUITE=runtime VERIFY_RUNTIME_TRACES=true
```

The command waits up to three minutes for ADOT delivery to the named Runtime
endpoint's CloudWatch `spans` stream, requires a session-correlated
`strands.telemetry.tracer` `invoke_agent` span for the deployed Runtime, and prints the number of matching spans without content or IDs.
Override the delivery wait with `RUNTIME_TRACE_TIMEOUT_SECONDS=seconds`.

## Deployed evaluation

Run the canonical evaluation manually, with explicit approval for its metered
work, after the development endpoint and its Strands traces are verified:

```shell
make eval-runtime-dev
```

The current suite performs 30 metered Runtime invocations with isolated session
IDs and up to 90 managed evaluation requests. It waits for a correlated
CloudWatch trace after each invocation. Prefer the
[local checks and cost controls](../evals/README.md#cost-controls)
when a fresh model measurement is unnecessary. It resolves
the endpoint qualifier, immutable Runtime version, and digest-pinned container
from OpenTofu state, then writes a versioned result under
`build/evals/`. The artifact excludes AWS account,
resource, session, trace, and span identifiers. Use
`RUNTIME_EVAL_TRACE_TIMEOUT_SECONDS=seconds` to change the per-case trace wait.
The command reads the model ID and image digest from the immutable Runtime
version served by the endpoint, preventing manual metadata mismatches.

### Model selection and rollback

Nova Pro (`amazon.nova-pro-v1:0`) is the supported model. The model ID remains
configurable, but every model uses the same structured candidate contract.
Validate a proposed model's tool use, citations, briefs, reliability, latency,
and token usage before adopting it. Model evaluations require explicit approval.

Set the intended `agent_model_id` in deployment configuration and review the
saved plan. Runtime IAM permits only that configured model. Changing this policy
affects all versions sharing the execution role. Pause submissions and
drain queued work during model transitions.

Inspect versions with `make inspect-runtime-versions-dev` and verify the live
READY version has the intended model, image digest, and MMDSv2 setting.
A rollback must restore compatible model permissions, image, API contract, and
Runtime configuration. Follow the normal reviewed
plan/apply workflow and verify compatibility before resuming traffic.

## Agent image publication

Build the AgentCore Runtime image, then preview its immutable ECR destination:

```shell
make agent-image
make security SCAN=image
make preview-agent-image-dev
```

The image must be ARM64. Preview resolves the ECR repository from OpenTofu
state and reports the immutable `image-<configuration-id>` tag and whether it
already exists. Git revision labels are informational; worktree state does not
change publication behavior. Review the scan findings and destination, then
manually perform the write:

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

The service-managed `DEFAULT` endpoint automatically follows Runtime updates.
Configuration changes create a provider-managed version followed by an
MMDSv2-enabled version. Do not submit requests or run evaluations during apply:
the endpoint can temporarily serve the intermediate version. Resume only after
the live endpoint and Runtime are `READY` with MMDSv2 enabled. No separate version
selection or promotion is required. Smoke and evaluation scripts resolve the live
version from AWS, not a stored OpenTofu version output.

Before an extended pause or project completion, review and apply a saved
destroy plan. Supply the private `TF_VAR_budget_notification_email` input as
described under [operational alarms](#operational-alarms); a destroy plan still
evaluates required configuration inputs. Before deleting resources, preserve
privacy-reviewed demonstration evidence and record the exact Runtime log-group
names from `application_log_group_names` in a private local inventory. Do not
export raw prompts or telemetry into committed evidence.

```shell
make tofu-plan-destroy-dev
tofu -chdir=infra/environments/dev show dev-destroy.tfplan
make tofu-destroy-dev CONFIRM=destroy-dev
```

Development teardown removes all resources tracked by the development root,
including ECR repositories and their images. It intentionally preserves the
bootstrap S3 bucket, remote state history, cost budget, and local bootstrap
state because those belong to the independent bootstrap root.

### Resource ownership and residual checks

| Resources | Teardown boundary | Verification |
| --- | --- | --- |
| Dashboard and API error-rate alarm | Development root: `dashboard.tf`, `alarms.tf` | Confirm the exact dashboard/alarm names are absent after apply. |
| SNS topic, policy, and email subscription | Development root: `alarms.tf` | Confirm the topic is absent. A pending email subscription cannot be individually unsubscribed; topic deletion removes its subscriptions. |
| Runtime/Gateway trace delivery sources, destinations, and connections | Development root: `runtime_tracing.tf`, `gateway_tracing.tf` | Confirm both named delivery sources/destinations and their recorded connections are absent. These are distinct from shared X-Ray destination settings. |
| API, worker, catalog, ingestion, and API access log groups | Explicit development `aws_cloudwatch_log_group` resources | Confirm the recorded names are absent. |
| Service-created Runtime log groups | Retention-only provisioning for `DEFAULT`, not managed log-group resources | Inspect all exact pre-destroy names, including unused endpoint groups. The retention script has no destroy hook; removing its `terraform_data` record does not delete a group. |
| Shared `aws/spans`, X-Ray/Transaction Search configuration, and retained spans | Account/Region-level setup outside the development root | Review ownership and retention separately; never delete shared data or disable account-wide settings merely because Praxis is removed. |
| Bootstrap state bucket/history and cost budget | Independent bootstrap root | Preserve until a separately approved bootstrap teardown. |

Seven-day Runtime retention expires events, not the log groups themselves. It
does not establish the retention of `aws/spans`. Earlier Runtime identities may
also have service-created groups; compare a narrowly scoped inventory with the
recorded Runtime identities rather than deleting by a broad prefix. Any cleanup
of exact residual resources requires separate explicit approval. Keep shared
resources as documented exceptions until ownership is resolved.

Verify tracked development resources are gone (with the configured profile):

```shell
AWS_PROFILE=praxis-dev tofu -chdir=infra/environments/dev state list
tofu -chdir=infra/bootstrap state list
```

The first command must print no managed resources; read-only data sources may
remain. The second must continue to list the state-bucket controls and budget
until the bootstrap stack is explicitly destroyed. Empty state is necessary
but not sufficient: complete the residual checks above before reporting that
only documented bootstrap/shared resources remain. This ownership review is
not evidence of an executed teardown or zero ongoing charges.
