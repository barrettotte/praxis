# praxis

An Amazon Bedrock and AgentCore app that uses personal evidence to recommend worthwhile software projects and turn ideas into actionable briefs.

## Architecture

Praxis follows this serverless target architecture:

```mermaid
flowchart TD
    user[User] --> ui[React + TypeScript application]
    ui -->|Authenticate| cognito[Amazon Cognito]
    cognito -->|JWT| ui
    ui -->|JWT request| apiGateway[Amazon API Gateway]
    apiGateway --> apiLambda[API Lambda]

    subgraph runtime[Amazon Bedrock AgentCore Runtime]
        agent[Python 3.13 ARM64 container<br/>Strands agent]
        memory[AgentCore Memory]
        agent --> memory
    end

    apiLambda --> agent
    agent --> bedrock[Amazon Bedrock<br/>Nova Micro]

    subgraph tools[AgentCore Gateway MCP tool boundary]
        gateway[AgentCore Gateway]
        catalogLambda[Catalog Lambda]
        githubLambda[GitHub Lambda]
        researchLambda[Research Lambda]
        gateway --> catalogLambda
        gateway --> githubLambda
        gateway --> researchLambda
    end

    agent -->|IAM-authenticated MCP| gateway
    catalogLambda --> catalog[(DynamoDB catalog)]
    githubLambda --> github[GitHub API]
    researchLambda --> external[External APIs]

    sources[Read-only source JSON] -->|Reproducible seed| sourceBucket[(S3 source copies)]
    sourceBucket --> ingestion[Ingestion Lambda]
    ingestion --> catalog
```

API Gateway is the application boundary, while AgentCore Gateway is the
authenticated tool boundary. OpenTofu manages the AWS infrastructure.

## Development

Praxis is a monorepo with a Python backend in `backend/`, a React and TypeScript
application in `frontend/`, OpenTofu configuration in `infra/`, and evaluation
fixtures in `evals/`.

Install the Python 3.13 environment and list the available commands:

```bash
make bootstrap
make help
```

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
