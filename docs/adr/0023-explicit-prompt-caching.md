# ADR 0023: Explicit prompt caching

## Status

Accepted

## Context

Every recommendation invocation sends the same Gateway tool schemas and system
instructions before its variable goal, retrieved evidence, memory context, and
model output. Amazon Nova Lite supports explicit prompt caching for prefixes of
at least 1,000 tokens in `system` or `messages`, with a five-minute lifetime.
The recommendation prefix exceeds that threshold because it includes the four
strict Gateway tool contracts as well as the maintained system instructions.

The project-brief prompt and local no-tool planner do not yet have a repeated
prefix known to exceed the model threshold. Adding cache points there would
increase configuration without demonstrated reuse.

## Decision

Place one explicit Bedrock cache point after the recommendation agent's stable
system instructions. Bedrock evaluates tool schemas before system content, so
the checkpoint covers both stable inputs while leaving request-specific data
outside the cached prefix. Do not cache user goals, retrieved catalog evidence,
Memory records, generated recommendations, or project briefs.

Verify the behavior through two traced calls to the stable AgentCore Runtime.
The first call warms the cache and the second must report a positive
`gen_ai.usage.cache_read_input_tokens` value. Keep the check opt-in because it
performs two metered model invocations and depends on trace delivery.

## Consequences

- Repeated recommendation calls within the cache lifetime can reuse the large,
  stable instruction and tool-schema prefix.
- Editing the system instructions or tool contracts naturally produces a new
  prefix and cache entry.
- Cache use is an optimization only; correctness and evidence validation do not
  depend on a hit.
- Runtime version 40 verified the checkpoint with 2,403 cache-read input tokens
  and zero cache-write input tokens on the required second invocation.
- Other model paths gain caching only after their stable prefix and reuse are
  measured against the selected model's requirements.

## References

- [Amazon Bedrock prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
- [Amazon Nova Lite model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html)
