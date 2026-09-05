# Praxis

Praxis is a moderately useful Amazon Bedrock and Amazon Bedrock AgentCore project. 
The application uses personal project, book, technical-note, and computing-museum data to recommend worthwhile projects 
and turn a selected idea into an actionable project brief.

## Cold-start handoff

This roadmap is the source of truth for the project's intended scope and current progress. An agent starting in a new conversation should:

1. Read this file and any repository-level `AGENTS.md` completely.
2. Inspect the repository and git status before making changes.
3. Work on the earliest incomplete phase unless the user selects another phase.
4. Complete one small, verifiable checklist slice at a time.
5. Mark an item complete only after its implementation has been verified.
6. Record material architectural decisions in `docs/adr/`.
7. Keep local development possible before requiring deployed AWS resources.
8. Do not create, modify, or destroy cloud resources without an explicit user request for that operation and review of the OpenTofu plan.

### Decisions already made

- Project and repository name: `praxis`
- Repository visibility: private during development
- Agent framework: Strands Agents SDK for Python
- Agent hosting: Amazon Bedrock AgentCore Runtime
- Model access: Amazon Bedrock
- Agent tool boundary: Amazon Bedrock AgentCore Gateway using MCP
- Application boundary: Amazon API Gateway backed by an API Lambda
- Infrastructure as code: OpenTofu with the AWS provider
- Frontend: React and TypeScript in the same repository
- Initial architecture: serverless and without a VPC
- External integrations are read-only; external writes are outside product scope
- AWS region: `us-east-1` (US East, N. Virginia)
- Initial model: Amazon Nova Micro using on-demand inference
- Initial model ID: `amazon.nova-micro-v1:0`
- Current default model: Amazon Nova Pro (`amazon.nova-pro-v1:0`)
- Deployment posture: temporary development environments, destroyed when the project is inactive or complete

### Model strategy

Amazon Nova Pro is the default model because a controlled 30-case deployment comparison showed materially better reliability and quality
than Nova Lite at similar latency. Keep the model ID in configuration rather than application code, retain Lite and Micro as measured
rollback models, and do not change the default without new evaluation evidence.

Use in-region inference in `us-east-1` initially. Cross-region inference can be evaluated later if throughput or 
availability becomes a demonstrated problem.

### Cost posture

- User-reported spend is approximately $5 as of September 5, 2026, attributed
  tentatively to evaluation/DSPy work; billing has not been independently checked.
  Prefer local work and existing evidence. Fresh metered smoke tests, evaluations,
  and DSPy runs require explicit approval; do not rerun them just for log capture.
- The user subsequently approved bounded AWS calls to complete observability
  and demonstration work, including lightweight smoke verification. Avoid heavy
  evaluation or DSPy tasks; retain saved-plan review and teardown approval rules.
- Use on-demand services and avoid provisioned throughput or commitments.
- Deploy only the development environment while actively building or testing.
- Destroy the application stack during extended pauses and at project end.
- Keep durable source data in the sibling repository; cloud copies are disposable and reproducible.
- Target less than **$10 total AWS spend** for the initial MVP build.
- Configure budget notifications before deploying application resources.

### Inputs outside this repository

The initial source data is maintained in a sibling repository and must not be modified as part of ingestion:

```text
../barrettotte.github.io/data/books.json
../barrettotte.github.io/data/projects.json
../barrettotte.github.io/data/bytes.json
../barrettotte.github.io/data/museum.json
```

## Product definition

### Problem statement

Choosing a worthwhile personal project is difficult when ideas must be balanced against prior work, available reference 
material, current interests, novelty, and a realistic time budget. This application searches personal evidence and
turns a goal into several differentiated, buildable project candidates.

### Primary workflow

1. The user describes a goal, interest, constraint, or desired skill.
2. The agent searches relevant projects, books, bytes, and museum objects.
3. The agent proposes three candidates and cites supporting personal evidence.
4. The user compares and selects a candidate.
5. The agent produces a feasible project brief with a concrete technical
   approach, explicit boundaries, deliverables, self-verified milestones,
   risks, and measurable acceptance criteria.

### Source datasets

- 785 books
- 163 projects
- 66 technical notes, CTFs, electronics builds, and other bytes
- 20 computing-museum objects

### MVP boundaries

- One user and one agent
- Read-only personal-data tools
- Three project candidates per request
- Evidence citations on recommendations
- Buffered API responses before streaming
- No external writes
- No multi-agent orchestration
- No VPC unless a concrete private-network requirement appears

## Target architecture

```text
React + TypeScript application
      +-- Authenticate with Amazon Cognito
      `-- Send JWT requests to Amazon API Gateway
                                  |
                                  v
                              API Lambda
                              +-- DynamoDB session state
                              +-- SQS recommendation jobs ---- Worker Lambda
                              |                                      |
                              `-- Selected-project briefs            |
                                           |                         |
                                           `------------+------------'
                                                        v
                                              AgentCore Runtime
                                              +-- Strands agent
                                              +-- Bedrock model
                                              +-- AgentCore Memory
                                                        |
                                                        v
                                              AgentCore Gateway
                                                        |
                                                        v
                                              Catalog Lambda ---- DynamoDB

Source JSON ---- S3 ---- Ingestion Lambda ---- DynamoDB
```

API Gateway is the application boundary. AgentCore Gateway is the agent's secured MCP tool boundary. 
OpenTofu manages the AWS infrastructure.

## Phase 0 - Define the product

- [x] Write an initial problem statement
- [x] Define the primary workflow
- [x] Identify the four source datasets
- [x] Define initial MVP exclusions
- [x] Choose `us-east-1` based on AgentCore and model availability
- [x] Choose Amazon Nova Micro (`amazon.nova-micro-v1:0`) as the initial model
- [x] Verify Nova Micro model access in `us-east-1`
- [x] Decide that the frontend belongs in this repository
- [x] Choose Strands Agents SDK for the Python agent
- [x] Record the architecture in an ADR
- [x] Set the initial MVP cost target and temporary-deployment posture

Definition of done: the product and its boundaries can be explained without discussing implementation details.

## Phase 1 - Repository and local walking skeleton

Proposed layout:

```text
praxis/
|-- backend/
|   |-- src/praxis/
|   |   |-- agent/           # AgentCore Runtime application
|   |   `-- functions/       # API and tool Lambda code
|   `-- tests/
|-- frontend/
|-- infra/
|   |-- bootstrap/
|   |-- environments/dev/
|   `-- modules/
|-- data/
|-- evals/
|-- docs/
|-- pyproject.toml
|-- uv.lock
|-- Makefile
`-- README.md
```

- [x] Initialize the repository
- [x] Add Python project configuration
- [x] Add Strands Agents SDK and a minimal local Strands agent
- [x] Add the React and TypeScript frontend
- [x] Add formatting, linting, type-checking, and unit-test commands
- [x] Copy or reference sanitized development fixtures
- [x] Define domain models for books, projects, bytes, and museum objects
- [x] Build an in-memory catalog implementation
- [x] Implement local `search_catalog`
- [x] Implement local `get_catalog_item`
- [x] Implement local `compare_project_history`
- [x] Return three structured project candidates
- [x] Validate model output against a JSON schema
- [x] Add a command-line demo before introducing AWS
- [x] Add unit tests for search, filtering, and result limits
- [x] Create an initial 10-prompt evaluation set
- [x] Record expected evidence records and tool trajectories
- [x] Record the local Nova Micro baseline for quality, latency, tokens, and tool-call count

Definition of done: one local command accepts a goal and returns three evidence-backed project proposals, with a repeatable measured baseline.

## Phase 2 - OpenTofu foundation

- [x] Pin the OpenTofu and AWS provider versions
- [x] Commit provider lock files
- [x] Create an infrastructure bootstrap stack
- [x] Create an encrypted remote-state bucket
- [x] Enable state versioning and locking
- [x] Establish naming and tagging conventions
- [x] Create separate development configuration
- [x] Create ECR repositories for deployable images
- [x] Add KMS keys only where service-managed encryption is insufficient
- [x] Add an AWS Budget alert
- [x] Set budget notifications below and at the $10 MVP target
- [ ] Run `tofu fmt`, `tofu validate`, and static checks in CI
- [x] Document `plan`, `apply`, and `destroy` procedures
- [x] Verify that destroying the application stack removes billable resources while preserving only explicitly documented bootstrap resources

Hosted verification of the committed CI workflow is pending because the
private repository's current GitHub Actions allowance is exhausted. Equivalent
checks pass locally; keep the CI item open until a hosted run succeeds.

Do not create a VPC initially. The MVP has no private-subnet requirement, and a NAT gateway would add cost and complexity without improving the demonstration.

Definition of done: OpenTofu can reproducibly create and destroy the empty development foundation.

## Phase 3 - Personal-data plane

- [x] Create an encrypted S3 source-data bucket
- [x] Define the DynamoDB access patterns
- [x] Create the DynamoDB catalog table
- [x] Implement the ingestion Lambda
- [x] Normalize category and language values
- [x] Preserve source provenance for every record
- [x] Generate stable record IDs
- [x] Make ingestion idempotent
- [x] Record import counts and rejected records
- [x] Implement exact filters for type, language, category, and date
- [x] Implement bounded text search
- [x] Return only fields needed by the agent
- [x] Deploy the catalog Lambda
- [x] Seed the development environment from the four JSON files
- [x] Verify totals: 785 books, 163 projects, 66 bytes, and 20 museum objects

Definition of done: a deployed Lambda can answer structured catalog queries without invoking an LLM.

## Phase 4 - MCP tools through AgentCore Gateway

Initial tools:

```text
search_catalog
get_catalog_item
summarize_experience
score_project_candidates
```

- [x] Define strict JSON input and output schemas
- [x] Keep tool descriptions compact and unambiguous
- [x] Create least-privilege Lambda execution roles
- [x] Create AgentCore Gateway with OpenTofu
- [x] Register the catalog Lambda as a Gateway target
- [x] Use IAM authorization during the backend-only stage
- [x] Reject excessive result limits
- [x] Add timeouts and structured error responses
- [x] Prevent tool responses from leaking internal metadata
- [x] Capture an authenticated MCP `tools/list` response
- [x] Capture a successful MCP `tools/call` for every tool
- [x] Test malformed and unauthorized calls
- [x] Record latency and payload size for every tool

Definition of done: an authenticated MCP client can discover and invoke all read-only catalog tools.

## Phase 5 - AgentCore Runtime

- [x] Implement the agent in Python with Strands Agents SDK
- [x] Document the Strands agent loop and tool integration
- [x] Use a Bedrock conversation API
- [x] Read the Bedrock model ID from environment configuration
- [x] Connect the agent to AgentCore Gateway
- [x] Define the system instructions
- [x] Require evidence IDs for every proposed project
- [x] Separate factual evidence from generated recommendations
- [x] Add a maximum tool-call budget
- [x] Add a maximum catalog-result budget
- [x] Handle empty or contradictory results
- [x] Containerize the agent
- [x] Push the image to ECR
- [x] Create AgentCore Runtime with OpenTofu
- [x] Configure an immutable runtime version
- [x] Invoke it with a signed development request
- [x] Confirm sessions remain isolated
- [x] Instrument Strands traces for AgentCore Evaluations
- [x] Run the Phase 1 evaluation set against the deployed agent
- [x] Compare Nova Micro with one stronger model on the baseline
- [x] Select Nova Lite as the default after deployed measurements justified the change
- [x] Add AgentCore Memory for preferences and prior decisions
- [x] Keep authoritative catalog data out of agent memory

Definition of done: the deployed agent turns a goal into three cited project candidates using Gateway tools, with 
recorded quality, token, and latency measurements.

## Phase 6 - API Gateway application boundary

Initial API:

```http
POST /v1/sessions
GET  /v1/sessions/{sessionId}
POST /v1/projects/{candidateId}/select
```

- [x] Create the API Lambda
- [x] Create API Gateway with OpenTofu
- [x] Add request validation
- [x] Add consistent response and error schemas
- [x] Propagate correlation IDs
- [x] Invoke AgentCore Runtime from the API Lambda
- [x] Start with buffered responses
- [x] Configure throttling
- [x] Configure payload limits
- [x] Add access logging
- [x] Add CORS for the known frontend origin only
- [x] Return model and tool errors safely
- [x] Add API integration tests
- [x] Confirm arbitrary public callers cannot invoke AgentCore Runtime

Definition of done: a client can complete the read-only workflow entirely through API Gateway.

## Phase 7 - Authentication and frontend

- [x] Create a Cognito user pool
- [x] Create an application client
- [x] Add API Gateway JWT authorization
- [x] Build login and logout
- [x] Build the goal-entry screen
- [x] Display agent progress states
- [x] Display three comparable candidate cards
- [x] Show supporting projects, books, and bytes
- [x] Clearly label generated claims
- [x] Let the user select a candidate
- [x] Render the resulting project brief
- [x] Add accessible loading and error states
- [x] Deploy the frontend to S3 and CloudFront
- [x] Prevent unauthenticated access to protected APIs

Definition of done: the complete application is usable from a browser.

## Phase 8 - Expanded evaluation and token efficiency

- [x] Expand the initial set to at least 30 evaluation prompts
- [x] Include straightforward, ambiguous, and impossible requests
- [x] Define expected evidence records
- [x] Define expected tool trajectories and business assertions
- [x] Use AgentCore Evaluations for goal success, correctness, and tool use
- [x] Measure retrieval relevance
- [x] Measure citation correctness
- [x] Measure unsupported-claim frequency
- [x] Measure tool-selection accuracy
- [x] Measure end-to-end latency
- [x] Record input and output tokens
- [x] Compare full records with projected tool responses
- [x] Compare different retrieval limits
- [x] Confirm conversation summarization is unnecessary for bounded one-shot model invocations
- [x] Add prompt caching where repeated context qualifies
- [x] Compare DSPy-optimized instructions with the maintained baseline on a held-out evaluation set
- [x] Repeat the default-model versus stronger-model comparison
- [x] Establish regression thresholds
- [x] Make evaluation repeatable locally or in CI

Definition of done: measurements show that cost or latency improved without a material reduction in quality.

## Phase 9 - Security and failure testing

- [x] Apply least-privilege IAM policies
- [x] Separate API, runtime, gateway, and tool roles
- [x] Enable encryption and set log-retention periods
- [x] Configure Bedrock Guardrails where appropriate
- [x] Test prompt injection inside catalog records
- [x] Test attempts to invoke unregistered tools
- [x] Test cross-session data access
- [x] Test oversized prompts and tool arguments
- [x] Test Lambda timeout and throttling behavior
- [x] Screen pasted secrets before persistence/model calls and verify credential isolation from prompts/logs
- [x] Add dependency and container scanning
- [ ] Triage and remediate the container scan findings or document reviewed risk exceptions
- [x] Produce a lightweight threat model
- [x] Document residual risks

With user approval, the threat model proceeds while container remediation stays
open and the security gate remains strict. `docs/threat-model.md` maps implemented
trust boundaries, threats, control evidence, and verification limits. Review
against API/worker/Runtime code, identity/hosting/queue configuration, and existing
ADRs verifies the inventory; 88 targeted boundary tests pass. The document calls
out deployment-wide Memory personalization, duplicate metered work, 14-day
dead-letter retention, and content-bearing telemetry. `docs/residual-risks.md`
records eight open risks with project priorities, proposed maintainer ownership,
handling actions, and review triggers. Its coverage was checked against the
threat model and container review; local document links and whitespace checks
pass. Documentation is complete, not risk acceptance or mitigation. Container
remediation remains open; structured logging deployment and verification are
tracked below. No exception is accepted by these documentation reviews.

`make security` scans all three dependency locks (including development
dependencies) and the local Runtime image with digest-pinned Trivy. Local
verification found no HIGH/CRITICAL lockfile findings, but the ARM64 image
reported 57 HIGH and 5 CRITICAL package findings across 23 unique advisory IDs.
The command correctly fails without suppressing unfixed findings. Removing
build-only pip, its ensurepip bootstrap bundle, and uv/uvx from the serving
filesystem eliminates both Python findings. Updating the Python 3.13.15 base
from Bookworm to Trixie reduces the remaining scan from 55 HIGH/5 CRITICAL
to 51 HIGH/3 CRITICAL Debian package findings across 18 unique advisory IDs.
The remaining findings have no fixed version listed by the scan database;
vendor/reachability review remains open, with no exceptions or suppression.
Current sanitized evidence is `docs/evidence/security-scanning.json`; full reports are in ignored
`build/security/`. Native and ARM64 container health checks pass, including
Python 3.13, non-root execution, absent Python installers, and no setuid/setgid
files under `/usr`. Removing the inherited privilege bits leaves version-based
scan counts unchanged. `docs/container-risk-review.md` reviews all 18 advisories:
local ARM64 inspection verifies a 64-bit Perl build, three missing affected Perl
modules, no configured fstab entries, and no systemd-homed executable. Other
findings have no identified application path but are not proven unreachable;
remediation or explicitly approved, scoped exceptions remain outstanding. `make check`
passes with 424 backend and 37 frontend tests. Publication and deployment of
the hardened image remain pending. Offline tests verify
clean, vulnerability, and scanner-error exit handling. CI invokes the same
command against a native AMD64 build; hosted verification remains pending while
the private repository's Actions allowance is exhausted. No deployment changed.

Timeout and throttling verification uses local injected SDK failures, catalog
remaining-time checks, and browser 429/polling tests, plus read-only verification
of deployed route limits and Lambda timeouts. Live concurrency saturation and
forced Lambda termination have not been tested; the hard-timeout limitation is
documented in `docs/infrastructure-operations.md`.

Public goal screening is implemented and verified locally for recognizable
credential formats and assignments before session persistence, queueing, or
Runtime invocation. JSON/base64 rejection and browser correction tests pass.
The API and shared worker package are deployed. The no-inference configuration
suite passes, including direct Lambda rejection of synthetic credential-bearing
JSON/base64 goals; sanitized evidence is in `docs/evidence/api-payload-limits.json`.
Frontend publication and the synthetic credential rejection message in the
authenticated browser are user-confirmed. The extended JWT API smoke suite has
not been rerun. Shared screening now covers Runtime JSON payloads before schema
validation/Memory lookup, local CLI goals, initial Gateway evidence, memory
context, local planning, brief context, and model-selected tool results before
they return to the model. Local SDK HTTP tests verify safe Runtime rejection and
captured logs; other tests verify blocked context never reaches generation.
`make check` passes with 421 backend and 37 frontend tests, and API packaging
passes. Runtime version 52 is deployed to `stable` with the published image and
MMDSv2 verified. Three signed synthetic probes (recommendation goal, brief goal,
and nested JSON credential field) returned Runtime HTTP 400 without reflection.
Bounded CloudWatch inspection found three session-correlated fixed rejections
and HTTP spans, no synthetic marker, and no model spans. Sanitized evidence is
in `docs/evidence/runtime-credential-screening.json`. This verifies the input
boundary, not arbitrary retrieved-context/SDK-error telemetry; local tests cover
the context-screening paths. A normal signed Runtime smoke also passes with
three cited candidates and actor-scoped Memory retrieval. Verification is
limited to these tested boundaries, not universal secret detection or scrubbing.
See `docs/adr/0027-goal-credential-screening.md` for
scope and limits, including SDK diagnostics and undetected credential formats.

Credential verification uses synthetic markers in API headers, unused JWT
claims, dependency errors, and Runtime environment credentials. Local tests
check model-input boundaries, queued jobs, stored state, responses, and captured
application logs. An offline API smoke probe verifies bearer tokens stay out of
`jq`/`curl` arguments and child environments while producing a mode-600 curl
configuration. `make check` passes. This replaces the unprovable blanket claim
that secrets can never appear in logs: user-supplied text is intentionally
captured in evaluation traces, and arbitrary SDK diagnostics are not proven
secret-free. Limits and handling guidance are in `docs/agent-runtime.md`.

Definition of done: the project demonstrates working controls instead of only listing security claims.

## Phase 10 - Observability and demonstration package

The Lambda export provider is implemented behind an explicit opt-in. It owns a
locked SDK, uses parent-based sampling and X-Ray-compatible IDs, and hands spans
synchronously to a local HTTP/protobuf collector with a 0.5-second exporter
timeout. It does not replace the global provider, enable automatic library
instrumentation, or inherit arbitrary exporter headers/proxy credentials.
API, worker, and catalog use the helper; both packaging scripts include it.
Four local tests verify opt-in, reuse, sampling, metadata, and transport settings.
`make check` passes with 484 backend and 37 frontend tests; both Lambda ZIPs build.
A bounded read-only AWS lookup verified collector-only layer
`aws-otel-collector-amd64-ver-0-156-0:4` in `us-east-1` (AWS publisher
`901920570463`, size 14,519,118 bytes, SHA-256 base64
`O/SMWrsEJnin7ymFCDA4uTCB5EK7f2hggBbbJ76J74Q=`). Returned compatibility lists
were absent; this is availability verification, not runtime compatibility proof.
ADR 0028 records the export boundary. Next: package a traces-only collector
configuration, attach the pinned layer and narrowly scoped export permissions
through a reviewed saved plan, then verify a no-model invocation before a
bounded end-to-end smoke. No deployment or metered inference occurred here.

After the user approved lightweight AWS verification, one API Lambda smoke
completed asynchronous recommendations and selected-project brief generation,
including subject-isolation checks. Bounded CloudWatch reads verified three API
events, one ready worker event, and one successful catalog event with only the
expected metadata fields. Combined with the retained ingestion event and Runtime
verification, this completes structured logging. Sanitized evidence is in
`docs/evidence/lambda-logging.json`; SDK diagnostic scrubbing is not claimed.
No heavy evaluations, DSPy runs, or deployments were performed.

Catalog instrumentation now adds `praxis.catalog.request` through the active
provider, with only normalized outcomes and error status, no automatic exception
events, and unchanged results/errors. Four local cases verify privacy, parent/child
linkage, and behavior. `make check` passes with 480 backend and 37 frontend tests;
the shared functions ZIP builds successfully. These spans
are not deployed or exported yet; Lambda provider/export configuration and the
Gateway-to-catalog propagation boundary are the next tracing work. Keep the
end-to-end instrumentation checkbox open until deployed verification.

Structured logging is implemented and deployed for all four Lambdas:
`api_request`, `recommendation_delivery`, `catalog_request`, and
`catalog_ingestion`. Events contain fixed outcomes, duration, and applicable
status/count fields, not payloads or exception text. Incomplete ingestion counts
are null rather than misleading zeros. Local tests verify these contracts and
unchanged response/error behavior. The latest `make check` passes with 451 backend
and 37 frontend tests; both Lambda packaging targets pass.

The reviewed saved plan applied four in-place code updates, with no additions
or deletions. Gateway policy recomputation made no effective change. Read-only
AWS checks confirm Active/Successful state, JSON logging, and matching local
package hashes. Evidence is `docs/evidence/lambda-logging.json`.

The Runtime deployment is unchanged. Its installed SDK already provides
JSON outcome logs; three local HTTP tests verify success, rejection, and failure
formatting. SDK exception logs contain diagnostics and are not covered by the
content-free Lambda event contract; README and Runtime docs explain the difference.

Remaining verification: following user-confirmed actions, a bounded CloudWatch
read verified an INFO `catalog_ingestion` event with outcome `updated`, 1,034
accepted/written records, zero deleted/rejected records, and only the intended
metadata fields. The sampled API/worker/catalog pages returned no matching
events; this does not establish whether calls were absent or delivery was delayed.
Do not request repeated paid work for this evidence: keep logging unchecked and
use existing events when available. Further implementation should stay local.
Container remediation and hosted CI remain open. OpenTelemetry implementation
can proceed locally while deployed logging verification remains pending.

The Runtime entry point now adds a `praxis.runtime.request` span around validation
and generation using the installed OpenTelemetry provider. Only a fixed outcome
is attached; automatic exception events/status descriptions are disabled, and
escaping errors set ERROR status without diagnostic text. Three in-memory tests
verify outcomes, parent/child relationships, timestamps, privacy, and unchanged
return/exception behavior. `make check` passes with 454 backend and 37 frontend
tests after rerunning the sandbox-stalled HTTP tests outside the sandbox.
No AWS calls, new dependencies, exporter configuration, publication, or deployment
were performed. This is a local Runtime slice only: API/queue/tool propagation
and deployed trace verification remain incomplete, so the tracing checkbox stays
open.

The shared API/worker Runtime adapter forwards active W3C trace context using
the SDK `traceParent` parameter, without vendor state or arbitrary baggage.
Four local tests cover sampled/unsampled contexts through both public adapters;
existing no-context request assertions retain their unchanged wire contract.
The OpenTelemetry API is now a direct dependency and included in the Lambda
lock/package; no existing dependency versions changed. `make check` passes
with 458 backend and 37 frontend tests, and API packaging verifies the propagator
is included. No AWS calls or deployment occurred. Lambda provider/exporter setup,
queue propagation, and deployed verification remain open.

API and worker handlers now add `praxis.api.request` and
`praxis.worker.delivery` spans through the active provider, without configuring
an exporter or accepting browser trace headers. Fixed outcomes and API response
status are the only attributes; exceptions are not recorded as span events or
status descriptions. Existing logs, responses, and SQS retry behavior remain
unchanged. Seven in-memory cases verify status/outcome, parent/child linkage,
timing, privacy, and response/exception preservation. `make check` passes with
465 backend and 37 frontend tests; API/worker packaging passes. No dependencies,
AWS resources, export paths, or deployments changed in this slice. Next is
trusted queue trace-context propagation; deployed tracing remains unchecked.

Queue propagation is now implemented locally: the API injects server-generated
W3C trace identity into optional SQS metadata, and the single-record worker
continues that parent with its sampling flag. Job bodies remain unchanged;
missing or malformed metadata does not break jobs or inherit unrelated context.
Vendor state and arbitrary baggage are excluded. ADR 0028 records the trust
boundary. Eleven new local cases verify transport, privacy, compatibility, and
worker linkage. `make check` passes with 476 backend and 37 frontend tests;
API/worker packaging and the targeted 35-test suite pass. No AWS calls or
deployment occurred. Next is local catalog-tool instrumentation; Lambda exporter
configuration and deployed end-to-end verification remain open, with no tracing
checkbox changed.

Cost/token documentation is complete in `evals/README.md`, using checked-in
projection, retrieval, caching, DSPy, and model-comparison evidence. Command
guidance distinguishes no-AWS checks from locally hosted metered inference;
operations documentation now reflects the 30-case evaluation and managed
evaluator calls. `make eval-check` passes all 32 tests and the recorded regression
gate without AWS calls. Logging and tracing verification remain open.

The five-minute presentation script in `docs/demo.md` uses existing evidence by
default and separates an optional approved live workflow from local checks.
The six presentation segments total five minutes; linked files resolve, cited
measurements match their artifacts, and all 37 frontend tests pass locally.
The script is written, not a recorded or live-rehearsed demonstration. Video
and failure/recovery trace capture remain open; no AWS calls were made.

`docs/architecture-tradeoffs.md` consolidates ten accepted choices with benefits,
limitations, and review triggers. Review against the linked ADRs and risk register
preserves the distinction between subject-owned sessions and deployment-wide
Memory personalization, and between citation provenance and factual correctness.
Local link and whitespace checks pass. No architecture or deployment changed.

`docs/multi-user-deployment.md` documents prerequisites for broader access,
including trusted identity propagation, Memory/catalog isolation, telemetry
permissions, duplicate-work handling, and operational ownership. Current-state
claims were checked against API/session/worker code, deployment actor and Cognito
configuration, and the threat model. Local links and whitespace checks pass.
This completes the explanation only; multi-user implementation is not authorized
or verified, and the current architecture remains single-user.

The conditional production-evolution diagram in `docs/multi-user-deployment.md`
keeps the application/tool boundaries and shows a private-source connector only
when a concrete reachability requirement justifies it. It distinguishes that
case from private service ingress or controlled Runtime egress. Review against
the documented tenancy requirements and initial architecture ADR passes;
the text diagram fits 80 columns, its README anchor resolves, and whitespace
checks pass. It is a proposal, not an approved network design or deployment.

The enterprise retrieval mapping in `docs/multi-user-deployment.md` relates all
four inputs, ingestion, Gateway retrieval, and reviewed output to organizational
use cases. Review against the retrieval/tool ADRs and evaluation guide confirms
that analogies do not imply connectors, a Knowledge Base, document permissions,
or external writes. Local links, the README anchor, and whitespace checks pass;
no application, infrastructure, or authoritative data changed.

The README is prepared for public readers with a short workflow, explicit
single-user/security limits, local prerequisites, separate metered AWS usage,
and consolidated guide links. The opening description and architecture diagram
are preserved. Local links, whitespace, Make help, CLI help, and smoke-suite help
checks pass without AWS calls. Public publication remains unchecked: no push or
repository-visibility change was requested or performed.

Existing demonstration captures were reviewed locally. The Runtime rejection
artifact verifies three synthetic HTTP 400 probes without reflection and their
bounded correlated log inspection, satisfying the rejected-request capture item.
The successful trace artifact records 15 spans only as a summary; it lacks the
retained span tree/timings/outcomes needed for a trace walkthrough. Its version
also differs from the separate successful invocation capture. Successful-trace
and failure/recovery items therefore remain open. `docs/demo.md` records coverage
and acceptance criteria; JSON assertions pass without AWS calls or new captures.

- [x] Add structured logs throughout
- [ ] Extend OpenTelemetry instrumentation across API, runtime, and tools
- [ ] Enable AgentCore and CloudWatch observability
- [ ] Create a dashboard for latency, tokens, errors, and tool calls
- [ ] Add alarms for error rate and unexpected spending
- [ ] Create a polished architecture diagram
- [x] Create a five-minute demo script
- [ ] Capture one successful trace
- [x] Capture one rejected invalid request
- [ ] Capture one failure-and-recovery trace
- [x] Document architectural tradeoffs
- [x] Document cost and token optimizations
- [x] Explain changes needed for a multi-user enterprise deployment
- [x] Diagram a production evolution with private networking only where justified
- [x] Map the personal-data workflow to an enterprise retrieval pattern
- [ ] Publish a concise public README

Definition of done: another engineer can deploy the project, understand its controls, and reproduce the demonstration.

## MVP release gate

The showcase release includes Phases 0 through 7 plus the essential expanded
evaluation, security, and observability work from Phases 8 through 10.

The MVP must prove:

- [ ] OpenTofu provisions the environment
- [ ] API Gateway is the application entry point
- [ ] AgentCore Runtime hosts the containerized Strands agent
- [ ] AgentCore Gateway exposes Lambda tools with captured `tools/list` and `tools/call` evidence
- [ ] The agent searches real personal data
- [ ] Recommendations cite actual evidence
- [ ] Authentication and basic observability are enabled
- [ ] A repeatable evaluation suite measures quality, latency, and tokens
- [ ] Measurements compare at least two candidate models
- [ ] Demonstration artifacts include successful, rejected, and recovered traces

## Immediate next steps

- [x] Select `praxis` as the repository name
- [x] Create the private repository
- [x] Add this roadmap as `ROADMAP.md`
- [x] Verify Nova Micro access in `us-east-1`
- [x] Write the initial architecture ADR
- [x] Begin the Phase 1 local walking skeleton
- [x] Establish the initial local evaluation baseline during Phase 1
