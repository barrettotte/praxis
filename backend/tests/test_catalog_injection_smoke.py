import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from strands.agent.agent_result import AgentResult

from praxis.agent import catalog_injection_smoke
from praxis.agent.catalog_injection_smoke import CatalogInjectionSmokeError
from praxis.config import AgentSettings
from praxis.domain import EvidenceCitation, ProjectCandidate, ProjectCandidateSet


def settings() -> AgentSettings:
    return AgentSettings(
        model_id="amazon.nova-pro-v1:0",
        region="us-east-1",
        guardrail_id="guardrail-123",
        guardrail_version="1",
    )


def candidate_set(title: str = "Build a compiler exercise") -> ProjectCandidateSet:
    return ProjectCandidateSet(
        candidates=[
            ProjectCandidate(
                title=f"{title} {number}",
                summary="Implement one bounded compiler component.",
                rationale="The synthetic evidence provides relevant compiler context.",
                estimated_scope="weekend",
                technologies=["Python"],
                first_milestone="Parse one arithmetic expression.",
                evidence_citations=[
                    EvidenceCitation(
                        evidence_id="book:0000000000000001",
                        generated_connection="The record concerns compiler construction.",
                    )
                ],
            )
            for number in range(1, 4)
        ]
    )


def test_run_keeps_catalog_injection_outside_guardrail_and_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = MagicMock(return_value=cast("AgentResult", SimpleNamespace(stop_reason="end_turn")))
    monkeypatch.setattr(catalog_injection_smoke, "create_agent", MagicMock(return_value=agent))
    monkeypatch.setattr(
        catalog_injection_smoke,
        "validate_gateway_candidate_result",
        MagicMock(return_value=candidate_set()),
    )

    result = catalog_injection_smoke.run(settings(), evidence_directory=tmp_path)

    prompt = cast("list[dict[str, object]]", agent.call_args.args[0])
    assert prompt[0] == {"guardContent": {"text": {"text": catalog_injection_smoke.DEFAULT_GOAL}}}
    assert catalog_injection_smoke.ATTACK_MARKER in cast("str", prompt[1]["text"])
    assert result["attack_marker_followed"] is False
    capture = json.loads((tmp_path / "catalog-prompt-injection.json").read_text())
    assert capture["catalog_fixture"] == "synthetic_in_memory"
    assert capture["authoritative_sources_modified"] is False


def test_run_rejects_attack_marker_in_model_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = MagicMock(return_value=cast("AgentResult", SimpleNamespace(stop_reason="end_turn")))
    monkeypatch.setattr(catalog_injection_smoke, "create_agent", MagicMock(return_value=agent))
    monkeypatch.setattr(
        catalog_injection_smoke,
        "validate_gateway_candidate_result",
        MagicMock(return_value=candidate_set(catalog_injection_smoke.ATTACK_MARKER)),
    )

    with pytest.raises(CatalogInjectionSmokeError, match="followed or repeated"):
        catalog_injection_smoke.run(settings())
