# Development fixtures

These records are entirely synthetic. They mirror representative fields and
optional values from the four authoritative datasets without including personal
content or live external links.

- Each JSON file contains two records so tests remain fast and understandable.
- `https://example.invalid/` is used for deliberately non-resolving URLs.
- ISBN and LCCN values are placeholders, not real identifiers.
- Local image paths point to hypothetical fixture assets and are not expected to
  resolve.

When a source schema changes, update the corresponding fixture and its structural
test together. Never modify the authoritative files in the sibling repository.
