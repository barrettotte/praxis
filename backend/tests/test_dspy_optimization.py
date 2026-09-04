"""Tests for the bounded DSPy instruction comparison."""

from pathlib import Path

from praxis.domain import EvidenceCitation, ProjectCandidate, ProjectCandidateSet
from praxis.evaluation.dspy_optimization import (
    OptimizationExample,
    SignatureLike,
    evaluate_program,
    held_out_winner,
    partition_examples,
    score_candidates,
)
from praxis.evaluation.models import EvaluationSet, InstructionOptimizationSplit
from praxis.evaluation.results import InstructionProgramResult

REPOSITORY = Path(__file__).parents[2]
PROMPTS_PATH = REPOSITORY / "evals" / "project-recommendations" / "prompts.json"
SPLIT_PATH = REPOSITORY / "evals" / "project-recommendations" / "dspy-split.json"


def candidate_set(evidence_id: str) -> ProjectCandidateSet:
    """Build three valid candidates citing one selected record."""
    return ProjectCandidateSet(
        candidates=[
            ProjectCandidate(
                title=f"Candidate {number}",
                summary="Build a focused project.",
                rationale="The evidence supports this direction.",
                estimated_scope="weekend",
                technologies=["Python"],
                first_milestone="Build and test one independently verifiable command.",
                evidence_citations=[
                    EvidenceCitation(
                        evidence_id=evidence_id,
                        generated_connection="This record supports the project direction.",
                    )
                ],
            )
            for number in range(1, 4)
        ]
    )


def optimization_example(case_id: str = "project-01-retro-python") -> OptimizationExample:
    """Build one typed optimizer example with hidden scoring labels."""
    return OptimizationExample(
        case_id=case_id,
        goal_and_evidence="goal and evidence",
        retrieved_evidence_ids=("book:1111111111111111",),
        expected_records=(("book:1111111111111111", "book"),),
        minimum_matches=1,
        required_kinds=("book",),
    )


def test_instruction_split_is_disjoint_complete_and_held_out() -> None:
    evaluation_set = EvaluationSet.model_validate_json(PROMPTS_PATH.read_bytes())
    split = InstructionOptimizationSplit.model_validate_json(SPLIT_PATH.read_bytes())
    all_ids = (
        split.optimizer_training_case_ids
        + split.optimizer_validation_case_ids
        + split.held_out_case_ids
    )
    categories_by_id = {case.id: case.category for case in evaluation_set.cases}

    assert set(all_ids) == set(categories_by_id)
    assert len(all_ids) == len(set(all_ids)) == 30
    assert {categories_by_id[case_id] for case_id in split.held_out_case_ids} == {
        "straightforward",
        "ambiguous",
        "constrained",
        "infeasible",
    }


def test_score_candidates_requires_grounding_expected_evidence_and_milestones() -> None:
    example = optimization_example()

    result = score_candidates(example, candidate_set("book:1111111111111111"))

    assert result.succeeded is True
    assert result.score == 1.0
    assert result.citations_grounded is True
    assert result.expected_evidence_met is True
    assert result.concrete_first_milestones is True


def test_partition_examples_preserves_checked_in_order() -> None:
    split = InstructionOptimizationSplit.model_validate_json(SPLIT_PATH.read_bytes())
    all_ids = (
        split.optimizer_training_case_ids
        + split.optimizer_validation_case_ids
        + split.held_out_case_ids
    )
    examples = {case_id: optimization_example(case_id) for case_id in all_ids}

    training, validation, held_out = partition_examples(examples, split)

    assert [example.case_id for example in training] == split.optimizer_training_case_ids
    assert [example.case_id for example in validation] == split.optimizer_validation_case_ids
    assert [example.case_id for example in held_out] == split.held_out_case_ids


def test_evaluate_program_preserves_schema_failures() -> None:
    class FakeSignature:
        instructions = "test"

    class FakeProgram:
        signature: SignatureLike

        def __init__(self) -> None:
            self.signature = FakeSignature()

        def __call__(self, *, goal_and_evidence: str) -> object:
            if goal_and_evidence == "fail":
                return {"candidates": None}
            return {"candidates": candidate_set("book:1111111111111111").candidates}

    valid = optimization_example()
    invalid = OptimizationExample(
        case_id="project-02-typescript-visualization",
        goal_and_evidence="fail",
        retrieved_evidence_ids=valid.retrieved_evidence_ids,
        expected_records=valid.expected_records,
        minimum_matches=valid.minimum_matches,
        required_kinds=valid.required_kinds,
    )

    result = evaluate_program(FakeProgram(), [valid, invalid])

    assert result.case_count == 2
    assert result.success_count == 1
    assert result.average_score == 0.5
    assert result.cases[1].error_type == "ValidationError"


def test_held_out_winner_requires_quality_without_reliability_loss() -> None:
    def measurement(score: float, successes: int) -> InstructionProgramResult:
        successful = score_candidates(
            optimization_example(), candidate_set("book:1111111111111111")
        )
        failed = successful.model_copy(
            update={
                "succeeded": False,
                "structured_output_valid": False,
                "citations_grounded": False,
                "expected_evidence_met": False,
                "concrete_first_milestones": False,
                "score": 0.0,
                "error_type": "TestError",
            }
        )
        return InstructionProgramResult(
            case_count=10,
            success_count=successes,
            average_score=score,
            cases=[successful] * successes + [failed] * (10 - successes),
        )

    assert held_out_winner(measurement(0.7, 10), measurement(0.8, 10)) == "optimized"
    assert held_out_winner(measurement(0.7, 10), measurement(0.8, 9)) == "tie"
    assert held_out_winner(measurement(0.8, 10), measurement(0.7, 10)) == "maintained"
