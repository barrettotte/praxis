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
- Initial external actions: read-only; later writes require explicit approval
- AWS region: `us-east-1` (US East, N. Virginia)
- Initial model: Amazon Nova Micro using on-demand inference
- Initial model ID: `amazon.nova-micro-v1:0`
- Deployment posture: temporary development environments, destroyed when the project is inactive or complete

### Model strategy

Amazon Nova Micro is the initial model because Praxis begins as a text-only workflow and should minimize development inference cost. 
Keep the model ID in configuration rather than application code. Use evaluation results beginning with the Phase 1 baseline and 
expanded in Phase 10 to decide whether particular workflows require a stronger model; do not upgrade the default model without measured evidence.

Use in-region inference in `us-east-1` initially. Cross-region inference can be evaluated later if throughput or 
availability becomes a demonstrated problem.

### Cost posture

- Use on-demand services and avoid provisioned throughput or commitments.
- Deploy only the development environment while actively building or testing.
- Destroy the application stack during extended pauses and at project end.
- Keep durable source data in the sibling repository; cloud copies are disposable and reproducible.
- Target less than **$10 total AWS spend** for the initial MVP build.
- Configure budget notifications before deploying application resources.
- Treat the later Knowledge Base phase as a separate cost decision.

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
5. The agent produces a scoped project brief with milestones, risks, and acceptance criteria.
6. For the showcase release, the user can preview, explicitly approve, and create GitHub issues from the selected brief.

### Source datasets

- 782 books
- 162 projects
- 66 technical notes, CTFs, electronics builds, and other bytes
- 20 computing-museum objects

### MVP boundaries

- One user and one agent
- Read-only personal-data tools
- Three project candidates per request
- Evidence citations on recommendations
- Buffered API responses before streaming
- No autonomous external writes
- No multi-agent orchestration
- No VPC unless a concrete private-network requirement appears

## Target architecture

```text
React + TypeScript application
      |
      v
Amazon Cognito
      | JWT
      v
Amazon API Gateway
      |
      v
API Lambda
      |
      v
AgentCore Runtime
      |
      +-- Strands agent
      +-- Bedrock model
      +-- AgentCore Memory
      |
      v
AgentCore Gateway
      +-- Catalog Lambda ---- DynamoDB
      +-- GitHub Lambda ----- GitHub API
      +-- Research Lambda --- External APIs

Source JSON ---- Ingestion Lambda ---- DynamoDB / S3
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
- [x] Verify totals: 782 books, 162 projects, 66 bytes, and 20 museum objects

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
- [x] Read the Nova Micro model ID from environment configuration
- [x] Connect the agent to AgentCore Gateway
- [ ] Define the system instructions
- [ ] Require evidence IDs for every proposed project
- [ ] Separate factual evidence from generated recommendations
- [ ] Add a maximum tool-call budget
- [ ] Add a maximum catalog-result budget
- [ ] Handle empty or contradictory results
- [ ] Containerize the agent
- [ ] Push the image to ECR
- [ ] Create AgentCore Runtime with OpenTofu
- [ ] Configure an immutable runtime version
- [ ] Invoke it with a signed development request
- [ ] Confirm sessions remain isolated
- [ ] Instrument Strands traces for AgentCore Evaluations
- [ ] Run the Phase 1 evaluation set against the deployed agent
- [ ] Compare Nova Micro with one stronger model on the baseline
- [ ] Keep Nova Micro as the default unless measured results justify a change
- [ ] Add AgentCore Memory for preferences and prior decisions
- [ ] Keep authoritative catalog data out of agent memory

Definition of done: the deployed agent turns a goal into three cited project candidates using Gateway tools, with 
recorded quality, token, and latency measurements.

## Phase 6 - API Gateway application boundary

Initial API:

```http
POST /v1/sessions
POST /v1/sessions/{sessionId}/messages
GET  /v1/sessions/{sessionId}
POST /v1/projects/{candidateId}/select
```

- [ ] Create the API Lambda
- [ ] Create API Gateway with OpenTofu
- [ ] Add request validation
- [ ] Add consistent response and error schemas
- [ ] Propagate correlation IDs
- [ ] Invoke AgentCore Runtime from the API Lambda
- [ ] Start with buffered responses
- [ ] Configure throttling
- [ ] Configure payload limits
- [ ] Add access logging
- [ ] Add CORS for the known frontend origin only
- [ ] Return model and tool errors safely
- [ ] Add API integration tests
- [ ] Confirm arbitrary public callers cannot invoke AgentCore Runtime

Definition of done: a client can complete the read-only workflow entirely through API Gateway.

## Phase 7 - Authentication and frontend

- [ ] Create a Cognito user pool
- [ ] Create an application client
- [ ] Add API Gateway JWT authorization
- [ ] Build login and logout
- [ ] Build the goal-entry screen
- [ ] Display agent progress states
- [ ] Display three comparable candidate cards
- [ ] Show supporting projects, books, and bytes
- [ ] Clearly label generated claims
- [ ] Let the user select a candidate
- [ ] Render the resulting project brief
- [ ] Add accessible loading and error states
- [ ] Deploy the frontend to S3 and CloudFront
- [ ] Prevent unauthenticated access to protected APIs

Definition of done: the complete application is usable from a browser.

## Phase 8 - Showcase workflow: approved GitHub actions

- [ ] Create a separate GitHub tool Lambda
- [ ] Register the GitHub Lambda with AgentCore Gateway as MCP tools
- [ ] Store credentials through an appropriate secrets or identity mechanism
- [ ] Request the narrowest possible GitHub scopes
- [ ] Implement read-only repository lookup first
- [ ] Add `preview_github_issues`
- [ ] Add `create_github_issues`
- [ ] Require explicit approval between preview and execution
- [ ] Make write requests idempotent
- [ ] Record who approved each action
- [ ] Add an audit record
- [ ] Prevent arbitrary repository selection
- [ ] Test expired and revoked credentials
- [ ] Test partial failure during issue creation
- [ ] Create issues in a designated test repository after explicit approval
- [ ] Capture the approval, resulting issue URLs, and audit record

Definition of done: the agent can prepare GitHub issues but cannot create them without distinct, authenticated approval, 
and one approved end-to-end action is demonstrated against a designated test repository.

## Phase 9 - Knowledge Base and richer evidence

- [ ] Fetch selected GitHub README content
- [ ] Store source snapshots in S3
- [ ] Create a Bedrock Knowledge Base
- [ ] Ingest descriptions and README documents
- [ ] Preserve repository and file citations
- [ ] Add semantic retrieval as a separate tool
- [ ] Keep dates, languages, and identifiers in DynamoDB
- [ ] Compare semantic retrieval with structured search
- [ ] Add reranking only if measurements justify it
- [ ] Test stale-document behavior
- [ ] Document the hybrid-retrieval design

Definition of done: recommendations can use both structured facts and cited semantic evidence.

## Phase 10 - Expanded evaluation and token efficiency

- [ ] Expand the initial set to at least 30 evaluation prompts
- [ ] Include straightforward, ambiguous, and impossible requests
- [ ] Define expected evidence records
- [ ] Define expected tool trajectories and business assertions
- [ ] Use AgentCore Evaluations for goal success, correctness, and tool use
- [ ] Measure retrieval relevance
- [ ] Measure citation correctness
- [ ] Measure unsupported-claim frequency
- [ ] Measure tool-selection accuracy
- [ ] Measure end-to-end latency
- [ ] Record input and output tokens
- [ ] Compare full records with projected tool responses
- [ ] Compare different retrieval limits
- [ ] Test conversation summarization
- [ ] Add prompt caching where repeated context qualifies
- [ ] Repeat the Nova Micro versus stronger-model comparison
- [ ] Establish regression thresholds
- [ ] Make evaluation repeatable locally or in CI

Definition of done: measurements show that cost or latency improved without a material reduction in quality.

## Phase 11 - Security and failure testing

- [ ] Apply least-privilege IAM policies
- [ ] Separate API, runtime, gateway, and tool roles
- [ ] Enable encryption and set log-retention periods
- [ ] Configure Bedrock Guardrails where appropriate
- [ ] Test prompt injection inside catalog records
- [ ] Test attempts to bypass approval
- [ ] Test cross-session data access
- [ ] Test oversized prompts and tool arguments
- [ ] Test Lambda timeout and throttling behavior
- [ ] Confirm secrets never enter prompts or logs
- [ ] Add dependency and container scanning
- [ ] Produce a lightweight threat model
- [ ] Document residual risks

Definition of done: the project demonstrates working controls instead of only listing security claims.

## Phase 12 - Observability and demonstration package

- [ ] Add structured logs throughout
- [ ] Extend OpenTelemetry instrumentation across API, runtime, and tools
- [ ] Enable AgentCore and CloudWatch observability
- [ ] Create a dashboard for latency, tokens, errors, and tool calls
- [ ] Add alarms for error rate and unexpected spending
- [ ] Create a polished architecture diagram
- [ ] Create a five-minute demo script
- [ ] Capture one successful trace
- [ ] Capture one rejected write attempt
- [ ] Capture one failure-and-recovery trace
- [ ] Document architectural tradeoffs
- [ ] Document cost and token optimizations
- [ ] Explain changes needed for a multi-user enterprise deployment
- [ ] Diagram a production evolution with private networking only where justified
- [ ] Map the personal-data and GitHub workflow to an enterprise integration pattern
- [ ] Publish a concise public README
- [ ] Record a short demonstration video

Definition of done: another engineer can deploy the project, understand its controls, and reproduce the demonstration.

## MVP release gate

The showcase release ends after Phase 8 plus the essential expanded evaluation, security, and observability work from Phases 10 through 12. 
The Knowledge Base can follow.

The MVP must prove:

- [ ] OpenTofu provisions the environment
- [ ] API Gateway is the application entry point
- [ ] AgentCore Runtime hosts the containerized Strands agent
- [ ] AgentCore Gateway exposes Lambda tools with captured `tools/list` and `tools/call` evidence
- [ ] The agent searches real personal data
- [ ] Recommendations cite actual evidence
- [ ] A GitHub action requires preview, authenticated approval, and an audit record
- [ ] One approved action creates issues in the designated test repository
- [ ] Authentication and basic observability are enabled
- [ ] A repeatable evaluation suite measures quality, latency, and tokens
- [ ] Measurements compare Nova Micro with a stronger model
- [ ] Demonstration artifacts include successful, rejected, and recovered traces

## Immediate next steps

- [x] Select `praxis` as the repository name
- [x] Create the private repository
- [x] Add this roadmap as `ROADMAP.md`
- [x] Verify Nova Micro access in `us-east-1`
- [x] Write the initial architecture ADR
- [x] Begin the Phase 1 local walking skeleton
- [x] Establish the initial local evaluation baseline during Phase 1
