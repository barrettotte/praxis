# Security

Praxis is a temporary single-user application. Protect goals, identity tokens,
catalog provenance, AWS credentials, and access to paid model calls.
Use non-sensitive inputs. Generated plans are advice, not verified procedures.

## Boundaries and controls

| Boundary | Control | Important limit |
| --- | --- | --- |
| Browser → API | Cognito JWT issuer/audience validation; exact-origin CORS; strict request schemas | CORS is not authentication. A stolen valid token can perform the user's operations. |
| API → sessions/queue | JWT-subject ownership, expiry checks, server-owned candidate selection | Service roles can access state; TTL deletion is asynchronous. |
| Worker → Runtime | IAM-scoped invocation of the DEFAULT endpoint | A compromised privileged caller or AWS administrator can bypass application assumptions. |
| Runtime → Gateway/catalog | Four read-only tools, strict contracts, bounded calls, citation validation | Citations establish provenance, not truth or technical feasibility. |
| Services → telemetry | Metadata-only API access logs and application spans; restricted readers and retention | Strands traces contain prompts/results. SDK diagnostics can contain exception text. |

The Bedrock Guardrail uses a numbered Classic-tier policy with the high-strength
PROMPT_ATTACK input filter. Only the raw goal is marked guardContent; catalog records remain untrusted model context. Output and broad topic filters are not
enabled. Guardrails can miss attacks or reject legitimate inputs and do not
replace evidence, tool, and authorization checks.

Local credential screening rejects recognizable secrets before API persistence,
queueing and model calls. Model-selected tool results are
screened before entering the evidence ledger. See
[Runtime handling](agent-runtime.md#credential-isolation) for formats and limits.

## Known limitations

- **Image vulnerabilities:** a minimal image is not necessarily vulnerability-free.
  Unresolved findings require an explicit operator decision for the scanned image.
  A rebuild requires a fresh scan and review; no blanket acceptance or scanner
  suppression applies.
- **Private data:** unknown or encoded credentials and sensitive prose can pass
  screening. Session expiry does not remove traces, exports, or the
  14-day dead-letter queue. Existing data is not scrubbed.
- **Browser identity:** MFA is off; session-storage tokens are accessible to
  same-origin scripts. No application-specific CSP is declared. Sign-out is not
  proof that every issued token is immediately unusable.
- **Spending and retries:** throttles, tool limits, and budget alerts are not a
  hard spending cap. Duplicate queue deliveries and brief retries can repeat
  inference; conditional completion does not prevent duplicate paid work.
- **Tenancy:** sessions are subject-owned, but the shared catalog has no per-user
  source authorization. Additional users require an explicit data-isolation design.
- **Generated advice:** indirect injection, misleading source text, and unsafe
  or impractical plans remain possible. Human review is required before acting.
- **Compromise:** a compromised dependency, publisher, operator, or Runtime
  process retains its granted authority. General egress isolation is not established.
- **Verification:** local tests do not establish deployed cloud
  health, live saturation behavior, or managed-host isolation. Verify deployed
  behavior separately before relying on these controls.

The maintainer must approve exceptions explicitly. Revisit these limits before
adding users, private data, write tools, URL fetching, HTML rendering, or new IAM
and telemetry permissions.

## Scanning

```sh
make security SCAN=dependencies
make agent-image
make security SCAN=image AGENT_IMAGE=praxis-agent:dev
```

Pinned Trivy checks development/runtime lockfiles, the Lambda requirements lock,
and OS/language packages in the selected local image. A complementary Grype image
scan detects upstream CPython binaries that Trivy's package checks do not cover.
Both download public databases but do not access AWS or execute the image.
The command requires Podman or Docker and `jq` for report validation.
Use the ARM64 deployment image; a native AMD64 CI scan is not equivalent.

HIGH/CRITICAL findings, including unfixed advisories, and scanner errors fail the
command. Reports are `build/security/dependencies.json` and
`build/security/image.json`, and `build/security/image-binaries.json`; each selected
scan replaces its previous reports.
A missing or partial report is not a pass. The scanner mounts only inputs, its
report directory, and database cache—not AWS credentials or the container socket.
Image checks require Ubuntu identification and libc/zlib package inventory;
an OS-detection failure cannot pass as a language-only scan.
AWS-managed Lambda components and unknown advisories remain outside coverage.

Review installed/fixed versions, affected behavior, and reachability. Update
locks or the base, run local checks, rebuild, and rescan. Do not use blanket
ignores, remove package metadata, mix distributions, or force-remove Essential
packages to obtain a passing result.

## Publication review

Run `make security SCAN=image` against the image intended for publication and
review the findings. Scans fail for HIGH/CRITICAL findings; publication does not
reinterpret that result or require a separate approval document. Publishing is an
explicit operator decision using `CONFIRM=push-agent-image-dev`, not a clean-scan
claim. Review any accepted risk privately before proceeding.

The publication script pins the local image configuration ID and uses a
content-derived immutable tag. Git revision labels are descriptive metadata,
not proof of image identity. Deploy using the registry manifest digest.

## Responding to a problem

For credential exposure, stop submitting the content and have the operator
revoke or rotate the credential. Identify affected stores with non-secret
identifiers; do not paste the secret into logs, searches, or issue reports.
Agree on targeted cleanup before deleting anything. TTL and teardown do not
make a compromised credential safe.

For repeated failures or unexpected spend, stop retries, inspect bounded
metadata, and obtain approval for suspension or teardown using
[the operations guide](infrastructure-operations.md). Do not run paid tests merely
to refresh evidence.
