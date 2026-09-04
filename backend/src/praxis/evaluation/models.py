"""Validated contracts for repeatable evaluation inputs."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type EvaluationCategory = Literal["straightforward", "ambiguous", "constrained", "infeasible"]
type EvidenceKind = Literal["book", "byte", "museum", "project"]
type LocalToolName = Literal["search_catalog", "get_catalog_item", "compare_project_history"]
type BriefQualityDimension = Literal[
    "evidence-discipline",
    "feasibility",
    "goal-alignment",
    "specificity",
    "testability",
]
type BusinessAssertionDimension = Literal[
    "constraint-adherence",
    "differentiation",
    "feasibility",
    "goal-alignment",
    "safety",
]


class EvaluationModel(BaseModel):
    """Apply strict validation to versioned evaluation artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)


class EvaluationCase(EvaluationModel):
    """One stable prompt and its coverage metadata."""

    id: Annotated[str, Field(pattern=r"^project-[0-9]{2}-[a-z0-9-]+$")]
    prompt: Annotated[str, Field(min_length=1, max_length=1_000)]
    category: EvaluationCategory
    tags: Annotated[
        list[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$")]], Field(min_length=1)
    ]

    @model_validator(mode="after")
    def require_unique_tags(self) -> Self:
        """Keep case metadata deterministic and unambiguous."""
        if len(self.tags) != len(set(self.tags)):
            message = f"evaluation case {self.id} contains duplicate tags"
            raise ValueError(message)
        return self


class EvaluationSet(EvaluationModel):
    """A versioned project-recommendation evaluation suite."""

    suite: Literal["project-recommendation-baseline"]
    version: Literal[1, 2]
    cases: Annotated[list[EvaluationCase], Field(min_length=10, max_length=30)]

    @model_validator(mode="after")
    def require_unique_cases(self) -> Self:
        """Reject duplicate case IDs or prompts."""
        ids = [case.id for case in self.cases]
        prompts = [case.prompt.casefold() for case in self.cases]
        if len(ids) != len(set(ids)):
            message = "evaluation case IDs must be unique"
            raise ValueError(message)
        if len(prompts) != len(set(prompts)):
            message = "evaluation prompts must be unique"
            raise ValueError(message)
        expected_count = {1: 10, 2: 30}[self.version]
        if len(self.cases) != expected_count:
            message = f"evaluation set version {self.version} requires {expected_count} cases"
            raise ValueError(message)
        return self


class ExpectedEvidenceRecord(EvaluationModel):
    """A curated record that can legitimately support an evaluation response."""

    evidence_id: Annotated[
        str,
        Field(pattern=r"^(book|byte|museum|project):[0-9a-f]{16}$"),
    ]
    kind: EvidenceKind
    label: Annotated[str, Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def require_matching_kind(self) -> Self:
        """Keep evidence metadata consistent with its identifier."""
        if not self.evidence_id.startswith(f"{self.kind}:"):
            message = f"evidence ID {self.evidence_id} does not match kind {self.kind}"
            raise ValueError(message)
        return self


class EvidenceExpectation(EvaluationModel):
    """Acceptable evidence and minimum kind coverage for one case."""

    any_of: Annotated[list[ExpectedEvidenceRecord], Field(min_length=1)]
    minimum_matches: Annotated[int, Field(ge=1)] = 1
    required_kinds: list[EvidenceKind] = Field(default_factory=list[EvidenceKind])

    @model_validator(mode="after")
    def require_satisfiable_expectation(self) -> Self:
        """Reject duplicate or internally impossible evidence assertions."""
        ids = [record.evidence_id for record in self.any_of]
        available_kinds = {record.kind for record in self.any_of}
        if len(ids) != len(set(ids)):
            message = "expected evidence IDs must be unique within a case"
            raise ValueError(message)
        if self.minimum_matches > len(self.any_of):
            message = "minimum evidence matches exceed the curated evidence set"
            raise ValueError(message)
        if not set(self.required_kinds) <= available_kinds:
            message = "required evidence kinds are absent from the curated evidence set"
            raise ValueError(message)
        return self


class ExpectedToolCall(EvaluationModel):
    """Expected bounded use of one local catalog tool."""

    tool: LocalToolName
    minimum_calls: Annotated[int, Field(ge=0)]
    maximum_calls: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def require_valid_bounds(self) -> Self:
        """Reject inverted tool-call bounds."""
        if self.minimum_calls > self.maximum_calls:
            message = f"invalid call bounds for {self.tool}"
            raise ValueError(message)
        return self


class CaseExpectation(EvaluationModel):
    """Evidence and ordered local-tool expectations for one prompt."""

    case_id: Annotated[str, Field(pattern=r"^project-[0-9]{2}-[a-z0-9-]+$")]
    evidence: EvidenceExpectation
    trajectory: Annotated[list[ExpectedToolCall], Field(min_length=1)]

    @model_validator(mode="after")
    def require_valid_trajectory(self) -> Self:
        """Require search first and at most one expectation per tool."""
        tools = [call.tool for call in self.trajectory]
        if tools[0] != "search_catalog":
            message = f"evaluation case {self.case_id} must search first"
            raise ValueError(message)
        if len(tools) != len(set(tools)):
            message = f"evaluation case {self.case_id} repeats a tool expectation"
            raise ValueError(message)
        return self


class EvaluationExpectations(EvaluationModel):
    """Curated evidence and trajectories aligned with the project-recommendation prompts."""

    suite: Literal["project-recommendation-baseline"]
    prompts_version: Literal[1, 2]
    version: Literal[1, 2]
    expectations: Annotated[list[CaseExpectation], Field(min_length=10, max_length=30)]

    @model_validator(mode="after")
    def require_unique_case_ids(self) -> Self:
        """Require exactly one expectation per stable case ID."""
        case_ids = [expectation.case_id for expectation in self.expectations]
        if len(case_ids) != len(set(case_ids)):
            message = "expectation case IDs must be unique"
            raise ValueError(message)
        expected_count = {1: 10, 2: 30}[self.prompts_version]
        if len(self.expectations) != expected_count:
            message = (
                f"prompt version {self.prompts_version} requires {expected_count} expectations"
            )
            raise ValueError(message)
        return self


class BusinessAssertion(EvaluationModel):
    """One case-specific product behavior suitable for judged evaluation."""

    dimension: BusinessAssertionDimension
    requirement: Annotated[str, Field(min_length=1, max_length=500)]


class CaseBusinessAssertions(EvaluationModel):
    """Business requirements associated with one recommendation case."""

    case_id: Annotated[str, Field(pattern=r"^project-[0-9]{2}-[a-z0-9-]+$")]
    assertions: Annotated[list[BusinessAssertion], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def require_unique_dimensions(self) -> Self:
        """Keep each scored dimension unambiguous within a case."""
        dimensions = [assertion.dimension for assertion in self.assertions]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError(f"business assertion dimensions repeat for {self.case_id}")
        return self


class EvaluationBusinessAssertions(EvaluationModel):
    """Versioned business requirements aligned with recommendation prompts."""

    suite: Literal["project-recommendation-baseline"]
    prompts_version: Literal[2]
    version: Literal[1]
    cases: Annotated[list[CaseBusinessAssertions], Field(min_length=30, max_length=30)]

    @model_validator(mode="after")
    def require_unique_case_ids(self) -> Self:
        """Require exactly one assertion set per recommendation case."""
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("business assertion case IDs must be unique")
        return self


class BriefEvaluationCase(EvaluationModel):
    """One selected-idea scenario used to assess project-brief quality."""

    id: Annotated[str, Field(pattern=r"^brief-[0-9]{2}-[a-z0-9-]+$")]
    goal: Annotated[str, Field(min_length=1, max_length=1_000)]
    selected_idea: Annotated[str, Field(min_length=1, max_length=200)]
    category: EvaluationCategory
    tags: Annotated[
        list[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$")]],
        Field(min_length=1),
    ]


class BriefEvaluationSet(EvaluationModel):
    """Versioned scenarios for feasibility and implementation-detail evaluation."""

    suite: Literal["project-brief-quality"]
    version: Literal[1]
    cases: Annotated[list[BriefEvaluationCase], Field(min_length=5, max_length=5)]

    @model_validator(mode="after")
    def require_unique_cases(self) -> Self:
        """Reject duplicate case IDs or selected goal-and-idea pairs."""
        ids = [case.id for case in self.cases]
        scenarios = [(case.goal.casefold(), case.selected_idea.casefold()) for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("brief evaluation case IDs must be unique")
        if len(scenarios) != len(set(scenarios)):
            raise ValueError("brief evaluation scenarios must be unique")
        return self


class BriefCaseExpectation(EvaluationModel):
    """Required quality dimensions and unsafe claims for one brief case."""

    case_id: Annotated[str, Field(pattern=r"^brief-[0-9]{2}-[a-z0-9-]+$")]
    dimensions: Annotated[list[BriefQualityDimension], Field(min_length=5, max_length=5)]
    minimum_dimension_score: Literal[4, 5]
    requires_feasibility_reframe: bool
    forbidden_claims: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list[str]
    )

    @model_validator(mode="after")
    def require_complete_rubric(self) -> Self:
        """Require every quality dimension exactly once."""
        if len(self.dimensions) != len(set(self.dimensions)):
            raise ValueError("brief quality dimensions must be unique")
        return self


class BriefEvaluationExpectations(EvaluationModel):
    """Curated quality requirements aligned with the project-brief cases."""

    suite: Literal["project-brief-quality"]
    cases_version: Literal[1]
    version: Literal[1]
    expectations: Annotated[list[BriefCaseExpectation], Field(min_length=5, max_length=5)]

    @model_validator(mode="after")
    def require_unique_case_ids(self) -> Self:
        """Require exactly one expectation per stable brief case ID."""
        case_ids = [expectation.case_id for expectation in self.expectations]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("brief expectation case IDs must be unique")
        return self
