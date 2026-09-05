# Threat model

## Scope and assumptions

Praxis is a temporary, single-user project-planning application. Protect user
goals, identity tokens, preferences, catalog provenance, AWS credentials, and
the ability to spend money through model calls. Generated recommendations are
untrusted advice, not executable instructions or verified scientific claims.

Threat actors include anonymous internet callers, a caller with a stolen valid
token, malicious text in goals/catalog/memory, and a compromised dependency or
operator workstation. AWS service isolation and the deployment operator are
trusted dependencies, not protections established by application tests. A
compromised AWS administrator can change these controls.

This is a source/configuration review with local regression tests and linked
deployment evidence, not a penetration test or a fresh audit of deployed state.
The [architecture diagram](../README.md#architecture) is the data-flow inventory;
no additional services or trust boundaries are proposed here.

## Trust boundaries

| Boundary | Data and authority crossing it |
| --- | --- |
| Browser → Cognito / API Gateway | Credentials go to Cognito; bearer JWT and goal go to the API. Browser input and identifiers are untrusted. JWT issuer/audience validation precedes Lambda; CORS is not authentication. |
| API → sessions / SQS / worker | Validated goals and JWT-subject ownership enter encrypted state/jobs. The worker is a privileged queue consumer, not another public entry point. |
| API or worker → Runtime | IAM-authorized callers supply server-owned Runtime configuration and selected candidate context. Runtime authenticates internal callers; public network mode does not mean anonymous invocation is permitted. |
| Runtime → model / Memory / Gateway | Model context remains untrusted. Memory access is read-only and namespace-limited. Gateway exposes four allowlisted, read-only catalog tools through distinct roles. |
| Source data → ingestion → catalog | An operator uploads disposable copies of authoritative JSON. Provenance identifies a source record; it does not make its text trustworthy. |
| Services → telemetry / operator tooling | Logs, traces, local reports, and deployment artifacts form a separate sensitive-data boundary. Operators with access can see more than the public API returns. |

Session ownership uses the validated JWT subject, but Runtime personalization
uses the configured application actor, not a per-user Memory namespace. This
is **not a multi-tenant architecture**. Do not add users expecting isolated
personalization without revisiting identity propagation and IAM.

## Threats, controls, and remaining exposure

| Threat | Implemented controls and verification anchors | Remaining exposure |
| --- | --- | --- |
| Unauthorized calls or stolen identity | [JWT routes](../infra/environments/dev/api_gateway.tf), admin-created [Cognito users](../infra/environments/dev/cognito.tf), IAM Runtime/Gateway boundaries; [Runtime authentication evidence](evidence/agentcore-runtime-auth.json). | Cognito MFA is off. Tokens use browser session storage, which same-origin malicious JavaScript can read. Sign-out is not evidence of immediate rejection of every previously issued token. |
| Read another session or substitute candidate facts | Server-owned selection, owner/expiry checks, conditional state updates; [session tests](../backend/tests/test_api_sessions.py) and [API integration tests](../backend/tests/test_api_integration.py). | Trusted service roles can access the table. Random session IDs do not replace authorization. Memory isolation is limited as described above. |
| Prompt injection or invented evidence | Strict schemas, evidence ledger, tool allowlist/budgets, generated-content labels; [Gateway tests](../backend/tests/test_agent_gateway.py), [injection capture](evidence/catalog-prompt-injection.json). | The [guardrail](adr/0026-versioned-prompt-attack-guardrail.md) screens the marked user goal, not all catalog/memory text. Citations prove record association, not that every generated claim follows from it. Filters and sampled evaluations are not universal defenses. |
| Credential or private-text disclosure | Local screening before persistence/model boundaries, fixed public errors, metadata-only API access logs; [screening tests](../backend/tests/test_prompt_safety.py), [Runtime rejection evidence](evidence/runtime-credential-screening.json). | Unknown/encoded secrets and sensitive prose can pass. Model traces intentionally contain content; SDK diagnostics may precede screening. See [screening limits](adr/0027-goal-credential-screening.md). Encryption does not prevent authorized readers from seeing plaintext. |
| Cost abuse, retries, or unavailable dependencies | Route throttles, input/result/tool limits, bounded SDK attempts, safe failed states; [API failure tests](../backend/tests/test_api_integration.py), [worker configuration](../infra/environments/dev/recommendation_worker.tf). | Throttles are not a spending cap or a concurrency guarantee. The worker invokes Runtime before conditional completion; duplicate delivery can repeat metered work. Brief retries can also repeat inference. Budget alerts do not stop spend. |
| Compromised image, dependency, or role | Locked dependencies, digest-pinned Runtime publication, separate scoped roles, non-root image; [role evidence](evidence/iam-role-separation.json), [security scanning](security-scanning.md). | [Container findings remain open](container-risk-review.md); local hardening is not proof of deployed protection. A compromised Runtime process retains its role's model, Memory-read, Gateway, and telemetry permissions. No general network-egress isolation is established. |
| Browser script injection or asset tampering | React text rendering, private S3 origin, signed CloudFront origin reads, HTTPS; [hosting configuration](../infra/environments/dev/frontend_hosting.tf). | A compromised frontend dependency or publisher can steal tokens or alter requests. There is no application-specific CSP declared here; adding raw HTML, executable markdown, or arbitrary generated links requires renewed review. |
| Source poisoning or operator compromise | Read-only authoritative source workflow, normalized ingestion, stable IDs, read-only catalog tools. | An authorized source editor/publisher can poison facts or replace artifacts. Cloud copies are reproducible, but not an independent authenticity guarantee. Workstation credentials and infrastructure state need operator protection. |

## Data lifetime and operational limits

- Session records enforce application expiry on read and use a one-hour TTL
  when created/completed. TTL is not a verified deadline for physical deletion.
- Recommendation jobs can remain in SQS for one day; the dead-letter queue is
  configured for **14 days**, including the goal and subject. Session expiry
  does not remove queued copies.
- Declared application/Runtime log retention is seven days. Do not infer that
  every X-Ray, evaluation export, local report, or manual copy shares that limit.
- Source copies and explicit Memory records have separate lifecycles; there is
  no blanket one-hour deletion or automatic removal of previously pasted secrets.

## Verification and follow-up

Run `make check` for local boundary regressions. Configuration and explicitly
metered deployment checks are described in the [operations guide](infrastructure-operations.md).
Existing captures record specific probes, not continuous assurance; for example,
the [API capture](evidence/api-gateway.json) records a synchronous response and
does not certify the current asynchronous workflow. Local integration tests
exercise API → queue → worker → Runtime → status with injected dependencies.

Keep container remediation and any risk-exception approval separate from this
document. The [residual-risk register](residual-risks.md) records priorities,
proposed ownership, and handling actions; none are accepted by documenting them.
Revisit this model when adding users, write tools, arbitrary URL retrieval,
HTML/markdown rendering, new telemetry, or changes to credentials and IAM.
