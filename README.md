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

Copy `.env.example` to `.env` before invoking the local Bedrock-backed agent.
Run `make dev-frontend` to start the Vite development server.
