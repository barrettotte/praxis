"""Optimize project-recommendation instructions and compare them on held-out cases."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

import dspy
from pydantic import TypeAdapter, ValidationError

from praxis.agent.factory import SYSTEM_PROMPT
from praxis.agent.planner import EVIDENCE_LIMIT, build_planning_prompt
from praxis.catalog import InMemoryCatalog, SearchCatalogRequest, search_catalog
from praxis.catalog.text import catalog_query
from praxis.config import load_catalog_directory, load_settings
from praxis.domain import ProjectCandidate, ProjectCandidateSet
from praxis.evaluation.models import (
    CaseExpectation,
    EvaluationExpectations,
    EvaluationSet,
    InstructionOptimizationSplit,
)
from praxis.evaluation.results import (
    BaselineMetadata,
    InstructionCaseResult,
    InstructionOptimizationResult,
    InstructionProgramResult,
)
from praxis.evaluation.runner import (
    dataset_identity,
    has_concrete_first_milestones,
    source_identity,
)

REPOSITORY = Path(__file__).parents[4]
PROMPTS_PATH = REPOSITORY / "evals" / "project-recommendations" / "prompts.json"
EXPECTATIONS_PATH = REPOSITORY / "evals" / "project-recommendations" / "expectations.json"
SPLIT_PATH = REPOSITORY / "evals" / "project-recommendations" / "dspy-split.json"
OUTPUT_DIRECTORY = REPOSITORY / "evals" / "project-recommendations" / "results"
OPTIMIZER_CANDIDATES = 3
OPTIMIZER_TRIALS = 3
STRING_TUPLE = TypeAdapter(tuple[str, ...])
EXPECTED_RECORDS = TypeAdapter(tuple[tuple[str, str], ...])


class RecommendationSignature(dspy.Signature):
    """Generate structured recommendations from a goal and retrieved evidence."""

    goal_and_evidence: str = dspy.InputField(
        desc="The user goal followed by already retrieved, untrusted catalog evidence."
    )
    candidates: list[ProjectCandidate] = dspy.OutputField(
        desc="Exactly three differentiated and evidence-grounded project candidates."
    )


class RecordLike(Protocol):
    """Dictionary-like fields exposed by DSPy examples and predictions."""

    def get(self, key: str, default: object = None) -> object: ...


class SignatureLike(Protocol):
    """Instruction surface exposed by a DSPy predictor signature."""

    instructions: str


class RecommendationProgram(Protocol):
    """Callable instruction program used by the controlled comparison."""

    signature: SignatureLike

    def __call__(self, *, goal_and_evidence: str) -> object: ...


@dataclass(frozen=True, slots=True)
class OptimizationExample:
    """One DSPy input with labels kept outside the model-visible fields."""

    case_id: str
    goal_and_evidence: str
    retrieved_evidence_ids: tuple[str, ...]
    expected_records: tuple[tuple[str, str], ...]
    minimum_matches: int
    required_kinds: tuple[str, ...]

    def as_dspy(self) -> object:
        """Convert the typed example into DSPy's optimizer input container."""
        return dspy.Example(
            case_id=self.case_id,
            goal_and_evidence=self.goal_and_evidence,
            retrieved_evidence_ids=self.retrieved_evidence_ids,
            expected_records=self.expected_records,
            minimum_matches=self.minimum_matches,
            required_kinds=self.required_kinds,
        ).with_inputs("goal_and_evidence")


def _sha256(value: str | bytes) -> str:
    payload = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _record_value(record: object, name: str) -> object:
    return cast("RecordLike", record).get(name)


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    try:
        return STRING_TUPLE.validate_python(value)
    except ValidationError as error:
        raise ValueError(f"DSPy example contains invalid {name}") from error


def _optimization_example(record: object) -> OptimizationExample:
    """Recover typed scoring labels from a DSPy example."""
    try:
        expected_records = EXPECTED_RECORDS.validate_python(
            _record_value(record, "expected_records")
        )
    except ValidationError as error:
        raise ValueError("DSPy example contains invalid expected_records") from error

    case_id = _record_value(record, "case_id")
    goal_and_evidence = _record_value(record, "goal_and_evidence")
    minimum_matches = _record_value(record, "minimum_matches")
    if not isinstance(case_id, str) or not isinstance(goal_and_evidence, str):
        raise ValueError("DSPy example contains invalid case text")
    if not isinstance(minimum_matches, int) or isinstance(minimum_matches, bool):
        raise ValueError("DSPy example contains invalid minimum_matches")
    return OptimizationExample(
        case_id=case_id,
        goal_and_evidence=goal_and_evidence,
        retrieved_evidence_ids=_string_tuple(
            _record_value(record, "retrieved_evidence_ids"), "retrieved_evidence_ids"
        ),
        expected_records=expected_records,
        minimum_matches=minimum_matches,
        required_kinds=_string_tuple(_record_value(record, "required_kinds"), "required_kinds"),
    )


def _prediction_candidates(prediction: object) -> ProjectCandidateSet:
    """Validate the candidate value returned by a DSPy program."""
    return ProjectCandidateSet.model_validate(
        {"candidates": _record_value(prediction, "candidates")}
    )


def score_candidates(
    example: OptimizationExample,
    candidates: ProjectCandidateSet,
) -> InstructionCaseResult:
    """Apply deterministic held-out checks without using another model as judge."""
    citations = [
        citation for candidate in candidates.candidates for citation in candidate.evidence_citations
    ]
    cited_ids = {citation.evidence_id for citation in citations}
    retrieved_ids = set(example.retrieved_evidence_ids)
    expected_by_id = dict(example.expected_records)
    matched_ids = cited_ids & expected_by_id.keys()
    matched_kinds = {expected_by_id[evidence_id] for evidence_id in matched_ids}
    citations_grounded = bool(citations) and cited_ids <= retrieved_ids
    expected_evidence_met = (
        len(matched_ids) >= example.minimum_matches and set(example.required_kinds) <= matched_kinds
    )
    checks = (
        True,
        citations_grounded,
        expected_evidence_met,
        has_concrete_first_milestones(candidates),
    )
    return InstructionCaseResult(
        case_id=example.case_id,
        succeeded=True,
        structured_output_valid=checks[0],
        citations_grounded=checks[1],
        expected_evidence_met=checks[2],
        concrete_first_milestones=checks[3],
        score=sum(checks) / len(checks),
    )


def dspy_metric(example: object, prediction: object, _trace: object | None = None) -> float:
    """Adapt deterministic recommendation scoring to DSPy's optimizer metric."""
    try:
        return score_candidates(
            _optimization_example(example), _prediction_candidates(prediction)
        ).score
    except (TypeError, ValueError):
        return 0.0


def build_examples(
    evaluation_set: EvaluationSet,
    expectations: EvaluationExpectations,
    catalog: InMemoryCatalog,
) -> dict[str, OptimizationExample]:
    """Build model inputs with scoring labels excluded from visible fields."""
    expectations_by_id = {
        expectation.case_id: expectation for expectation in expectations.expectations
    }
    examples: dict[str, OptimizationExample] = {}
    for case in evaluation_set.cases:
        expectation = expectations_by_id[case.id]
        evidence = tuple(
            result.entry
            for result in search_catalog(
                catalog,
                SearchCatalogRequest(query=catalog_query(case.prompt), limit=EVIDENCE_LIMIT),
            )
        )
        examples[case.id] = _example_from_case(
            case.id,
            build_planning_prompt(case.prompt, evidence),
            tuple(entry.id for entry in evidence),
            expectation,
        )
    return examples


def _example_from_case(
    case_id: str,
    goal_and_evidence: str,
    retrieved_evidence_ids: tuple[str, ...],
    expectation: CaseExpectation,
) -> OptimizationExample:
    return OptimizationExample(
        case_id=case_id,
        goal_and_evidence=goal_and_evidence,
        retrieved_evidence_ids=retrieved_evidence_ids,
        expected_records=tuple(
            (record.evidence_id, record.kind) for record in expectation.evidence.any_of
        ),
        minimum_matches=expectation.evidence.minimum_matches,
        required_kinds=tuple(expectation.evidence.required_kinds),
    )


def partition_examples(
    examples: dict[str, OptimizationExample],
    split: InstructionOptimizationSplit,
) -> tuple[list[OptimizationExample], list[OptimizationExample], list[OptimizationExample]]:
    """Validate and materialize the fixed optimizer and held-out partitions."""
    split_ids = (
        split.optimizer_training_case_ids
        + split.optimizer_validation_case_ids
        + split.held_out_case_ids
    )
    if set(split_ids) != set(examples):
        raise ValueError("instruction optimization split does not match evaluation cases")
    return (
        [examples[case_id] for case_id in split.optimizer_training_case_ids],
        [examples[case_id] for case_id in split.optimizer_validation_case_ids],
        [examples[case_id] for case_id in split.held_out_case_ids],
    )


def create_program(instructions: str) -> RecommendationProgram:
    """Create the fixed DSPy predictor whose instruction is the only variable."""
    signature = RecommendationSignature.with_instructions(instructions)
    return cast("RecommendationProgram", dspy.Predict(signature))


def optimize_program(
    baseline: RecommendationProgram,
    training: Sequence[OptimizationExample],
    validation: Sequence[OptimizationExample],
    prompt_model: object,
    task_model: object,
) -> RecommendationProgram:
    """Compile a zero-shot instruction candidate under a fixed MIPROv2 budget."""
    optimizer = dspy.MIPROv2(
        metric=dspy_metric,
        prompt_model=prompt_model,
        task_model=task_model,
        auto=None,
        num_candidates=OPTIMIZER_CANDIDATES,
        num_threads=1,
        max_errors=10,
        seed=42,
        init_temperature=0.7,
        verbose=False,
    )
    optimized = optimizer.compile(
        baseline,
        trainset=[example.as_dspy() for example in training],
        valset=[example.as_dspy() for example in validation],
        num_trials=OPTIMIZER_TRIALS,
        max_bootstrapped_demos=0,
        max_labeled_demos=0,
        minibatch=False,
        program_aware_proposer=False,
        data_aware_proposer=False,
        tip_aware_proposer=False,
        fewshot_aware_proposer=False,
    )
    return cast("RecommendationProgram", optimized)


def evaluate_program(
    program: RecommendationProgram,
    examples: Sequence[OptimizationExample],
) -> InstructionProgramResult:
    """Evaluate one instruction variant over the untouched held-out cases."""
    results: list[InstructionCaseResult] = []
    for example in examples:
        try:
            prediction = program(goal_and_evidence=example.goal_and_evidence)
            results.append(score_candidates(example, _prediction_candidates(prediction)))
        except Exception as error:  # Preserve model and schema failures in the comparison.
            results.append(
                InstructionCaseResult(
                    case_id=example.case_id,
                    succeeded=False,
                    structured_output_valid=False,
                    citations_grounded=False,
                    expected_evidence_met=False,
                    concrete_first_milestones=False,
                    score=0.0,
                    error_type=type(error).__name__,
                )
            )
    return InstructionProgramResult(
        case_count=len(results),
        success_count=sum(result.succeeded for result in results),
        average_score=sum(result.score for result in results) / len(results),
        cases=results,
    )


def held_out_winner(
    maintained: InstructionProgramResult,
    optimized: InstructionProgramResult,
) -> Literal["maintained", "optimized", "tie"]:
    """Select a winner only when quality improves without lower reliability."""
    if (
        optimized.average_score > maintained.average_score
        and optimized.success_count >= maintained.success_count
    ):
        return "optimized"
    if (
        maintained.average_score > optimized.average_score
        and maintained.success_count >= optimized.success_count
    ):
        return "maintained"
    return "tie"


def write_result(result: InstructionOptimizationResult, output_directory: Path) -> Path:
    """Write one immutable DSPy instruction-comparison artifact."""
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = result.metadata.generated_at.strftime("%Y%m%dT%H%M%SZ")
    output_path = output_directory / f"dspy-instructions-{timestamp}.json"
    with output_path.open("x", encoding="utf-8") as output:
        output.write(result.model_dump_json(indent=2))
        output.write("\n")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    """Build the offline DSPy comparison command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, default=PROMPTS_PATH)
    parser.add_argument("--expectations", type=Path, default=EXPECTATIONS_PATH)
    parser.add_argument("--split", type=Path, default=SPLIT_PATH)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Optimize instructions, run the held-out comparison, and save the result."""
    arguments = build_parser().parse_args(argv)
    prompts_path = cast(Path, arguments.prompts)
    expectations_path = cast(Path, arguments.expectations)
    split_path = cast(Path, arguments.split)
    data_directory = cast("Path | None", arguments.data_dir) or load_catalog_directory()
    output_directory = cast(Path, arguments.output_dir)
    settings = load_settings()
    evaluation_set = EvaluationSet.model_validate_json(prompts_path.read_bytes())
    expectations = EvaluationExpectations.model_validate_json(expectations_path.read_bytes())
    split = InstructionOptimizationSplit.model_validate_json(split_path.read_bytes())
    catalog = InMemoryCatalog.from_directory(data_directory)
    training, validation, held_out = partition_examples(
        build_examples(evaluation_set, expectations, catalog), split
    )

    # Disable DSPy's local response cache so every measured trial executes.
    dspy.configure_cache(enable_disk_cache=False, enable_memory_cache=False)
    task_model = dspy.LM(
        f"bedrock/{settings.model_id}",
        aws_region_name=settings.region,
        temperature=0,
        max_tokens=3000,
        cache=False,
    )
    prompt_model = dspy.LM(
        f"bedrock/{settings.model_id}",
        aws_region_name=settings.region,
        temperature=0.7,
        max_tokens=3000,
        cache=False,
    )
    dspy.configure(lm=task_model, adapter=dspy.JSONAdapter())

    maintained_program = create_program(SYSTEM_PROMPT)
    optimized_program = optimize_program(
        maintained_program, training, validation, prompt_model, task_model
    )
    maintained_result = evaluate_program(maintained_program, held_out)
    optimized_result = evaluate_program(optimized_program, held_out)
    optimized_instruction = optimized_program.signature.instructions
    result = InstructionOptimizationResult(
        suite="project-recommendation-dspy-instructions",
        result_version=1,
        metadata=BaselineMetadata(
            generated_at=datetime.now(UTC),
            model_id=settings.model_id,
            region=settings.region,
            dataset=dataset_identity(data_directory, catalog),
            source=source_identity(REPOSITORY),
        ),
        dspy_version=dspy.__version__,
        optimizer="MIPROv2",
        optimizer_candidate_count=OPTIMIZER_CANDIDATES,
        optimizer_trial_count=OPTIMIZER_TRIALS,
        split_version=split.version,
        split_sha256=_sha256(split_path.read_bytes()),
        maintained_instruction_sha256=_sha256(SYSTEM_PROMPT),
        optimized_instruction_sha256=_sha256(optimized_instruction),
        optimized_instruction=optimized_instruction,
        held_out_winner=held_out_winner(maintained_result, optimized_result),
        maintained=maintained_result,
        optimized=optimized_result,
    )
    output_path = write_result(result, output_directory)
    print(output_path.relative_to(REPOSITORY))
    print(
        json.dumps(
            {
                "held_out_winner": result.held_out_winner,
                "maintained": result.maintained.model_dump(mode="json", exclude={"cases"}),
                "optimized": result.optimized.model_dump(mode="json", exclude={"cases"}),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
