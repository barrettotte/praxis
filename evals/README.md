# Evaluations

Evaluation prompts, expected evidence, expected tool trajectories, and measured
results belong here.

`phase1/prompts.json` is the versioned initial evaluation input. Case IDs are
stable references for expectations and baseline results; do not renumber them
when prompts are retired or the suite expands. This file intentionally contains
only prompts and coverage metadata. Expected evidence and trajectories are
recorded in `phase1/expectations.json` so evaluation inputs do not accidentally
disclose answers to the agent. Evidence sets use an `any_of` policy to permit
multiple relevant records without coupling the suite to a single ranking.

Baseline result files must identify the model, region, code revision, dataset,
run time, and content hashes. Quality is the mean of five deterministic checks:
valid structured output, grounded citations, curated evidence coverage, expected
local-tool trajectory, and concrete first milestones. A milestone is considered
concrete when it contains at least six words and an action verb from the runner's
documented vocabulary. Never replace historical measurements in place.

Run the suite with `make eval-baseline`. Each case uses a fresh agent invocation;
failures are recorded and do not stop the remaining cases.
