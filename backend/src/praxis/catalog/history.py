"""Deterministic comparison with historical project records."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from praxis.catalog.memory import CatalogKind, InMemoryCatalog
from praxis.catalog.text import normalize_text, tokenize
from praxis.domain import Project

MAX_HISTORY_RESULTS = 10


class CompareProjectHistoryRequest(BaseModel):
    """Validated candidate details for historical comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)

    description: Annotated[str, Field(min_length=1, max_length=2_000)]
    languages: frozenset[Annotated[str, Field(min_length=1)]] = frozenset()
    limit: Annotated[int, Field(ge=1, le=MAX_HISTORY_RESULTS)] = 5


@dataclass(frozen=True, slots=True)
class ProjectHistoryMatch:
    """A prior project with factual lexical and technology overlap."""

    evidence_id: str
    project: Project
    matched_terms: tuple[str, ...]
    shared_languages: tuple[str, ...]
    score: int


def compare_project_history(
    catalog: InMemoryCatalog, request: CompareProjectHistoryRequest
) -> tuple[ProjectHistoryMatch, ...]:
    """Rank prior projects by shared terms and programming languages."""
    candidate_terms = tokenize(request.description)
    candidate_languages = frozenset(normalize_text(language) for language in request.languages)
    matches: list[ProjectHistoryMatch] = []

    for entry in catalog.entries():
        if entry.kind is not CatalogKind.PROJECT:
            continue
        project = entry.item
        if not isinstance(project, Project):
            continue
        project_terms = tokenize(f"{project.name} {project.description}")
        project_languages = frozenset(normalize_text(language) for language in project.languages)
        matched_terms = tuple(sorted(candidate_terms & project_terms))
        shared_languages = tuple(sorted(candidate_languages & project_languages))
        if not matched_terms and not shared_languages:
            continue
        matches.append(
            ProjectHistoryMatch(
                evidence_id=entry.id,
                project=project,
                matched_terms=matched_terms,
                shared_languages=shared_languages,
                score=len(matched_terms) + (len(shared_languages) * 5),
            )
        )

    matches.sort(key=lambda match: (-match.score, match.project.name.casefold(), match.evidence_id))
    return tuple(matches[: request.limit])
