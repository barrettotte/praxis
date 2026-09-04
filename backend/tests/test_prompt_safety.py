"""Check the scope and limits of accidental credential disclosure screening."""

import pytest

from praxis.api.prompt_safety import contains_likely_secret


@pytest.mark.parametrize(
    "goal",
    [
        "Build a password manager and learn about API keys and access tokens.",
        "Learn electromagnetism with electric motors.",
        "Explain public key encryption and JWT authentication.",
        "Use book:0f5ba253568e4836 for a compiler project.",
        "Design a parser for password assignments without using real credentials.",
    ],
)
def test_ordinary_learning_goals_are_not_blocked(goal: str) -> None:
    assert not contains_likely_secret(goal)


def test_unlabelled_passwords_are_not_detectable_by_format() -> None:
    assert not contains_likely_secret("My passphrase is a synthetic example of ordinary words.")
