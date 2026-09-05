# Five-minute demonstration

## Preparation

Use the evidence walkthrough by default: it requires no AWS calls. Open the
linked files beforehand and use a local Markdown preview for the architecture
diagram. Describe captures as recorded evidence, not a live health check. Do
not display `.env`, browser storage, authorization headers, raw traces, account
identifiers, or private prompts.

With dependencies installed, verify the local checks before presenting:

```sh
make eval-check
npm --prefix frontend test
```

These checks use stored evaluation results and mocked frontend services. They
do not generate recommendations or prove the current deployment is healthy.

## Presentation outline

| Time | Show | Say |
| --- | --- | --- |
| 0:00–0:40 | [README architecture](../README.md#architecture) | “Praxis turns a learning goal into three candidates and a selected-project brief, grounded in my catalog. Bedrock supplies inference; AgentCore hosts the Strands agent and its secured tool boundary.” |
| 0:40–1:35 | [Frontend workflow](../frontend/README.md) and [candidate rendering tests](../frontend/src/CandidateCards.test.tsx) | “The browser signs in with Cognito. Requests enter through the API, run on a queued worker, and are polled until ready. Cards separate generated ideas from supporting catalog evidence.” |
| 1:35–2:15 | [Brief rendering and retry tests](../frontend/src/GoalEntry.test.tsx) | “Selection sends identifiers, not an editable candidate. The server resolves the owned session and generates a brief with an approach, deliverables, milestones, and verification steps. Errors restore a retry control without exposing dependency diagnostics.” |
| 2:15–3:05 | [Runtime trace summary](evidence/agentcore-runtime-traces.json) and [input-rejection evidence](evidence/runtime-credential-screening.json) | “The summary records session-correlated Strands operations. Separate synthetic probes demonstrate credential rejection at the Runtime input boundary. These are different recorded runs, not a recovery trace or proof that all telemetry is secret-free.” |
| 3:05–4:00 | [Model comparison](adr/0025-nova-pro-default-model.md) and [cost controls](../evals/README.md#cost-and-token-controls) | “The matched comparison produced valid output in 29 of 30 Pro cases versus 21 for Lite. Citation provenance does not prove generated claims are true. Local regression checks reuse measurements; DSPy and managed evaluations cost money and are opt-in.” |
| 4:00–5:00 | [Threat model](threat-model.md) and [residual risks](residual-risks.md) | “This is a single-user, read-only-tool demonstration, not a production assurance claim. Memory uses a deployment-wide actor. Container findings and broader trace verification remain open. Generated plans need human review.” |

## Evidence coverage

| Artifact | What it supports | What it does not establish |
| --- | --- | --- |
| [Runtime invocation](evidence/agentcore-runtime-invocation.json) | A signed invocation with three cited candidates and Memory retrieval, at the recorded Runtime version. | Current health, individual span timing, or end-to-end browser tracing. |
| [Runtime trace summary](evidence/agentcore-runtime-traces.json) | One session-correlated trace with 15 spans and recorded operation/scope names. | A retained span tree with parent relationships, durations, and outcomes; it is not the same version as the invocation capture. |
| [Runtime input rejection](evidence/runtime-credential-screening.json) | Three synthetic invalid-input probes returned handler HTTP 400 without reflection; bounded log inspection recorded correlated rejections and no model spans. | Universal secret detection, all possible telemetry, or failure followed by recovery. |

For a successful trace walkthrough, retain a privacy-reviewed span view with
operation names, parent relationships, durations, and outcomes tied to the
recorded request result. For failure/recovery, retain the failed attempt and its
related successful retry or resubmission, explaining whether the application or
operator initiated it. Unrelated success and rejection files cannot be combined
to claim recovery. Remove content, credentials, and unnecessary identifiers;
preserve relationships with consistent local aliases where needed.

Prefer already retained evidence. New metered requests require approval and
must not be triggered just to fill these gaps during the presentation.

## Optional live workflow

Only replace the workflow/test segment with a browser demonstration after
explicit approval for metered work. Local Vite uses the configured AWS backend;
it is not an offline demo mode.

1. Use an already deployed application and sign in before sharing the screen.
   Do not create accounts, publish images, or provision resources during the demo.
2. Submit one non-sensitive goal, such as “Suggest a weekend Python project
   inspired by computing history, using only my laptop.”
3. Show the pending state, compare candidates, and inspect one cited source.
   Explain that the generated connection is not a quotation from that source.
4. Select one candidate and inspect its approach, first milestone, and acceptance
   check. This triggers another model operation; content and timing vary.
5. If the request fails or exceeds the allotted time, return to the evidence
   walkthrough. Do not repeatedly retry, reseed, run evaluations, or change the
   deployment to rescue the presentation. Sign out when finished.

One submission and one selection are the intended live scope, not a guarantee
of exactly two billable calls: model/tool turns and delivery retries may add work.
Review any screenshot or recording for private information before sharing. A
recorded video and a deployed failure-and-recovery trace are separate artifacts;
this script does not stand in for either.
