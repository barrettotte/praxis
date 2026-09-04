# ADR 0021: On-demand AgentCore evaluations

## Status

Accepted

## Context

The deterministic evaluation runner measures schema validity, evidence use,
tool trajectories, latency, and token consumption. Those checks cannot judge
whether an open-ended recommendation actually satisfies the user's goal or
whether the selected tools and generated claims are appropriate. Runtime
sessions already emit OpenTelemetry spans that AgentCore Evaluations accepts.

Continuous online evaluation would add an always-active configuration and
sample real application traffic. The development environment instead needs a
repeatable, explicitly metered comparison over reviewed fixtures.

## Decision

Run AgentCore Evaluations on demand as part of the deployed evaluation command.
For every successful isolated Runtime case:

- use `Builtin.GoalSuccessRate` at session level with the case's reviewed
  business assertions;
- use `Builtin.Correctness` at trace level for the generated responses; and
- use `Builtin.ToolSelectionAccuracy` at tool-call level for the observed
  Strands tool spans.

Read the complete session-correlated OTEL documents from the Runtime CloudWatch
span stream and submit them directly through the AgentCore data plane. Do not
create an online evaluation configuration or route application requests
through the evaluation runner.

Persist only evaluator identity, result and score counts, aggregate scores,
labels, error codes, and token totals. Do not persist evaluator explanations,
prompts, model responses, session IDs, trace IDs, or span IDs in evaluation
artifacts. Verify the required built-in evaluator IDs with a read-only control
plane request before starting metered work.

## Consequences

- The canonical 30-case deployed run makes 30 Runtime invocations and up to 90
  managed evaluation requests, so it remains a deliberate manual command.
- Reviewed business assertions become machine-consumable ground truth for goal
  success while deterministic local checks remain independently visible.
- AWS manages the built-in evaluator prompts and judge models; scores can
  change as the service evolves even when application inputs are fixed.
- Evaluation failures are recorded separately from agent-generation failures,
  preserving partial measurements without treating judge availability as
  product behavior.
- The production request path and its IAM roles need no evaluation permissions.

## References

- [AgentCore on-demand evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-demand-evaluations.html)
- [AgentCore ground-truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
- [AgentCore built-in evaluator prompts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/prompt-templates-builtin.html)
