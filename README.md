# praxis

An Amazon Bedrock and AgentCore app that uses personal evidence to recommend worthwhile software projects and turn ideas into actionable briefs.

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
