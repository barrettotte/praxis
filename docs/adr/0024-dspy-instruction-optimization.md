# ADR 0024: Offline DSPy instruction optimization

## Status

Accepted

## Context

The recommendation agent has a maintained system instruction that encodes tool,
evidence, safety, and structured-output constraints. Prompt edits can improve one
case while weakening reliability or grounding elsewhere, so an optimizer must not
select production instructions from training performance alone.

DSPy can optimize instructions against a programmatic metric. Replacing the
Strands production agent with DSPy would also change the execution framework and
tool behavior, obscuring whether an instruction caused an observed difference.

## Decision

Use DSPy MIPROv2 only as an offline development experiment. Optimize the
instruction with fixed 15-case training and five-case validation partitions, no
persisted demonstrations, three instruction candidates, and three optimization
trials. Compare the selected instruction with the maintained baseline on ten
untouched held-out cases using the same Nova Lite model, retrieved evidence,
structured candidate contract, and deterministic quality checks.

Never update the production instruction automatically. An optimized instruction
is eligible for review only when its held-out average score improves without
reducing successful structured outputs.

The qualifying comparison retained the maintained instruction. It produced valid
output for 10 of 10 held-out cases with an average score of 0.60. The optimized
instruction produced valid output for 9 of 10 cases with an average score of 0.50.
The immutable result is
[`dspy-instructions-20260904T155637Z.json`](../../evals/project-recommendations/results/dspy-instructions-20260904T155637Z.json).

## Consequences

- DSPy and its optimizer dependencies remain development-only and are excluded
  from the Runtime image.
- The maintained production instruction remains unchanged.
- Future instruction experiments reuse the checked-in split and preserve their
  own immutable artifacts rather than overwriting a baseline.
- Model comparisons can override `DSPY_MODEL_ID`, but they must be labeled and
  must not be interpreted as the default-model result.
- The application deployment topology and README architecture diagram do not
  change because optimization runs outside the serving path.

## References

- [DSPy MIPROv2](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/api/optimizers/MIPROv2.md)
- [DSPy paper](https://arxiv.org/abs/2310.03714)
