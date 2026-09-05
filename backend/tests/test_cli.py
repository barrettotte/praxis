"""Tests for the local command-line demonstration."""

import json
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from praxis import cli
from praxis.catalog import InMemoryCatalog
from praxis.domain import EvidenceCitation, ProjectCandidate, ProjectCandidateSet
from praxis.domain.candidate_validation import JsonValue

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "data" / "fixtures"


def response() -> ProjectCandidateSet:
    candidates = [
        ProjectCandidate(
            title=f"Candidate {number}",
            summary="Build a focused project.",
            rationale="It connects the goal to prior evidence.",
            estimated_scope="weekend",
            technologies=["Python"],
            first_milestone="Print one evidence-backed result.",
            evidence_citations=[
                EvidenceCitation(
                    evidence_id="book:0000000000000000",
                    generated_connection="Generated explanation of the evidence connection.",
                )
            ],
        )
        for number in range(1, 4)
    ]
    return ProjectCandidateSet(candidates=candidates)


def test_main_renders_readable_candidates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The default output is readable and preserves evidence labels."""

    def fake_invoke(prompt: str, catalog: InMemoryCatalog) -> ProjectCandidateSet:
        assert prompt == "build something useful"
        assert len(catalog) == 8
        return response()

    monkeypatch.setattr(cli, "invoke_project_candidates", fake_invoke)

    assert cli.main(["build something useful", "--data-dir", str(FIXTURE_DIRECTORY)]) == 0
    output = capsys.readouterr().out
    assert "1. Candidate 1 [weekend]" in output
    assert "Evidence connections (generated)" in output
    assert "book:0000000000000000" in output


def test_main_can_emit_structured_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_invoke(_prompt: str, _catalog: InMemoryCatalog) -> ProjectCandidateSet:
        return response()

    monkeypatch.setattr(cli, "invoke_project_candidates", fake_invoke)

    arguments = ["build something useful", "--data-dir", str(FIXTURE_DIRECTORY), "--json"]
    assert cli.main(arguments) == 0
    payload = cast("dict[str, JsonValue]", json.loads(capsys.readouterr().out))
    assert isinstance(payload["candidates"], list)
    assert len(payload["candidates"]) == 3


def test_main_reports_catalog_load_errors(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.main(["build something useful", "--data-dir", "missing-directory"])

    assert "Unable to load catalog records" in capsys.readouterr().err


def test_main_rejects_credentials_before_catalog_or_model_work(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(InMemoryCatalog, "from_directory") as load_catalog,
        patch.object(cli, "invoke_project_candidates") as invoke,
        pytest.raises(SystemExit, match="2"),
    ):
        cli.main(["Build with api_key=synthetic-credential"])
    load_catalog.assert_not_called()
    invoke.assert_not_called()
    output = capsys.readouterr()
    assert "remove them and retry" in output.err
    assert "synthetic-credential" not in output.out + output.err
