# Praxis roadmap

Praxis uses personal books, projects, technical notes, and computing-museum data
to recommend three evidence-backed projects and develop a selected project brief.

## Handoff

Follow [AGENTS.md](AGENTS.md) for working conventions and AWS approval rules.
This file tracks scope, current progress, and next work—not a session log.
Architecture lives in [README.md](README.md#architecture) and [ADRs](docs/adr/);
verification details live in [evidence](docs/evidence/) and the linked guides.

- **Next:** verify Runtime → Gateway propagation and resolve the intermediate
  Runtime parent. Gateway service-span retention and Gateway → catalog parent
  linkage are verified with a no-model signed search.
- **Sequencing:** continue Phase 10 with user approval while hosted CI and
  container remediation remain open. Do not mark either blocker resolved.
- **Deployed:** Runtime `stable` version 52; API, worker, and catalog have
  collector-backed tracing. The additional Runtime request span is implemented
  locally but not published. Do not assume all local code is deployed.
- **Verification baseline:** `make check`, both Lambda packages, and OpenTofu
  validation pass. No-model catalog and API rejection smokes pass.
- **Cost:** initial target below $10; last user report was about $5, not a billing
  audit. Bounded AWS calls and lightweight smokes are approved for completion;
  avoid heavy evaluations/DSPy and reuse existing evidence. Saved-plan review and
  destructive-operation approval rules still apply.

## Scope

Goal → retrieve personal evidence → compare three cited candidates → select →
generate a feasible brief with deliverables, milestones, risks, and acceptance criteria.

Single-user, one Strands agent, read-only tools, buffered responses, no external
writes or multi-agent orchestration, and no VPC without a demonstrated need.
Nova Pro in `us-east-1` is the evaluated default; Lite and Micro remain rollback
models. Memory contains only explicit preferences and decisions, not catalog facts.
Subject-owned sessions do not make deployment-wide Memory personalization multi-tenant.

Authoritative inputs are read-only:
`../barrettotte.github.io/data/{books,projects,bytes,museum}.json`.
Last verified ingestion: 785 books, 163 projects, 66 bytes, 20 museum objects.
Recalculate totals from source files when reseeding; cloud copies are disposable.
Curated JSON retrieval is sufficient for the MVP; no GitHub fetching or issue creation.

## Completed phases

Detailed completed checklists are available in git history; this consolidation
does not change their completion status.

| Phase | Verified outcome |
| --- | --- |
| 0 — Product | Workflow, datasets, exclusions, architecture, region, and cost posture defined. |
| 1 — Local skeleton | Python 3.13 backend, React/TypeScript frontend, typed catalog/tools, CLI, checks, and initial evaluation baseline. |
| 3 — Data plane | Reproducible S3 ingestion into DynamoDB, stable provenance/IDs, bounded search and filters, deployed totals verified. |
| 4 — MCP tools | IAM-authenticated Gateway exposes strict read-only Lambda tools; success, malformed/unauthorized calls, and latency captured. |
| 5 — Runtime | Containerized Strands agent, bounded cited output, model comparisons, session isolation, and scoped Memory verified. |
| 6 — API | Protected application boundary, asynchronous recommendations, buffered results/briefs, validation, throttling, limits, CORS, and integration tests. |
| 7 — Frontend | Cognito sign-in, goal entry, candidate/evidence display, selection and briefs, accessible states, S3/CloudFront delivery. |
| 8 — Evaluation | 30-case suite, managed quality/tool measures, retrieval/token comparisons, caching, DSPy comparison, model selection, and regression gates. |

References: [Runtime guide](docs/agent-runtime.md),
[evaluation guide](evals/README.md), [operations](docs/infrastructure-operations.md).

## Phase 2 - OpenTofu foundation

Infrastructure, remote state, naming, encryption, budget alerts, and documented
plan/apply/destroy procedures are complete, including teardown verification.

- [ ] Run `tofu fmt`, `tofu validate`, and static checks in CI

**Blocker:** private-repository GitHub Actions allowance exhausted. Equivalent
local checks pass; a successful hosted run is still required.

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

**Blocker:** the container scan still fails on unfixed Debian advisories; no risk
exceptions are accepted. Hardened image publication/deployment remains pending.
See [container review](docs/container-risk-review.md),
[scan evidence](docs/evidence/security-scanning.json),
[threat model](docs/threat-model.md), and [residual risks](docs/residual-risks.md).
Credential screening is limited detection, not universal secret scrubbing;
SDK diagnostics/content-bearing telemetry remain a documented risk.

## Phase 10 - Observability and demonstration package

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

**Current verification:**

- Structured Lambda logs are deployed and verified:
  [logging evidence](docs/evidence/lambda-logging.json).
- API rejection and catalog success spans are retained in `aws/spans` (no
  leading slash). X-Ray summary indexing is 1%; empty summary searches do not
  prove failed export. Cross-service linkage remains unverified:
  [tracing evidence](docs/evidence/lambda-tracing.json),
  [trace boundary](docs/adr/0028-trusted-trace-propagation.md).
- Dual W3C/X-Ray headers are deployed; recommendation/brief smoke passes and
  Runtime spans retain the API/worker trace ID. An intermediate parent is absent
  from the capture; complete workflow parent linkage remains open:
  [linkage evidence](docs/evidence/runtime-trace-linkage.json).
- Gateway → catalog parent linkage is deployed and verified:
  [tool-boundary evidence](docs/evidence/gateway-trace-boundary.json).
- The existing Runtime success capture is a summary, not a full-workflow trace
  walkthrough. Complete success and failure/recovery artifacts remain open.
  [Demo guide](docs/demo.md) defines required evidence.
- [Architecture tradeoffs](docs/architecture-tradeoffs.md),
  [cost/token findings](evals/README.md), and
  [enterprise evolution](docs/multi-user-deployment.md) are documented; proposed
  multi-user/private-network capabilities are not implemented.
- README is prepared, but public publication/visibility change is not authorized
  or verified. The current diagram exists; the polished showcase item stays open.

Definition of done: another engineer can deploy the project, understand its
controls, and reproduce the demonstration with retained evidence.

## MVP release gate

These are release-level confirmations, separate from implementation completion.
Keep them open until the assembled showcase is reviewed against its evidence.

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
