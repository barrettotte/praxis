from pathlib import Path

from pydantic import TypeAdapter

from praxis.evaluation import (
    BriefEvaluationExpectations,
    BriefEvaluationSet,
    EvaluationBusinessAssertions,
    EvaluationExpectations,
    EvaluationSet,
)

EVALUATION_SET_PATH = (
    Path(__file__).parents[2] / "evals" / "project-recommendations" / "prompts.json"
)
EXPECTATIONS_PATH = (
    Path(__file__).parents[2] / "evals" / "project-recommendations" / "expectations.json"
)
BUSINESS_ASSERTIONS_PATH = (
    Path(__file__).parents[2] / "evals" / "project-recommendations" / "business-assertions.json"
)
BRIEF_CASES_PATH = Path(__file__).parents[2] / "evals" / "project-briefs" / "cases.json"
BRIEF_EXPECTATIONS_PATH = (
    Path(__file__).parents[2] / "evals" / "project-briefs" / "expectations.json"
)


def test_project_recommendation_evaluation_set_is_valid_and_stable() -> None:
    evaluation_set = TypeAdapter(EvaluationSet).validate_json(EVALUATION_SET_PATH.read_bytes())

    assert evaluation_set.suite == "project-recommendation-baseline"
    assert evaluation_set.version == 2
    assert len(evaluation_set.cases) == 30
    assert [case.id[:10] for case in evaluation_set.cases] == [
        f"project-{number:02}" for number in range(1, 31)
    ]


def test_project_recommendation_evaluation_set_covers_request_difficulty() -> None:
    evaluation_set = TypeAdapter(EvaluationSet).validate_json(EVALUATION_SET_PATH.read_bytes())

    categories = {case.category for case in evaluation_set.cases}
    assert categories == {"straightforward", "ambiguous", "constrained", "infeasible"}
    assert all(
        sum(case.category == category for case in evaluation_set.cases) >= 5
        for category in categories
    )


def test_project_recommendation_evaluation_set_covers_core_domains() -> None:
    evaluation_set = TypeAdapter(EvaluationSet).validate_json(EVALUATION_SET_PATH.read_bytes())
    tags = {tag for case in evaluation_set.cases for tag in case.tags}

    assert {"3d-printing", "electronics", "museum", "retro-computing", "security"} <= tags
    assert {"cpp", "python", "rust", "typescript"} <= tags


def test_project_recommendation_expectations_align_with_every_prompt() -> None:
    evaluation_set = TypeAdapter(EvaluationSet).validate_json(EVALUATION_SET_PATH.read_bytes())
    expectations = TypeAdapter(EvaluationExpectations).validate_json(EXPECTATIONS_PATH.read_bytes())

    assert expectations.suite == evaluation_set.suite
    assert expectations.prompts_version == evaluation_set.version
    assert [expectation.case_id for expectation in expectations.expectations] == [
        case.id for case in evaluation_set.cases
    ]


def test_project_recommendation_expectations_preserve_evidence_metadata() -> None:
    expectations = TypeAdapter(EvaluationExpectations).validate_json(EXPECTATIONS_PATH.read_bytes())
    records = [
        record
        for expectation in expectations.expectations
        for record in expectation.evidence.any_of
    ]

    assert all(record.evidence_id.startswith(f"{record.kind}:") for record in records)
    assert len({record.evidence_id for record in records}) >= 20


def test_history_aware_cases_expect_project_comparison() -> None:
    expectations = TypeAdapter(EvaluationExpectations).validate_json(EXPECTATIONS_PATH.read_bytes())
    tools_by_case = {
        expectation.case_id: {call.tool for call in expectation.trajectory}
        for expectation in expectations.expectations
    }

    assert "compare_project_history" in tools_by_case["project-03-cpp-game-history"]
    assert "compare_project_history" in tools_by_case["project-07-security-python"]


def test_business_assertions_align_with_every_prompt() -> None:
    evaluation_set = TypeAdapter(EvaluationSet).validate_json(EVALUATION_SET_PATH.read_bytes())
    assertions = TypeAdapter(EvaluationBusinessAssertions).validate_json(
        BUSINESS_ASSERTIONS_PATH.read_bytes()
    )

    assert assertions.suite == evaluation_set.suite
    assert assertions.prompts_version == evaluation_set.version
    assert [case.case_id for case in assertions.cases] == [case.id for case in evaluation_set.cases]


def test_infeasible_cases_require_feasibility_or_safety_assertions() -> None:
    evaluation_set = TypeAdapter(EvaluationSet).validate_json(EVALUATION_SET_PATH.read_bytes())
    assertions = TypeAdapter(EvaluationBusinessAssertions).validate_json(
        BUSINESS_ASSERTIONS_PATH.read_bytes()
    )
    infeasible_ids = {case.id for case in evaluation_set.cases if case.category == "infeasible"}

    for case in assertions.cases:
        if case.case_id in infeasible_ids:
            dimensions = {assertion.dimension for assertion in case.assertions}
            assert dimensions & {"feasibility", "safety"}


def test_project_brief_evaluation_set_covers_feasible_and_infeasible_ideas() -> None:
    cases = TypeAdapter(BriefEvaluationSet).validate_json(BRIEF_CASES_PATH.read_bytes())

    assert len(cases.cases) == 5
    assert {case.category for case in cases.cases} >= {"straightforward", "infeasible"}
    assert [case.id[:8] for case in cases.cases] == [f"brief-{number:02}" for number in range(1, 6)]


def test_project_brief_expectations_align_and_require_complete_rubric() -> None:
    cases = TypeAdapter(BriefEvaluationSet).validate_json(BRIEF_CASES_PATH.read_bytes())
    expectations = TypeAdapter(BriefEvaluationExpectations).validate_json(
        BRIEF_EXPECTATIONS_PATH.read_bytes()
    )

    assert expectations.cases_version == cases.version
    assert [item.case_id for item in expectations.expectations] == [case.id for case in cases.cases]
    assert all(len(set(item.dimensions)) == 5 for item in expectations.expectations)
    assert sum(item.requires_feasibility_reframe for item in expectations.expectations) == 2
