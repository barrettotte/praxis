"""Deterministic local catalog search."""

from dataclasses import dataclass
from itertools import islice
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from praxis.catalog.memory import CatalogEntry, CatalogItem, CatalogKind, InMemoryCatalog
from praxis.catalog.text import MAX_SEARCH_TOKENS, normalize_text, tokenize
from praxis.domain import Book, Byte, MuseumObject, Project

MAX_SEARCH_RESULTS = 20
MAX_SEARCH_EVALUATED_ITEMS = 1_500
type CatalogDate = Annotated[
    str, Field(pattern=r"^\d{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?$")
]


class SearchCatalogRequest(BaseModel):
    """Validated inputs for a bounded local catalog search."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)

    query: Annotated[str, Field(min_length=1, max_length=500)]
    kinds: frozenset[CatalogKind] | None = None
    categories: frozenset[Annotated[str, Field(min_length=1)]] | None = None
    languages: frozenset[Annotated[str, Field(min_length=1)]] | None = None
    date_from: CatalogDate | None = None
    date_to: CatalogDate | None = None
    limit: Annotated[int, Field(ge=1, le=MAX_SEARCH_RESULTS)] = 10

    @field_validator("categories", "languages", mode="after")
    @classmethod
    def normalize_exact_filters(cls, values: frozenset[str] | None) -> frozenset[str] | None:
        """Normalize exact text filters once at the request boundary."""
        if values is None:
            return None
        return frozenset(normalize_text(value) for value in values)

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        """Reject an inclusive date range whose lower bound follows its upper bound."""
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        if len(tokenize(self.query)) > MAX_SEARCH_TOKENS:
            raise ValueError(f"query must contain at most {MAX_SEARCH_TOKENS} searchable tokens")
        return self


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


def catalog_search_text(item: CatalogItem) -> str:
    """Return the normalized fields eligible for deployed lexical search."""
    return normalize_text(" ".join(value for value, _weight in _searchable_fields(item)))


def _filter_fields(item: CatalogItem) -> tuple[str | None, frozenset[str], str | None]:
    match item:
        case Book():
            languages: frozenset[str] = (
                frozenset({normalize_text(item.language)}) if item.language else frozenset()
            )
            return item.category, languages, f"{item.year:04d}"
        case Project():
            languages = frozenset(normalize_text(language) for language in item.languages)
            return None, languages, item.date
        case Byte():
            return item.category, frozenset(), item.date.isoformat()
        case MuseumObject():
            catalog_date = f"{item.year:04d}" if item.year is not None else None
            return item.category, frozenset(), catalog_date


def _matches_exact_filters(item: CatalogItem, request: SearchCatalogRequest) -> bool:
    category, languages, catalog_date = _filter_fields(item)
    normalized_category = normalize_text(category) if category else None
    if request.categories is not None and normalized_category not in request.categories:
        return False
    if request.languages is not None and not (languages & request.languages):
        return False
    if request.date_from is not None and (catalog_date is None or catalog_date < request.date_from):
        return False
    return not (
        request.date_to is not None and (catalog_date is None or catalog_date > request.date_to)
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
        for entry in islice(catalog.entries(), MAX_SEARCH_EVALUATED_ITEMS)
        if entry.kind in allowed_kinds
        if _matches_exact_filters(entry.item, request)
        if (score := _score(entry, query, tokens)) > 0
    )
    ranked = sorted(matches, key=lambda result: (-result.score, result.entry.kind, result.entry.id))
    return tuple(ranked[: request.limit])
