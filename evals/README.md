# Evaluations

Evaluation prompts, expected evidence, expected tool trajectories, and measured
results belong here.

## Cost and token controls

Prefer existing artifacts and local checks. Coding agents require explicit
approval before metered model smoke tests, evaluations, or DSPy experiments;
do not rerun them merely to refresh evidence.

| Command | AWS usage |
| --- | --- |
| `make check`, `make eval-check`, `make eval-regression` | None; local tests and recorded results |
| `make eval-projections`, `make eval-retrieval-limits` | None; read-only local catalog comparisons |
| `make agent`, `make eval-baseline` | Metered Bedrock inference, despite running locally |
| `make eval-dspy-instructions` | Multiple metered Bedrock optimization and comparison calls |
| `make eval-runtime-dev` | Runtime inference, trace reads, and managed evaluator calls |

The serving path limits context through projected catalog fields, a three-result
initial retrieval, bounded tool turns, and separate recommendation/brief
operations without accumulated conversation history. The
[projection artifact](catalog-projections/results/catalog-projections-cb225f014349.json)
measures 227,099 full-record bytes versus 199,239 projected bytes: a 12.3%
reduction, **not** a token or billing estimate. The retrieval-limit comparison
below explains why simply increasing context is not the default optimization.

A cache point covers stable recommendation instructions and tool schemas,
excluding variable goals, evidence, and Memory context. Cache hits are not
guaranteed, and isolated requests may not reuse the prefix. See the
[cache decision and measured token reuse](../docs/adr/0023-explicit-prompt-caching.md).
Do not send extra requests just to keep a cache warm.

Keep the maintained instruction: the
[DSPy comparison](../docs/adr/0024-dspy-instruction-optimization.md) does not
justify promoting the optimized alternative. Nova Pro remains the configured
default for measured reliability; the
[model comparison](../docs/adr/0025-nova-pro-default-model.md) records the
quality/cost tradeoff. Its model-cost estimates exclude managed evaluators and
other AWS services and must not be treated as total project spend or current
pricing. Runtime tokens and evaluator tokens are separate artifact fields.

Tool/turn limits constrain individual requests, not total spending. Repeated
browser submissions and queue retries can cause duplicate paid work; budget
notifications are not an application spending cap. Keep deployments temporary
and follow the reviewed
[teardown procedure](../docs/infrastructure-operations.md) during long
pauses. Neither teardown nor a fresh paid experiment is part of local validation.

## Measurements and experiments

`catalog-projections/results/` contains content-addressed measurements comparing
the authoritative source records with the exact evidence objects exposed to the
agent. Run `make eval-projections` to reproduce the compact-JSON UTF-8 byte and
field comparison. This isolates context payload reduction without claiming that
bytes are model tokens; deployed evaluation artifacts record actual token use.

`retrieval-limits/results/` compares the production lexical query and ranking at
result limits 3, 5, 10, and 20 over the canonical prompts and curated evidence.
Run `make eval-retrieval-limits` to reproduce evidence pass counts, precision,
coverage, reciprocal rank, and exact projected response bytes. On the 1,034-item
catalog snapshot, increasing the production prefetch limit from 3 to 5 added 64%
more response bytes without improving the 9-of-30 evidence pass count. Limits 10
and 20 reached 10 and 12 passes but used about 3.2 and 6.3 times the bytes. The
prefetch limit therefore remains 3; retrieval ranking and query quality offer a
better improvement target than increasing context indiscriminately.

`project-recommendations/prompts.json` is the canonical 30-prompt evaluation
input. Case IDs are stable references for expectations and baseline results; do
not renumber them when prompts are retired or the suite expands. This file
intentionally contains only prompts and coverage metadata. Expected evidence
and trajectories are recorded in
`project-recommendations/expectations.json` so evaluation inputs do not
accidentally disclose answers to the agent. Evidence sets use an `any_of` policy
to permit multiple relevant records without coupling the suite to a single
ranking. Case-aligned product requirements for judged evaluation are kept in
`project-recommendations/business-assertions.json`.

Result files must identify the model, region, code revision, dataset, run time,
and content hashes. Deployed results also identify the named endpoint qualifier,
immutable Runtime version, and container digest without storing resource,
account, session, trace, or span identifiers. Quality is the mean of five
deterministic checks: valid structured output, grounded citations, curated
evidence coverage, expected local-tool trajectory, and concrete first
milestones. A milestone is considered concrete when it contains at least six
words and an action verb from the runner's documented vocabulary. Never replace
historical measurements in place.

Retrieval relevance is measured separately from generated-answer quality. For
each case, the runner compares the ordered retrieval context with the curated
`any_of` records and records precision at the returned cutoff, expected-evidence
coverage, and reciprocal rank. Suite averages include unsuccessful cases as
zero so reliability failures cannot inflate retrieval measurements.

Each evidence citation contains one generated connection claim. Citation
correctness requires its evidence ID to resolve inside the case's actual
retrieval context. The complementary unsupported-claim rate counts connection
claims whose citations lack that provenance. These measurements enforce the
retrieval-to-citation boundary but do not treat the curated relevant set as
exhaustive; the managed correctness evaluator remains the semantic check over
the full response.

Run the locally hosted, metered model suite with `make eval-baseline`. Run the same fixtures and scoring
against the stable development Runtime manually with:

```shell
make eval-runtime-dev
```

The deployed command makes 30 metered Runtime invocations and waits for each
session-correlated CloudWatch trace, so it can take several minutes. Each case
uses a fresh session. Failures are recorded in the immutable result artifact and
do not stop the remaining cases. Each correlated trace is also scored on demand
by the managed `Builtin.GoalSuccessRate`, `Builtin.Correctness`, and
`Builtin.ToolSelectionAccuracy` AgentCore evaluators. Goal success receives the
case's business assertions; correctness targets response traces; tool selection
targets the observed Strands tool spans. The Runtime response supplies
candidates, citations, and Gateway call counts; correlated Strands spans supply model
latency, first-token latency, token usage, structured-output tool calls, and
event-loop cycles. `summarize_experience` is compared with the local
`compare_project_history` expectation because they represent the same catalog
operation on opposite sides of the Gateway boundary.

The 30-case deployed run makes 30 Runtime invocations and up to 90 managed
evaluation requests. All are metered. Result artifacts retain evaluator IDs,
aggregate scores, labels, error codes, and evaluator token counts, but never
retain judge explanations, prompts, responses, session IDs, trace IDs, or span
IDs. A read-only evaluator preflight runs before any metered invocation.

The deployed command reads its model and image identity from the immutable
Runtime version served by the endpoint. `RUNTIME_EVAL_TRACE_TIMEOUT_SECONDS`
changes the per-case trace wait.

Check a sanitized result artifact against the reviewed regression policy with:

```shell
make eval-check
make eval-regression
make eval-regression REGRESSION_RESULT=path/to/result.json
```

`eval-check` is the single offline entry point for evaluation fixture schemas,
cross-file alignment, deterministic scoring behavior, and the accepted baseline.
It requires only locked repository dependencies and performs no network calls,
so it is suitable for local development and CI. The repository-wide `make check`
also enforces the accepted baseline regression gate.

`eval-regression` defaults to the accepted Nova Pro baseline. The versioned policy in
`project-recommendations/regression-thresholds.json` requires at least 27 of 30
successful cases, preserves citation provenance as an absolute invariant, and
sets bounded quality, retrieval, latency, token, and managed-evaluator gates.
This command is offline and never invokes AWS or a model.

Run the development-only, metered DSPy instruction comparison with:

```shell
make eval-dspy-instructions
```

The command uses MIPROv2 to optimize a zero-shot instruction over the fixed
15-case training and five-case validation partitions in
`project-recommendations/dspy-split.json`. It then evaluates the maintained and
optimized instructions against the same ten untouched held-out cases. Both
variants use Nova Lite, the same retrieved evidence, the same
`ProjectCandidateSet` output contract, and deterministic checks for schema
validity, citation grounding, curated evidence coverage, and concrete first
milestones. DSPy is an offline development dependency; the command records a
comparison artifact and never changes the production instruction automatically.
The optimization and comparison make multiple metered Bedrock requests and are
therefore not part of `make check` or a deployed smoke suite. Override
`DSPY_MODEL_ID` only for an explicitly labeled model experiment.

`project-briefs/cases.json` is the versioned five-scenario brief-quality seed.
It covers straightforward, constrained, and infeasible selected ideas,
including a speculative quantum-materials project. Its separate expectations
require goal alignment, feasibility, specificity, testability, and evidence
discipline, and record claims that must not appear. Keep these inputs separate
from measured results so future prompt or model comparisons use the same
scenarios and rubric.
