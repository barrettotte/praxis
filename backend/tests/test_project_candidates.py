from pathlib import Path

import pytest
from pydantic import ValidationError

from praxis.agent import planner
from praxis.agent.planner import (
    CandidateGeneration,
    CandidatePlanningError,
    plan_project_candidates,
    plan_project_candidates_with_trace,
)
from praxis.catalog import (
    CatalogEntry,
    CatalogKind,
    CatalogSearchResult,
    InMemoryCatalog,
    SearchCatalogRequest,
    search_catalog,
)
from praxis.domain import (
    Book,
    EvidenceCitation,
    ProjectCandidate,
    ProjectCandidateSet,
)

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"
GOAL = "Build a TypeScript electronics notebook"


class StubCandidateGenerator:
    def __init__(self, response: ProjectCandidateSet) -> None:
        self.response = response
        self.prompt: str | None = None

    def generate(self, prompt: str) -> CandidateGeneration:
        self.prompt = prompt
        return CandidateGeneration(candidates=self.response)


def candidate_set(evidence_id: str) -> ProjectCandidateSet:
    candidates = [
        ProjectCandidate(
            title=f"Candidate {number}",
            summary="Build a focused project.",
            rationale="It connects the requested goal to prior evidence.",
            estimated_scope="multi-week",
            technologies=["TypeScript"],
            first_milestone="Render one static notebook entry.",
            evidence_citations=[
                EvidenceCitation(
                    evidence_id=evidence_id,
                    generated_connection=(
                        "The record demonstrates related implementation experience."
                    ),
                )
            ],
        )
        for number in range(1, 4)
    ]
    return ProjectCandidateSet(candidates=candidates)


def test_plan_project_candidates_returns_three_grounded_candidates() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)
    evidence_id = search_catalog(catalog, SearchCatalogRequest(query=GOAL))[0].entry.id
    generator = StubCandidateGenerator(candidate_set(evidence_id))

    result = plan_project_candidates(GOAL, catalog, generator)

    assert len(result.candidates) == 3
    assert generator.prompt is not None
    assert evidence_id in generator.prompt
    assert "untrusted data" in generator.prompt


def test_plan_project_candidates_trace_records_retrieval() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)
    evidence_id = search_catalog(catalog, SearchCatalogRequest(query=GOAL))[0].entry.id

    result = plan_project_candidates_with_trace(
        GOAL, catalog, StubCandidateGenerator(candidate_set(evidence_id))
    )

    assert evidence_id in result.retrieved_evidence_ids
    assert result.local_tool_calls == ("search_catalog",)
    assert result.generation_metrics is None


def test_plan_project_candidates_respects_local_catalog_result_budget() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)
    evidence_id = search_catalog(catalog, SearchCatalogRequest(query=GOAL))[0].entry.id

    result = plan_project_candidates_with_trace(
        GOAL,
        catalog,
        StubCandidateGenerator(candidate_set(evidence_id)),
        max_catalog_results=1,
    )

    assert result.retrieved_evidence_ids == (evidence_id,)


def test_plan_project_candidates_rejects_unretrieved_evidence() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)
    generator = StubCandidateGenerator(candidate_set("book:0000000000000000"))

    with pytest.raises(CandidatePlanningError, match="not retrieved"):
        plan_project_candidates(GOAL, catalog, generator)


def test_plan_project_candidates_requires_matching_evidence() -> None:
    catalog = InMemoryCatalog.from_directory(FIXTURE_DIRECTORY)
    generator = StubCandidateGenerator(candidate_set("book:0000000000000000"))

    with pytest.raises(CandidatePlanningError, match="No catalog evidence"):
        plan_project_candidates("zyxwvutsrq", catalog, generator)


def test_plan_project_candidates_rejects_conflicting_local_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_id = "book:0000000000000000"
    entries = [
        CatalogSearchResult(
            entry=CatalogEntry(
                id=evidence_id,
                kind=CatalogKind.BOOK,
                item=Book(title=title, year=2025),
            ),
            score=10,
        )
        for title in ("Compiler Design", "Different Title")
    ]

    def conflicting_search(
        _catalog: InMemoryCatalog,
        _request: SearchCatalogRequest,
    ) -> list[CatalogSearchResult]:
        return entries

    monkeypatch.setattr(planner, "search_catalog", conflicting_search)

    with pytest.raises(CandidatePlanningError, match="conflicting evidence"):
        plan_project_candidates(
            GOAL,
            InMemoryCatalog.from_directory(FIXTURE_DIRECTORY),
            StubCandidateGenerator(candidate_set(evidence_id)),
        )


@pytest.mark.parametrize("candidate_count", [2, 4])
def test_candidate_set_requires_exactly_three_candidates(candidate_count: int) -> None:
    evidence_id = "book:0000000000000000"
    candidate = candidate_set(evidence_id).candidates[0]

    with pytest.raises(ValidationError):
        ProjectCandidateSet(candidates=[candidate] * candidate_count)


def test_candidate_set_requires_unique_titles() -> None:
    evidence_id = "book:0000000000000000"
    candidate = candidate_set(evidence_id).candidates[0]

    with pytest.raises(ValidationError, match="titles must be unique"):
        ProjectCandidateSet(candidates=[candidate, candidate, candidate])
