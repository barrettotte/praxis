"""Tests for the local command-line interface."""

import pytest

from praxis import cli


def test_main_invokes_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI prints the agent response and returns success."""

    def fake_invoke(prompt: str) -> str:
        return f"response for {prompt}"

    monkeypatch.setattr(cli, "invoke", fake_invoke)

    assert cli.main(["build something useful"]) == 0
    assert capsys.readouterr().out == "response for build something useful\n"
