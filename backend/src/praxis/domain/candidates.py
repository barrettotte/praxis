"""Structured project-candidate output models."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type ShortText = Annotated[str, Field(min_length=1, max_length=500)]


class CandidateModel(BaseModel):
    """Apply strict validation to generated candidate output."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class EvidenceCitation(CandidateModel):
    """A retrieved evidence identifier with generated relevance analysis."""

    evidence_id: Annotated[
        str,
        Field(pattern=r"^(book|byte|museum|project):[0-9a-f]{16}$"),
    ]
    generated_connection: Annotated[str, Field(min_length=1, max_length=240)]


class ProjectCandidate(CandidateModel):
    """A generated, scoped project recommendation."""

    title: Annotated[str, Field(min_length=1, max_length=100)]
    summary: Annotated[str, Field(min_length=1, max_length=400)]
    rationale: ShortText
    estimated_scope: Literal["weekend", "multi-week", "multi-month"]
    technologies: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=40)]], Field(min_length=1, max_length=6)
    ]
    first_milestone: Annotated[str, Field(min_length=1, max_length=300)]
    evidence_citations: Annotated[list[EvidenceCitation], Field(min_length=1, max_length=4)]


class ProjectCandidateSet(CandidateModel):
    """Exactly three differentiated project recommendations."""

    candidates: Annotated[list[ProjectCandidate], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def require_unique_titles(self) -> Self:
        """Reject candidate sets that repeat the same project idea."""
        titles = [candidate.title.casefold() for candidate in self.candidates]
        if len(titles) != len(set(titles)):
            message = "candidate titles must be unique"
            raise ValueError(message)
        return self
