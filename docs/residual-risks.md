# Residual risks

This register turns the [threat model](threat-model.md) into review actions for
the temporary, single-user deployment. Priorities are project triage judgments,
not measured exploit probabilities or replacements for advisory severity.
**Every entry is open; documenting it does not accept the risk.**

The proposed accountable owner for all entries is the repository maintainer,
acting as deployment operator. That role must approve any exception; an agent
may investigate and implement authorized fixes but must not accept risk on the
owner's behalf. No acceptance or expiry dates are assigned without approval.

## Prioritized register

| ID / priority | Exposure and existing limits | Proposed handling and review trigger |
| --- | --- | --- |
| R1 / release gate | Unresolved image advisories; local hardening does not establish deployed protection. Scanning fails without suppression. | Follow the [container review](container-risk-review.md): remediate or obtain advisory/package-specific, expiring approval. Rescan the intended image before publication and verify the deployed digest and smoke checks before claiming mitigation. |
| R2 / high | Undetected secrets or private prose can reach state, queues, model traces, or SDK diagnostics despite input screening. Session expiry does not erase all copies; DLQ retention is 14 days. | Use non-sensitive inputs. Inventory reader permissions and retention for logs, traces, exports, Memory, and queues before handling private material. Decide whether content tracing and DLQ retention need reduction; verify any approved change independently of session TTL. Follow [credential handling](agent-runtime.md#credential-isolation) if exposure occurs. |
| R3 / high | A stolen browser token permits the user's operations. MFA is off, session-storage tokens are accessible to same-origin scripts, and no application-specific CSP is declared. | Review MFA and a tested CSP before widening access or storing more sensitive data. Preserve text-only rendering and avoid token logging. Test the account/token response procedure rather than assuming sign-out immediately invalidates every token. |
| R4 / high | Throttles and bounded model turns limit individual work, not total spend. Duplicate queue delivery and repeated brief selection can repeat inference; budgets only notify. | Review usage while deployed and use approved teardown during inactivity. Measure duplicate processing and error rates; evaluate a worker claim/idempotency control if duplicate work is observed. Prioritize cost/error alarms in observability work; do not describe them as a hard spending cap. |
| R5 / scope gate | Sessions are JWT-subject-owned, but Memory personalization uses a deployment-wide actor. IAM-scoped read access is not per-user personalization isolation. | Keep the single-user boundary. Before adding another user, design subject-to-Memory identity propagation and verify cross-user denial at both the application and IAM boundaries. |
| R6 / medium | Indirect prompt injection, misleading source text, and unsupported or unsafe generated advice remain possible. Schemas/citations constrain shape and provenance, not truth or feasibility. | Keep tools read-only and require human review before acting on a brief. Rerun injection and quality evaluations after model, prompt, tool, or source changes. Revisit the threat model before allowing writes, URL fetching, or executable output. |
| R7 / high | A compromised publisher, dependency, Runtime process, or operator workstation can act with its granted authority. There is no demonstrated general egress restriction. | Review dependency/artifact changes and protect operator credentials/state. Reassess role permissions and egress when adding integrations. Keep deployment approval separate from a clean local build; no claim of resistance to AWS administrator compromise. |
| R8 / verification gap | Hosted CI is unverified while allowance is unavailable; some captures predate the asynchronous workflow. Local tests do not prove live saturation behavior, managed-host isolation, or current deployment state. | Retain local checks and record their limits. Refresh relevant deployed evidence after authorized publication, including the asynchronous API path; run hosted CI when available. Do not close release gates based solely on old captures or unit tests. |

## Decision and closure rules

- An open entry needs either verified mitigation or an explicit owner decision
  describing scope, rationale, residual impact, review deadline, and expiry.
  An accepted ADR is not a blanket vulnerability exception.
- A mitigation is complete only when its relevant tests/configuration checks
  pass. If it changes deployed behavior, record deployment verification too.
- Review this register before a showcase release and whenever exposure changes.
  Scope gates must be resolved before the named expansion, not afterward.
- Keep R1 separate: the HIGH/CRITICAL scanner gate remains strict. This register
  grants no permission to suppress findings, publish images, or mutate AWS.

## Operational response

For suspected credential exposure, stop submitting the affected content and
have the operator revoke or rotate the credential. Identify affected stores
and telemetry using non-secret identifiers; do not paste the secret into a
search query or incident note. Restrict access and agree on any targeted cleanup
before executing it. Session expiry and teardown are not proof that external
copies or compromised credentials are safe.

For unexpected spend or repeated failures, stop manual retries, inspect bounded
metadata and budget notifications, and have the operator approve any suspension
or teardown through the [operations guide](infrastructure-operations.md).
Record decisions and sanitized verification without copying prompts or tokens.
