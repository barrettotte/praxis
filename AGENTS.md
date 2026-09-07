# Praxis agent guide

`ROADMAP.md` is the source of truth for scope, sequencing, and progress. Read it
completely before starting work, inspect the repository and git status, and
preserve unrelated user changes.

## Working conventions

- Work on the earliest incomplete roadmap item unless the user selects other work.
- Complete one small, verifiable checklist slice at a time. Update a roadmap
  checkbox only after the implementation or external condition is verified.
- After each substantial verified slice, suggest a concise commit message unless
  the user says the changes will be bundled with other work.
- Keep material architecture choices and constraints in `docs/architecture.md`.
- Keep the architecture diagram in `README.md` aligned with that guide and
  implementation boundaries. Update it whenever components, trust boundaries,
  data flows, authentication, or deployment topology change.
- Write comments, documentation, examples, and file names for long-term readers.
  Describe current behavior, intent, and constraints without roadmap sequencing
  labels, decision chronology, or session narratives. Describe what the code does,
  not the experiments or conversations that led to it.
- Keep `ROADMAP.md` to open work, current blockers, and next actions. Do not keep
  completed-work narratives, deployment identities, test counts, or run receipts.
- Public documentation must describe current behavior, configuration, and limits.
  Keep generated results in ignored build/ artifacts and deployment settings,
  risk approvals, and private handoff notes in ignored local files. Commit reusable
  evaluation inputs and synthetic test fixtures, not experiment outputs.
- Keep local development usable before requiring deployed AWS services.
- Give every shell script a `.sh` file extension.
- Add deployed checks to the named `smoke-dev` suites instead of creating new
  Make targets. Keep mutating checks separate with explicit confirmation.
- A coding agent may run a provisioning `tofu apply` only from the exact saved
  plan it generated, reviewed, and summarized for the user. Regenerate and
  review the plan if configuration or state changes afterward. Teardown and
  other destructive commands require explicit user approval for each run.
  Keep other AWS-mutating commands manual unless the user explicitly requests
  them. Read-only, no-cost validation, planning, and inspection are allowed.
- Treat deployed development environments as temporary. Prefer on-demand
  services, avoid provisioned capacity, and keep the total development AWS spend
  below $10. Preserve only documented bootstrap resources when tearing down.
- Prefer local tests and available local diagnostics over fresh AWS executions. Obtain
  explicit approval before metered model smoke tests or evaluations;
  do not repeat them merely to refresh evidence. Keep cloud inspection bounded.
- Keep source data in the sibling repository authoritative and read-only;
  ingested cloud copies must be disposable and reproducible.
- Keep AgentCore Gateway tools and external integrations read-only. External
  write workflows are outside product scope.
- Preserve evidence provenance and identifiers. Separate retrieved facts from
  generated recommendations, and require evidence citations in agent output.
- Start each shell script (after its shebang) and OpenTofu file with a concise
  purpose comment. Comment non-obvious blocks and invariants without narrating
  straightforward commands or resource names.

## Durable architecture constraints

- Python agent: Strands Agents SDK, hosted on Amazon Bedrock AgentCore Runtime.
- Model: Amazon Nova Pro (`amazon.nova-pro-v1:0`) in `us-east-1`, using
  on-demand in-region inference. Keep the model ID in configuration and require
  evaluation evidence for future model changes. One structured-output contract
  is supported; other models require validation rather than compatibility adapters.
- Tool boundary: AgentCore Gateway with strict MCP schemas and least-privilege
  Lambda targets.
- Personalization across sessions is outside scope; retain only expiring,
  subject-owned application sessions and authoritative catalog data.
- Application boundary: API Gateway backed by an API Lambda. AgentCore Runtime
  must not be directly callable by arbitrary public clients.
- Infrastructure: OpenTofu with the AWS provider.
- Frontend: React and TypeScript in this repository.
- MVP topology: serverless, single-user, buffered responses, and no VPC or
  multi-agent orchestration unless a demonstrated requirement changes the architecture.

## Data and handoff

The four inputs are `../barrettotte.github.io/data/{books,projects,bytes,museum}.json`.
Never modify them during ingestion. Derive current totals from the authoritative
files and verify that deployed ingestion matches them.

At handoff, leave the worktree understandable: report verification performed,
keep roadmap state accurate, update current architecture constraints, and identify
the next incomplete checklist item plus any blocker that requires user input.
