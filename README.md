# praxis

An Amazon Bedrock and AgentCore app that uses personal evidence to recommend worthwhile software projects and turn ideas into actionable briefs.

## Architecture

Praxis follows this serverless architecture:

```mermaid
flowchart TD
    user[User] -->|HTTPS| edge[Amazon CloudFront]
    edge -->|Signed OAC reads| frontendAssets[(Private S3 frontend assets)]
    edge -->|Serve application| ui[React + TypeScript in browser]
    ui -->|Authenticate| cognito[Amazon Cognito]
    cognito -->|JWT| ui
    ui -->|JWT request| apiGateway[Amazon API Gateway HTTP API]
    apiGateway --> apiLambda[API Lambda]
    apiLambda -->|Store/read expiring session state| sessions[(DynamoDB sessions<br/>TTL enabled)]
    apiLambda -->|Queue validated goal| jobs[[Encrypted SQS<br/>recommendation jobs]]
    jobs --> worker[Recommendation worker Lambda]
    jobs -.->|Retries exhausted| deadLetter[[Encrypted SQS<br/>dead-letter queue]]
    worker -->|Complete ready or failed state| sessions

    subgraph runtime[Amazon Bedrock AgentCore Runtime]
        runtimeEndpoint[stable endpoint<br/>Pinned Runtime version]
        agent[Python 3.13 ARM64 container<br/>Strands agent]
        memory[AgentCore Memory]
        runtimeEndpoint --> agent
        agent -->|Read typed preferences and decisions| memory
    end

    worker -->|Generate candidates| runtimeEndpoint
    apiLambda -->|Generate selected project brief| runtimeEndpoint
    agent --> bedrock[Amazon Bedrock<br/>Nova Lite]
    agentImage[(Amazon ECR<br/>agent image)] -->|Immutable image digest| agent

    subgraph observability[Application and agent observability]
        apiAccessLogs[CloudWatch Logs<br/>API access metadata]
        runtimeSpans[CloudWatch Logs<br/>Runtime span stream]
        xray[AWS X-Ray ingest]
        cloudwatch[CloudWatch transaction search]
        xray --> cloudwatch
    end

    apiGateway -->|Privacy-safe access records| apiAccessLogs
    agent -->|Strands OTEL spans via ADOT| xray
    agent -->|Session-correlated OTEL spans| runtimeSpans

    subgraph evaluation[Manual evaluation path]
        evalRunner[Local evaluation runner]
        managedEvaluators[AgentCore Evaluations<br/>Managed evaluators]
        evalRunner -->|OTEL spans + reviewed assertions| managedEvaluators
    end

    evalRunner -->|Isolated metered sessions| runtimeEndpoint
    evalRunner -->|Read correlated spans| runtimeSpans

    subgraph tools[AgentCore Gateway MCP tool boundary]
        gateway[AgentCore Gateway]
        catalogLambda[Catalog Lambda]
        gateway --> catalogLambda
    end

    agent -->|IAM-authenticated MCP| gateway
    catalogLambda --> catalog[(DynamoDB catalog)]

    sources[Read-only source JSON] -->|Manual reproducible seed upload| sourceBucket[(S3 source copies)]
    sourceBucket -->|Manual invocation reads| ingestion[Ingestion Lambda]
    ingestion --> catalog
```

API Gateway is the application boundary, while AgentCore Gateway is the
authenticated tool boundary. Application routes use Cognito JWT authorization;
AgentCore Runtime and Gateway remain IAM-authenticated internal boundaries.
OpenTofu manages the AWS infrastructure.

## Development

Praxis is a monorepo with a Python backend in `backend/`, a React and TypeScript
application in `frontend/`, OpenTofu configuration in `infra/`, and evaluation
fixtures in `evals/`.

Install the Python 3.13 environment and list the available commands:

```bash
make bootstrap
make help
```

Run all local quality checks with `make check`. Deployed smoke checks use one
suite command; `make smoke-dev` runs the non-inference configuration suite, and
`./scripts/smoke/smoke-dev.sh --help` lists the explicitly metered suites.

The frontend requires the public Cognito and API values shown in
`frontend/.env.example`; `frontend/README.md` describes the local setup.

Copy `.env.example` to `.env`, refresh the `praxis-dev` AWS session, and run the
local evidence-backed command-line demonstration:

```bash
make agent PROMPT='Build a small Python project inspired by computing history'
```

The command renders three readable candidates with evidence IDs. Use
`uv run praxis --json 'your goal'` for the validated JSON representation, or
`--data-dir data/fixtures` to use synthetic fixtures. Run `make dev-frontend` to
start the Vite development server.

The [agent runtime guide](docs/agent-runtime.md) documents the Strands loop,
AgentCore Gateway tool boundary, and evidence-grounding invariants. Deployment
and teardown commands are in
[the infrastructure operations guide](docs/infrastructure-operations.md).
