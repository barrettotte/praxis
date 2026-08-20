# ADR 0002: DynamoDB catalog access patterns

- Status: Accepted
- Date: 2026-08-19

## Context

Praxis must retrieve roughly 1,000 personal catalog records by stable evidence
ID and search them with exact kind, category, language, and date filters. Text
search must remain deterministic and bounded. The source JSON repository is
authoritative, so the deployed catalog is disposable and reproducible. The MVP
cost target and workload do not justify OpenSearch, provisioned capacity, or a
large denormalized inverted index.

## Decision

Use one on-demand DynamoDB table with one catalog item per stable evidence ID.
The table has a string partition key named `record_id` and one global secondary
index named `kind-date-index`:

| Attribute        | Purpose                                                           |
| ---------------- | ----------------------------------------------------------------- |
| `record_id`      | Stable ID such as `book:1d48534f817374c6`; table partition key    |
| `kind`           | `book`, `project`, `byte`, or `museum`; GSI partition key         |
| `kind_date_key`  | Normalized date followed by `record_id`; GSI sort key             |
| `label`          | Human-readable title or name                                      |
| `category`       | Optional normalized category for exact filtering                  |
| `languages`      | Normalized language list; a book language becomes a one-item list |
| `search_text`    | Case-folded searchable fields joined into one bounded string      |
| `source`         | Source file, source ordinal, and content digest provenance        |
| `payload`        | Validated type-specific fields needed by catalog responses        |
| `schema_version` | Integer controlling future item migrations                        |

`kind_date_key` uses `<date>#<record_id>`, with `0000` for unknown dates. Dates
retain each kind's source precision (`YYYY`, `YYYY-MM`, or `YYYY-MM-DD`), which
is consistent within a kind and sorts lexically. Appending the stable ID makes
ordering and pagination deterministic. The GSI projects all attributes because
the catalog is small and this avoids a second read for every result.

### Access patterns

| Operation                      | DynamoDB operation                                                              | Bound                                                          |
| ------------------------------ | ------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Get an evidence record         | `GetItem` by `record_id`                                                        | One item                                                       |
| List one kind                  | Query `kind-date-index` by `kind`                                               | Paginated and result-limited                                   |
| Filter by date                 | GSI query with a `kind_date_key` range                                          | One query per requested kind                                   |
| Filter by category or language | GSI query plus exact `FilterExpression` on normalized attributes                | At most four kind partitions                                   |
| Search catalog text            | GSI query per requested kind with token `contains` filters; rank in the Lambda  | At most 8 tokens, 1,500 evaluated items, and 20 returned items |
| Compare project history        | Query the `project` GSI partition, then apply the existing deterministic scorer | 1,500 evaluated and 10 returned items                          |

Requests without a kind query the four known kind partitions independently and
merge their results. The catalog Lambda must stop once the total evaluated-item
budget is reached, even if DynamoDB returns a continuation key. It normalizes
filters with the same shared functions used during ingestion, ranks lexical
matches in application code, and uses `record_id` as the final tie-breaker.
Filter expressions reduce returned data but not read consumption; that tradeoff
is acceptable for the measured catalog size and must remain visible in metrics.

The table uses on-demand billing, AWS-owned encryption, point-in-time recovery
disabled, and deletion protection disabled. Those choices match a temporary
development copy that can be reconstructed from validated source data.

## Consequences

- Stable IDs provide constant-time evidence lookup and remain identical between
  local and deployed implementations.
- Exact filters and text search have explicit request, evaluation, and response
  bounds without another search service.
- The all-attributes GSI duplicates a small amount of storage and filter-based
  queries may read nonmatching items, trading minor MVP cost for simpler,
  idempotent ingestion.
- Search is lexical rather than semantic. The later Knowledge Base remains a
  separate retrieval tool so structured facts and semantic evidence are not
  conflated.
- Add a facet/token index or dedicated search service only if measurements show
  the catalog exceeds 1,500 evaluated items, latency becomes unacceptable, or
  read consumption materially threatens the cost target. Such a change requires
  a superseding ADR and evaluation comparison.
