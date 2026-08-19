"""Deterministic local catalog search."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from praxis.catalog.memory import CatalogEntry, CatalogItem, CatalogKind, InMemoryCatalog
from praxis.catalog.text import normalize_text, tokenize
from praxis.domain import Book, Byte, MuseumObject, Project

MAX_SEARCH_RESULTS = 20


class SearchCatalogRequest(BaseModel):
    """Validated inputs for a bounded local catalog search."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)

    query: Annotated[str, Field(min_length=1, max_length=500)]
    kinds: frozenset[CatalogKind] | None = None
    limit: Annotated[int, Field(ge=1, le=MAX_SEARCH_RESULTS)] = 10


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    """A ranked catalog match with evidence identity and score."""

    entry: CatalogEntry
    score: int


def _searchable_fields(item: CatalogItem) -> tuple[tuple[str, int], ...]:
    match item:
        case Book():
            return (
                (item.title, 8),
                (item.author or "", 4),
                (item.category or "", 4),
                (" ".join(item.tags), 3),
            )
        case Project():
            return (
                (item.name, 8),
                (item.description, 2),
                (" ".join(item.languages), 5),
            )
        case Byte():
            return (
                (item.name, 8),
                (item.category, 5),
                (item.model.description if item.model else "", 2),
            )
        case MuseumObject():
            return (
                (item.name, 8),
                (item.manufacturer, 5),
                (item.category, 4),
                (item.description, 2),
            )


def _score(entry: CatalogEntry, query: str, tokens: frozenset[str]) -> int:
    fields = tuple(
        (normalize_text(value), weight) for value, weight in _searchable_fields(entry.item)
    )
    token_score = sum(weight for token in tokens for value, weight in fields if token in value)
    phrase_bonus = 10 if any(query in value for value, _ in fields) else 0
    return token_score + phrase_bonus


def search_catalog(
    catalog: InMemoryCatalog, request: SearchCatalogRequest
) -> tuple[CatalogSearchResult, ...]:
    """Search catalog text locally and return deterministic ranked matches."""
    query = normalize_text(request.query)
    tokens = tokenize(query)
    allowed_kinds = frozenset(CatalogKind) if request.kinds is None else request.kinds
    matches = (
        CatalogSearchResult(entry=entry, score=score)
        for entry in catalog.entries()
        if entry.kind in allowed_kinds
        if (score := _score(entry, query, tokens)) > 0
    )
    ranked = sorted(matches, key=lambda result: (-result.score, result.entry.kind, result.entry.id))
    return tuple(ranked[: request.limit])
