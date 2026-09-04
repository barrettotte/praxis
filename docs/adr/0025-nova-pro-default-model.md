# ADR 0025: Nova Pro default model

- Status: Accepted
- Date: 2026-09-04

## Context

Praxis requires reliable structured project recommendations while preserving
evidence provenance and an inexpensive on-demand deployment. Nova Lite was the
measured default, but its expanded 30-case evaluation still failed nine cases.

Nova Lite and Nova Pro were evaluated through immutable AgentCore Runtime
versions using the same source hash, 1,034-record catalog snapshot, prompts,
evaluators, region, and container digest. Nova Pro uses its native nested
structured-output schema because its Bedrock tool-use adapter did not reliably
populate the atomic JSON-string schema required by Nova Lite.

| Measurement | Nova Lite v44 | Nova Pro v46 |
| --- | ---: | ---: |
| Successful cases | 21/30 | 29/30 |
| Average quality score | 0.36 | 0.60 |
| Expected-evidence passes | 4/30 | 9/30 |
| Expected-trajectory passes | 6/30 | 21/30 |
| Concrete-milestone passes | 2/30 | 2/30 |
| Retrieval precision at k | 0.111 | 0.189 |
| Expected-evidence coverage | 0.088 | 0.166 |
| Mean reciprocal rank | 0.211 | 0.317 |
| Citation correctness | 100% | 100% |
| Wall latency p50 | 29,858 ms | 30,939 ms |
| Wall latency p95 | 40,275 ms | 39,511 ms |
| Runtime tokens | 104,852 | 98,136 |
| Estimated Runtime model cost | $0.0064 | $0.0834 |

The cost estimate applies current on-demand text-token rates, including the 90%
cache-read discount, to Runtime generation only. It excludes shared AgentCore
infrastructure and managed evaluator inference. The immutable measurements are
stored in
[`agentcore-v44-20260904T165105Z.json`](../../evals/project-recommendations/results/agentcore-v44-20260904T165105Z.json)
and
[`agentcore-v46-20260904T175002Z.json`](../../evals/project-recommendations/results/agentcore-v46-20260904T175002Z.json).

## Decision

- Use Amazon Nova Pro (`amazon.nova-pro-v1:0`) as the default model with
  on-demand in-region inference in `us-east-1`.
- Pin the stable AgentCore endpoint to evaluated Runtime version 46 and its
  immutable container digest.
- Retain least-privilege access to Nova Lite and Nova Micro as measured rollback
  models.
- Keep the model-specific structured-output adapter isolated at the model
  boundary; both paths normalize into the same validated public contract.
- Require controlled evaluation evidence before changing the default again.

This decision supersedes ADR 0005's Nova Lite default. Its requirements for
configured model IDs, immutable Runtime promotion, and measured changes remain
accepted.

## Consequences

- Successful output increases by eight cases and average deterministic quality
  increases by 0.24 in the matched suite.
- Median latency increases by 3.6%, p95 latency decreases by 1.9%, and Runtime
  token use decreases by 6.4%.
- Estimated model inference cost is 13.1 times Lite, but remains below one cent
  per successful recommendation in this measurement.
- The one Pro failure returned duplicate candidate titles for an infeasible
  clinical-diagnosis prompt; semantic validation rejected the response rather
  than exposing invalid candidates.
- No deployment topology or trust boundary changes. The README diagram changes
  only the model label.

## References

- [Amazon Nova Pro model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-pro.html)
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [Amazon Bedrock prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
