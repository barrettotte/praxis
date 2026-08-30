from pathlib import Path

from pydantic import TypeAdapter

from praxis.agent.planner import (
    CandidateGenerationMetrics,
    ProjectPlanningRun,
    TokenUsage,
)
from praxis.catalog import InMemoryCatalog
from praxis.config import AgentSettings
from praxis.domain import EvidenceCitation, ProjectCandidate, ProjectCandidateSet
from praxis.evaluation import DeploymentIdentity, EvaluationExpectations, EvaluationSet
from praxis.evaluation.runner import PlanningInvoker, run_baseline
from praxis.evaluation.runtime import write_result

REPOSITORY = Path(__file__).parents[2]
FIXTURE_DIRECTORY = REPOSITORY / "data" / "fixtures"
PROMPTS_PATH = REPOSITORY / "evals" / "project-recommendations" / "prompts.json"
EXPECTATIONS_PATH = REPOSITORY / "evals" / "project-recommendations" / "expectations.json"


def _candidate_set(evidence_ids: list[str]) -> ProjectCandidateSet:
    candidates: list[ProjectCandidate] = []
    for number in range(1, 4):
        selected_ids = evidence_ids[number - 1 :: 3] or evidence_ids[:1]
        candidates.append(
            ProjectCandidate(
                title=f"Candidate {number}",
                summary="Build a focused project.",
                rationale="It connects the goal to the curated evidence.",
                estimated_scope="weekend",
                technologies=["Python"],
                first_milestone="Build and test one independently verifiable command.",
                evidence_citations=[
                    EvidenceCitation(
                        evidence_id=evidence_id,
                        generated_connection=(
                            "This record supports the proposed project direction."
                        ),
                    )
                    for evidence_id in selected_ids
                ],
            )
        )
    return ProjectCandidateSet(candidates=candidates)


def _fake_invoker(
    evaluation_set: EvaluationSet, expectations: EvaluationExpectations
) -> PlanningInvoker:
    case_ids_by_prompt = {case.prompt: case.id for case in evaluation_set.cases}
    expectations_by_id = {
        expectation.case_id: expectation for expectation in expectations.expectations
    }

    def invoke(
        prompt: str, _catalog: InMemoryCatalog, _settings: AgentSettings | None
    ) -> ProjectPlanningRun:
        expectation = expectations_by_id[case_ids_by_prompt[prompt]]
        evidence_ids = [record.evidence_id for record in expectation.evidence.any_of]
        local_tool_calls = tuple(call.tool for call in expectation.trajectory)
        return ProjectPlanningRun(
            candidates=_candidate_set(evidence_ids),
            retrieved_evidence_ids=tuple(evidence_ids),
            local_tool_calls=local_tool_calls,
            generation_metrics=CandidateGenerationMetrics(
                token_usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
                model_latency_ms=250,
                time_to_first_byte_ms=100,
                model_tool_calls=(("ProjectCandidateSet", 1),),
                cycle_count=2,
            ),
        )

    return invoke


def test_run_baseline_scores_and_aggregates_all_cases(tmp_path: Path) -> None:
    evaluation_set = TypeAdapter(EvaluationSet).validate_json(PROMPTS_PATH.read_bytes())
    expectations = TypeAdapter(EvaluationExpectations).validate_json(EXPECTATIONS_PATH.read_bytes())

    deployment = DeploymentIdentity(
        endpoint_qualifier="stable",
        runtime_version="8",
        container_digest=f"sha256:{'a' * 64}",
    )
    result = run_baseline(
        evaluation_set=evaluation_set,
        expectations=expectations,
        catalog=InMemoryCatalog.from_directory(FIXTURE_DIRECTORY),
        catalog_directory=FIXTURE_DIRECTORY,
        repository=REPOSITORY,
        settings=AgentSettings(model_id="test-model", region="us-east-1"),
        invoker=_fake_invoker(evaluation_set, expectations),
        deployment=deployment,
    )

    assert result.summary.case_count == 10
    assert result.summary.success_count == 10
    assert result.summary.average_quality_score == 1.0
    assert result.summary.expected_evidence_pass_count == 10
    assert result.summary.expected_trajectory_pass_count == 10
    assert result.summary.total_tokens == 1_500
    assert result.summary.total_local_tool_calls == 12
    assert result.summary.total_model_tool_calls == 10
    assert result.metadata.deployment == deployment
    assert all(case.candidates is not None for case in result.cases)

    output_path = write_result(result, tmp_path)
    assert output_path.name.startswith("agentcore-v8-")
    assert output_path.read_text().endswith("\n")
    assert "runtimeSessionId" not in output_path.read_text()
