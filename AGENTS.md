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
- Record material architectural decisions in `docs/adr/`.
- Keep the architecture diagram in `README.md` aligned with accepted ADRs and
  implementation boundaries. Update it whenever components, trust boundaries,
  data flows, authentication, or deployment topology change.
- Write comments, documentation, examples, and file names for long-term readers.
  Describe current behavior, intent, and constraints without roadmap sequencing
  labels or implementation chronology. Keep progress history in `ROADMAP.md`
  and decision history in ADRs rather than scattering it through the codebase.
- Keep local development usable before requiring deployed AWS services.
- Give every shell script a `.sh` file extension.
- Never run commands that create, modify, or destroy AWS resources. The user
  must manually execute all provisioning and teardown commands, including
  `tofu apply` and `tofu destroy`, after reviewing the plan. Read-only,
  no-cost commands such as validation, planning, and resource inspection are
  allowed.
- Treat deployed development environments as temporary. Prefer on-demand
  services, avoid provisioned capacity, and keep the initial total AWS spend
  below $10. Preserve only documented bootstrap resources when tearing down.
- Keep source data in the sibling repository authoritative and read-only;
  ingested cloud copies must be disposable and reproducible.
- External actions are read-only by default. Any write must have a
  distinct authenticated preview/approval step, idempotency, and an audit trail.
- Preserve evidence provenance and identifiers. Separate retrieved facts from
  generated recommendations, and require evidence citations in agent output.

## Durable architecture constraints

- Python agent: Strands Agents SDK, hosted on Amazon Bedrock AgentCore Runtime.
- Model: Amazon Nova Micro (`amazon.nova-micro-v1:0`) in `us-east-1`, using
  on-demand in-region inference. Keep the model ID in configuration. Change the
  default only when evaluation results justify it.
- Tool boundary: AgentCore Gateway with strict MCP schemas and least-privilege
  Lambda targets.
- Application boundary: API Gateway backed by an API Lambda. AgentCore Runtime
  must not be directly callable by arbitrary public clients.
- Infrastructure: OpenTofu with the AWS provider.
- Frontend: React and TypeScript in this repository.
- MVP topology: serverless, single-user, buffered responses, and no VPC or
  multi-agent orchestration unless a demonstrated requirement changes the ADRs.

## Data and handoff

The four inputs are `../barrettotte.github.io/data/{books,projects,bytes,museum}.json`.
Never modify them during ingestion. Expected source totals are 782 books, 162
projects, 66 bytes, and 20 museum objects.

At handoff, leave the worktree understandable: report verification performed,
keep roadmap state accurate, document material tradeoffs in an ADR, and identify
the next incomplete checklist item plus any blocker that requires user input.
