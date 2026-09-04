# Evaluations

Evaluation prompts, expected evidence, expected tool trajectories, and measured
results belong here.

`project-recommendations/prompts.json` is the canonical ten-prompt evaluation input. Case IDs are
stable references for expectations and baseline results; do not renumber them
when prompts are retired or the suite expands. This file intentionally contains
only prompts and coverage metadata. Expected evidence and trajectories are
recorded in `project-recommendations/expectations.json` so evaluation inputs do not accidentally
disclose answers to the agent. Evidence sets use an `any_of` policy to permit
multiple relevant records without coupling the suite to a single ranking.

Result files must identify the model, region, code revision, dataset, run time,
and content hashes. Deployed results also identify the named endpoint qualifier,
immutable Runtime version, and container digest without storing resource,
account, session, trace, or span identifiers. Quality is the mean of five
deterministic checks: valid structured output, grounded citations, curated
evidence coverage, expected local-tool trajectory, and concrete first
milestones. A milestone is considered concrete when it contains at least six
words and an action verb from the runner's documented vocabulary. Never replace
historical measurements in place.

Run the local suite with `make eval-baseline`. Run the same fixtures and scoring
against the stable development Runtime manually with:

```shell
make eval-runtime-dev
```

The deployed command makes ten metered Runtime invocations and waits for each
session-correlated CloudWatch trace, so it can take several minutes. Each case
uses a fresh session. Failures are recorded in the immutable result artifact and
do not stop the remaining cases. The Runtime response supplies candidates,
citations, and Gateway call counts; correlated Strands spans supply model
latency, first-token latency, token usage, structured-output tool calls, and
event-loop cycles. `summarize_experience` is compared with the local
`compare_project_history` expectation because they represent the same catalog
operation on opposite sides of the Gateway boundary.

The deployed command reads its model and image identity from the immutable
Runtime version served by the endpoint. `RUNTIME_EVAL_TRACE_TIMEOUT_SECONDS`
changes the per-case trace wait.

`project-briefs/cases.json` is the versioned five-scenario brief-quality seed.
It covers straightforward, constrained, and infeasible selected ideas,
including a speculative quantum-materials project. Its separate expectations
require goal alignment, feasibility, specificity, testability, and evidence
discipline, and record claims that must not appear. Keep these inputs separate
from measured results so future prompt or model comparisons use the same
scenarios and rubric.
