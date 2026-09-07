"""Structured project-brief output models."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

EXTERNAL_REVIEW_TERMS = ("expert", "peer review", "specialist review")
SUBJECTIVE_COMPLETION_TERMS = (
    "completed the project",
    "solid understanding",
    "understand the",
)


class BriefModel(BaseModel):
    """Apply strict validation to generated project-brief output."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class ProjectMilestone(BriefModel):
    """A concrete delivery step with an artifact and completion check."""

    title: Annotated[str, Field(min_length=1, max_length=100)]
    deliverable: Annotated[str, Field(min_length=10, max_length=400)]
    verification: Annotated[str, Field(min_length=10, max_length=400)]

    @field_validator("verification")
    @classmethod
    def require_self_service_verification(cls, value: str) -> str:
        """Keep milestone checks reproducible without unavailable reviewers."""
        normalized = value.casefold()
        if any(term in normalized for term in EXTERNAL_REVIEW_TERMS):
            raise ValueError("verification must be executable without an external expert")
        return value


class ProjectRisk(BriefModel):
    """A delivery risk paired with a practical mitigation."""

    risk: Annotated[str, Field(min_length=1, max_length=300)]
    mitigation: Annotated[str, Field(min_length=1, max_length=300)]


class ProjectAcceptanceCriterion(BriefModel):
    """A measurable success condition and the method used to verify it."""

    criterion: Annotated[str, Field(min_length=10, max_length=300)]
    verification: Annotated[str, Field(min_length=10, max_length=300)]

    @field_validator("criterion")
    @classmethod
    def require_observable_outcome(cls, value: str) -> str:
        """Reject subjective completion statements that cannot be tested."""
        normalized = value.casefold()
        if any(term in normalized for term in SUBJECTIVE_COMPLETION_TERMS):
            raise ValueError("criterion must describe an observable artifact or result")
        return value

    @field_validator("verification")
    @classmethod
    def require_self_service_verification(cls, value: str) -> str:
        """Keep acceptance checks reproducible without unavailable reviewers."""
        normalized = value.casefold()
        if any(term in normalized for term in EXTERNAL_REVIEW_TERMS):
            raise ValueError("verification must be executable without an external expert")
        return value


class ProjectBrief(BriefModel):
    """A generated implementation plan for one selected candidate."""

    objective: Annotated[str, Field(min_length=1, max_length=500)]
    scope: Annotated[str, Field(min_length=1, max_length=600)]
    technical_approach: Annotated[
        list[Annotated[str, Field(min_length=20, max_length=400)]],
        Field(max_length=6),
    ] = Field(default_factory=list)
    assumptions: Annotated[
        list[Annotated[str, Field(min_length=10, max_length=300)]],
        Field(max_length=5),
    ] = Field(default_factory=list)
    out_of_scope: Annotated[
        list[Annotated[str, Field(min_length=10, max_length=300)]],
        Field(max_length=5),
    ] = Field(default_factory=list)
    deliverables: Annotated[
        list[Annotated[str, Field(min_length=10, max_length=300)]],
        Field(min_length=1, max_length=6),
    ]
    milestones: Annotated[list[ProjectMilestone], Field(min_length=1, max_length=5)]
    risks: Annotated[list[ProjectRisk], Field(max_length=4)] = Field(
        default_factory=list[ProjectRisk]
    )
    acceptance_criteria: Annotated[
        list[ProjectAcceptanceCriterion],
        Field(min_length=1, max_length=6),
    ]

    @field_validator("objective")
    @classmethod
    def require_delivery_objective(cls, value: str) -> str:
        """Allow learning goals only when they commit to a tangible result."""
        normalized = value.casefold()
        learning_only = normalized.startswith(
            ("learn ", "to learn ", "understand ", "to understand ")
        )
        artifact_terms = (
            "build ",
            "create ",
            "dataset",
            "demonstrator",
            "implement ",
            "model ",
            "program",
            "produc",
            "report",
            "simulat",
        )
        if learning_only and not any(term in normalized for term in artifact_terms):
            raise ValueError("objective must name an artifact or observable result")
        return value
