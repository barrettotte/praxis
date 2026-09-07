# praxis

An Amazon Bedrock and AgentCore app that uses personal evidence to recommend worthwhile software projects and turn ideas into actionable briefs.

I wanted to see a basic AgentCore app doing something mildly interesting.
I used my data from [barrettotte.github.io](https://github.com/barrettotte/barrettotte.github.io/tree/master/data).

Describe a learning goal, compare three evidence-backed candidates, then select
one for a brief with deliverables, milestones, risks, and acceptance checks.
Retrieval uses book, project, technical-note, and computing-museum metadata in
DynamoDB—not a semantic Knowledge Base or externally fetched book contents.

This is a single-user demonstration. Citations identify retrieved evidence;
they do not prove generated advice is correct or feasible. Do not submit secrets
or sensitive material. Security findings and deployment-verification gaps remain
open in the [security guide](docs/security.md#known-limitations).

## Try it

Sign in to the configured frontend and submit a non-sensitive goal, such as
“Suggest a weekend Python project about computing history using only my laptop.”
Compare the three candidates, inspect their cited resources, and select one for
a brief. Review its first step and completion checks before acting on it.
Both submission and selection can incur model costs; local Vite uses the
configured AWS backend, not an offline agent. Stop rather than repeatedly retrying
failures. See [operations](docs/infrastructure-operations.md) for setup and tokens.

## Architecture

### Tradeoffs and limitations

- Serverless services avoid always-on application servers but add AWS integration
  and cold-start overhead. AgentCore integration is an explicit goal of this demo.
- Lexical retrieval is sufficient for the small metadata catalog; citations do
  not substantiate unseen book contents or generated technical procedures.
- Recommendations and briefs use the same queue and worker. Retries can repeat
  paid inference, and budget alerts are not a spending cap.
- Sessions are subject-owned, but the catalog is shared. Additional users require
  explicit catalog authorization and data-isolation design, not merely another login.
  Private networking is justified only by a concrete traffic need.


The diagram describes the implementation, not current deployment health.
Use the [operating procedures](docs/infrastructure-operations.md) to inspect a deployment.

```mermaid
flowchart TB
    subgraph client[Browser and identity]
        hosting[CloudFront + private S3] -->|Serve assets| browser[React + TypeScript]
        browser <-->|Sign in / JWT| identity[Amazon Cognito]
    end

    subgraph application[Authenticated application boundary]
        http[API Gateway HTTP API] -->|Validated JWT subject| api[API Lambda]
        api <-->|Owned session / status| session[(DynamoDB sessions)]
        api -->|Recommendation / brief job| queue[SQS]
        queue --> worker[Worker Lambda]
        worker <-->|Candidates / briefs / status| session
    end

    subgraph intelligence[IAM-protected agent and read-only tools]
        runtime[AgentCore Runtime / Strands]
        model[Bedrock Nova Pro + Guardrail]
        gateway[AgentCore Gateway / MCP]
        tools[Catalog Lambda]
        catalog[(DynamoDB catalog)]
        runtime -->|Guarded inference| model
        runtime -->|Signed tool calls| gateway
        gateway --> tools
        tools -->|Read evidence| catalog
    end

    browser -->|JWT: create, poll, select| http
    worker -->|Generate recommendations / briefs| runtime
    sources[Site JSON / S3 / ingestion Lambda] -->|Reproducible ingestion| catalog

    classDef entry fill:#e8f0fe,stroke:#355b86,color:#172b4d
    classDef compute fill:#eef5ed,stroke:#476b45,color:#233b22
    classDef data fill:#fff4df,stroke:#89642a,color:#493411
    class browser,identity,http,hosting entry
    class api,worker,runtime,model,gateway,tools compute
    class session,queue,catalog,sources data
```

Recommendations and briefs run asynchronously: the browser polls subject-owned
job state for each buffered result. These
are logical access boundaries, not VPCs. Catalog evidence comes from curated
site JSON, not a semantic Knowledge Base. Each generation uses its supplied goal
and retrieved catalog evidence, without cross-session personalization.

CloudWatch logs, ADOT/X-Ray traces, the operations dashboard, and SNS alarm
routing support the workflow. The detailed view includes those flows,
image publication, and the manual evaluation path.

<details>
<summary>Detailed deployment, data, and observability view</summary>


```mermaid
flowchart TD
    user[User] -->|HTTPS| edge[Amazon CloudFront]
    edge -->|Signed OAC reads| frontendAssets[(Encrypted private S3 frontend assets)]
    edge -->|Serve application| ui[React + TypeScript in browser]
    ui -->|Authenticate| cognito[Amazon Cognito]
    cognito -->|JWT| ui
    ui -->|JWT request| apiGateway[Amazon API Gateway HTTP API]
    apiGateway -->|Validated JWT claims| apiLambda[API Lambda<br/>Goal credential screening + API execution role]
    apiLambda -->|Store/read subject-owned state| sessions[(Encrypted DynamoDB sessions<br/>Subject bound + TTL enabled)]
    apiLambda -->|Queue owned generation job| jobs[[Encrypted SQS<br/>recommendation / brief jobs]]
    jobs --> worker[Recommendation worker Lambda<br/>Worker execution role]
    jobs -.->|Retries exhausted| deadLetter[[Encrypted SQS<br/>dead-letter queue]]
    worker <-->|Read/complete subject-owned state| sessions

    subgraph runtime[Amazon Bedrock AgentCore Runtime]
        runtimeEndpoint[stable endpoint<br/>Pinned Runtime version]
        agent[Python 3.13 ARM64 distroless container<br/>Input/context screening + Strands agent<br/>Runtime execution role]
        runtimeEndpoint --> agent
    end

    worker -->|Generate candidates / briefs| runtimeEndpoint
    agent -->|Guarded Converse requests| guardrail[Amazon Bedrock Guardrail<br/>Prompt-attack input filter]
    guardrail --> bedrock[Amazon Bedrock<br/>Nova Pro]
    agentImage[(Encrypted Amazon ECR<br/>agent image)] -->|Immutable image digest| agent

    subgraph observability[Application and agent observability]
        apiAccessLogs[CloudWatch Logs<br/>API access metadata]
        workerLogs[CloudWatch Logs<br/>Worker delivery outcomes]
        apiLogs[CloudWatch Logs<br/>API request outcomes]
        catalogLogs[CloudWatch Logs<br/>Catalog request outcomes]
        ingestionLogs[CloudWatch Logs<br/>Ingestion outcomes and counts]
        runtimeLogs[CloudWatch Logs<br/>SDK Runtime outcomes and diagnostics]
        runtimeSpans[CloudWatch Logs<br/>Runtime span stream]
        xray[AWS X-Ray ingest]
        lambdaCollector[ADOT collector extension<br/>API, worker, and catalog]
        cloudwatch[CloudWatch transaction search]
        operationsDashboard[CloudWatch operations dashboard<br/>Metrics and aggregate API statuses]
        apiErrorAlarm[HTTP API error-rate alarm]
        operationsTopic[SNS operational notifications<br/>Budget email recipient]
        xray --> cloudwatch
    end

    apiGateway -->|Privacy-safe access records| apiAccessLogs
    apiGateway -->|5xx / Count| apiErrorAlarm
    apiErrorAlarm -->|Alarm and recovery metadata| operationsTopic
    worker -->|Outcome + duration metadata| workerLogs
    apiLambda -->|Status + duration metadata| apiLogs
    catalogLambda -->|Outcome + duration metadata| catalogLogs
    apiLogs -->|Aggregate status query on view| operationsDashboard
    apiLambda -->|Duration and error metrics| operationsDashboard
    worker -->|Duration and error metrics| operationsDashboard
    catalogLambda -->|Duration, errors, and invocation metrics| operationsDashboard
    bedrock -->|Account/model token metrics| operationsDashboard
    ingestion -->|Outcome + aggregate counts| ingestionLogs
    apiLambda -->|Application spans over loopback OTLP| lambdaCollector
    worker -->|Application spans over loopback OTLP| lambdaCollector
    catalogLambda -->|Application spans over loopback OTLP| lambdaCollector
    lambdaCollector -->|Traces only| xray
    agent -->|SDK JSON logs| runtimeLogs
    agent -->|Strands OTEL spans via ADOT| xray
    agent -->|Session-correlated OTEL spans| runtimeSpans
    runtimeEndpoint -->|Managed service trace delivery| xray

    subgraph evaluation[Manual evaluation path]
        evalRunner[Local evaluation runner]
        managedEvaluators[AgentCore Evaluations<br/>Managed evaluators]
        evalRunner -->|OTEL spans + reviewed assertions| managedEvaluators
    end

    evalRunner -->|Isolated metered sessions| runtimeEndpoint
    evalRunner -->|Read correlated spans| runtimeSpans

    subgraph tools[AgentCore Gateway MCP tool boundary]
        gateway[AgentCore Gateway<br/>Gateway execution role]
        catalogLambda[Catalog Lambda<br/>Catalog execution role]
        gateway --> catalogLambda
    end

    agent -->|IAM-authenticated MCP| gateway
    gateway -->|Service trace delivery| xray
    catalogLambda --> catalog[(Encrypted DynamoDB catalog)]

    sources[Read-only source JSON] -->|Manual reproducible seed upload| sourceBucket[(Encrypted S3 source copies)]
    sourceBucket -->|Manual invocation reads| ingestion[Ingestion Lambda<br/>Ingestion execution role]
    ingestion --> catalog
```

</details>

Operational alerting is deployed; email subscription confirmation and delivery
verification remain open in the roadmap.

API Gateway is the application boundary, while AgentCore Gateway is the
authenticated tool boundary. Application routes use Cognito JWT authorization
and bind session access to the validated token subject;
AgentCore Runtime and Gateway remain IAM-authenticated internal boundaries.
The API rejects recognizable pasted credentials in new goals before storing or
queueing them. Runtime and CLI entry points share the detector; model-bound
retrieval and brief context are screened too. This is limited screening, not a guarantee that prompts or traces
are secret-free; see [input-screening limits](docs/agent-runtime.md#credential-isolation).
OpenTofu manages the AWS infrastructure.

## Development

Praxis is a monorepo with a Python backend in `backend/`, a React and TypeScript
application in `frontend/`, OpenTofu configuration in `infra/`, and evaluation
fixtures in `evals/`.

Prerequisites: Python 3.13, uv, Node.js 24–26, npm, and Make. Install locked
dependencies and run local checks without AWS credentials:

```bash
make bootstrap
make check
make help
```

Dependency installation needs network access. `make check` runs Ruff, type
checks, backend/frontend tests, and schema checks without AWS calls.
`make eval-check` runs the focused offline tests;
`make eval-artifact-check EVAL_RESULT=path` checks a local result against its policy. Neither
establishes the quality of current prompts or a deployed model.

Run `make security` to scan locked dependencies and the built local Runtime
image. It requires Podman (or `CONTAINER_TOOL=docker`) and network access, but
no AWS credentials. See [security scanning](docs/security.md#scanning) for
coverage, reports, and finding triage.

## Run with AWS

Model commands incur AWS charges even when run locally or with synthetic
fixtures. After following [account setup](docs/infrastructure-operations.md#account-access), configure
`.env` from `.env.example` and refresh the `praxis-dev` session before running:

```bash
make agent PROMPT='Build a small Python project inspired by computing history'
```

The CLI renders three candidates with evidence IDs. Use
`uv run praxis --data-dir data/fixtures --json 'your goal'` for synthetic catalog
inputs and JSON output; inference is still metered.

For the browser, follow [frontend setup](frontend/README.md) and run
`make dev-frontend`. Local Vite uses the configured AWS authentication/API;
it is not an offline application mode.

Deployed checks use `make smoke-dev`; the default is the non-inference
public-boundary suite. `./scripts/smoke/smoke-dev.sh --help` lists metered suites.
Review [cost controls](evals/README.md#cost-controls) before model smoke
tests or evaluations. Deployment and teardown require the reviewed
procedures in the [operations guide](docs/infrastructure-operations.md).

## Project guides

- [Agent runtime](docs/agent-runtime.md) and [API](docs/api.md): execution and contracts.
- [Evaluations](evals/README.md): test cases, metrics, and token controls.
- [Architecture](docs/architecture.md): component boundaries and design constraints.
- [Security](docs/security.md): trust boundaries, scanning, and known limitations.
- [Operations](docs/infrastructure-operations.md): account access, deployment, and teardown.
- [Roadmap](ROADMAP.md): implementation progress and open release gates.
