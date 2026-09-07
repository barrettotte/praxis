# Evaluations

This directory contains evaluation inputs and expectations, not run receipts.
Generated results go to ignored `build/evals/`.

## Local checks

`make eval-check` tests input alignment and evaluation logic using synthetic data.
`make check` includes those tests. Neither invokes a model nor proves serving quality.

`project-recommendations/` contains prompts, curated evidence expectations,
bounded tool trajectories, product assertions, and an explicit threshold policy.
`project-briefs/` contains selected-idea scenarios and a review rubric.
Generated outputs do not belong in the input suite.

## Running an evaluation

All model evaluations are metered and require explicit approval. Refresh the AWS
profile and configure the intended model before running:

```sh
make eval-baseline
make eval-runtime-dev
```

The local baseline uses the shared candidate-generation pipeline with in-memory
catalog tools and Bedrock. The Runtime command
uses the named stable endpoint, waits for session-correlated Strands traces, and
invokes three managed evaluators per case. Runtime and evaluator token usage are
reported separately. Failed cases remain in the result.

Results include model, dataset, source, and deployment identities for interpretation.
They are local diagnostics, not a promise that another deployment behaves identically.
To check a result against the threshold policy without invoking AWS:

```sh
make eval-artifact-check EVAL_RESULT=build/evals/result.json
```

The policy checks suite completeness, successful responses, citation counts and
resolution, latency, and token budgets. These are operational acceptance limits,
not calibrated measures of recommendation quality. Curated evidence matches,
retrieval relevance, expected tool use, and managed evaluator scores remain
diagnostics: they do not determine the exit status or require paid evaluator runs.
Review those diagnostics and the case-specific expectations when judging usefulness.

Choose an actual generated result path. Passing the policy is not a release-quality
guarantee. Changing a model default requires review of results from the intended
configuration; do not run paid experiments merely to refresh a receipt.

## Interpreting results

- Success measures whether the request produced a valid response.
- Mechanical checks report schema validity, retrieved citation IDs, curated evidence
  coverage and expected tool use independently.
- Citation resolution only checks that IDs occur in retrieved context. It does
  not establish that sources support generated claims.
- Retrieval precision, curated-evidence coverage, and reciprocal rank compare
  retrieval with case-specific expected records, not an exhaustive relevance set.
- Managed evaluator scores are model judgments, not guarantees or substitutes
  for inspecting examples.

There is no composite mechanical quality score. Review briefs for a bounded
artifact, specific tools and inputs, observable completion checks, feasibility,
and separation of retrieved facts from generated advice.

## Prompt injection

`make eval-injection` tests instruction-bearing synthetic catalog records using
the stable Runtime's model and guardrail settings. It invokes Bedrock locally,
does not modify source data or DynamoDB, and requires explicit approval for
metered inference. Results go to ignored `build/evals/`. Marker rejection is a
focused attack test, not proof of general prompt-injection resistance.

## Cost controls

Tool and context limits bound individual requests, not total spending. Repeated
submissions and queue retries can repeat paid work. Prompt caching covers stable
instructions and tool schemas; cache hits are not guaranteed. Do not issue extra
requests just to keep a cache warm. Budget notifications are not a spending cap.
Use [operating procedures](../docs/infrastructure-operations.md) for deployment
and teardown, and prefer local tests for routine changes.
