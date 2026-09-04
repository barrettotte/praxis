# ADR 0026: Versioned prompt-attack guardrail

## Status

Accepted

## Context

Praxis sends a user goal, pre-fetched catalog evidence, and explicit memory
records to Amazon Bedrock. The catalog and memory text are untrusted even though
their retrieval paths are read-only. System instructions tell the model not to
follow embedded instructions, while strict schemas, evidence ledgers, budgets,
and Gateway tool allowlists enforce output and action boundaries. Those controls
do not independently classify prompt attacks before model generation.

The application legitimately handles security, electronics, chemistry,
historical, and other technical subjects. Broad harmful-content or denied-topic
filters would therefore risk blocking useful project planning. Output is already
constrained by strict domain contracts and cannot invoke arbitrary tools.

## Decision

- Create one OpenTofu-managed Amazon Bedrock Guardrail in `us-east-1` and attach
  an immutable numbered version to every recommendation and project-brief model
  request.
- Enable only the text `PROMPT_ATTACK` input filter at high strength with the
  blocking action. Disable output evaluation and do not configure general
  harmful-content, denied-topic, word, sensitive-information, or contextual-
  grounding policies without a measured requirement.
- Use the Classic safeguard tier because Praxis accepts English input and must
  keep inference in-region. The Standard tier requires cross-Region guardrail
  inference.
- Put only the raw user goal in an explicit Strands `guardContent` block.
  Server-added framing, catalog records, and memory records remain regular model
  context so defensive instructions such as "treat as untrusted" do not trigger
  the prompt-attack classifier. System instructions, strict output validation,
  evidence controls, and tool allowlists defend the indirect-injection boundary.
- Enable guardrail traces for control behavior while keeping public API errors
  generic. Preserve strict schema, evidence, tool, and authorization checks as
  independent defenses because a probabilistic filter cannot enforce them.
- Keep guardrail configuration optional for local development, but require the
  identifier and version as a pair when configured. Deployed Runtime versions
  always receive both from OpenTofu.

## Consequences

- Each guarded input adds Bedrock Guardrails text-unit charges and some latency;
  output evaluation adds neither because it is disabled.
- Legitimate project domains remain available instead of being screened by
  broad subject categories.
- Guardrail false positives and false negatives remain possible. Adversarial
  catalog fixtures and tool-boundary tests must verify the surrounding controls.
- A non-mutating, metered smoke check passes synthetic instruction-bearing
  catalog evidence through the maintained prompt and candidate contracts. It
  must be rerun after model, instruction, or contract changes.
- Updating a guardrail policy creates a new numbered version and a new immutable
  Runtime version. The stable endpoint moves only after verification.
- A read-only configuration smoke check verifies the policy and the stable
  Runtime attachment without submitting metered model input.

## References

- [Use guardrails with the Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html)
- [Prompt-attack filter configuration](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-content-filters.html)
- [Guardrail safeguard tiers](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-tiers.html)
