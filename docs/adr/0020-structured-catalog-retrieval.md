# ADR 0020: Keep structured catalog retrieval without a Knowledge Base

## Status

Accepted

## Context

Praxis has 1,034 source records, but record count alone does not make a useful
semantic corpus. The rendered text is approximately 185 KB: 753 records are
under 200 bytes and none reaches 500 bytes. Books have titles and bibliographic
metadata without summaries, project descriptions average approximately 43
characters, museum descriptions average approximately 81 characters, and only
8 of 66 technical-note records include a model description.

ISBN services can sometimes supply publisher descriptions, but coverage is not
guaranteed. Bulk enrichment would introduce remote availability, attribution,
licensing, synchronization, and provenance concerns. Generated summaries would
not be authoritative evidence.

## Decision

Use the DynamoDB catalog and its bounded lexical search as the only personal-data
retrieval system. Do not provision a Bedrock Knowledge Base or maintain a
semantic-document ingestion pipeline. Improve retrieval quality through bounded
query expansion, exact filters, and evaluation against stable evidence IDs.

External book descriptions and repository content are not authoritative inputs.
Reconsider semantic retrieval only when the owned source datasets contain enough
substantive text and evaluations demonstrate a material retrieval gap. That
change requires a superseding ADR with cost, licensing, and citation evidence.

## Consequences

- The deployed architecture remains smaller, cheaper, and fully reproducible
  from the four owned JSON datasets.
- Exact catalog provenance and stable evidence IDs remain the citation boundary.
- Semantic synonym matching is limited, so query expansion and retrieval
  evaluation carry more responsibility.
- Richer user-authored notes can improve future retrieval without depending on
  remote content providers.
