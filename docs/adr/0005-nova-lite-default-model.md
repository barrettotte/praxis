# ADR 0005: Nova Lite default model

- Status: Accepted
- Date: 2026-08-30

## Context

Praxis requires reliable structured tool use and grounded project candidates
while retaining an inexpensive on-demand model. The canonical ten-case suite
ran against immutable AgentCore Runtime versions using the same dataset,
evaluator source, container digest, region, prompts, and deterministic scoring.

| Measurement | Nova Micro | Nova Lite |
| --- | ---: | ---: |
| Successful cases | 6/10 | 10/10 |
| Average quality score | 0.26 | 0.50 |
| Expected-evidence passes | 1/10 | 3/10 |
| Expected-trajectory passes | 0/10 | 1/10 |
| Concrete-milestone passes | 0/10 | 1/10 |
| Wall latency p50 | 14,998 ms | 18,831 ms |
| Wall latency p95 | 21,991 ms | 26,983 ms |
| Tokens per successful case | 9,014 | 13,230 |

The immutable measurements are stored in
`evals/project-recommendations/results/agentcore-v8-20260830T021034Z.json` and
`evals/project-recommendations/results/agentcore-v10-20260830T023643Z.json`.

## Decision

- Use Amazon Nova Lite (`amazon.nova-lite-v1:0`) as the default model with
  on-demand inference in `us-east-1`.
- Keep the model ID in configuration and pin the stable AgentCore endpoint to
  the evaluated immutable Runtime version.
- Retain least-privilege permission for Nova Micro as a measured rollback model.
- Require controlled evaluation evidence before changing the default again.

This decision supersedes only the Nova Micro default-model statements in ADR
0001 and ADR 0004; their remaining architecture and Runtime controls remain
accepted.

## Consequences

- The default eliminates the observed Runtime failures in the canonical suite
  and improves deterministic quality and evidence coverage.
- Median latency increases by 25.6%, p95 latency by 22.7%, and tokens per
  successful case by 46.8% relative to the deployed Micro baseline.
- Retrieval relevance, expected tool trajectories, and milestone concreteness
  remain weak and require workflow improvements rather than another unmeasured
  model upgrade.
- On-demand inference and temporary development deployments remain mandatory to
  preserve the project cost target.
