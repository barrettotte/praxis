"""Check the scope and limits of accidental credential disclosure screening."""

import pytest

from praxis.domain.prompt_safety import (
    SensitiveInputError,
    contains_likely_secret,
    require_safe_content,
)


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


@pytest.mark.parametrize(
    "content",
    [
        {"password": "synthetic-credential"},
        {"nested": [{"text": "api_key=synthetic-credential"}]},
        ("safe context", "AWS_SESSION_TOKEN=synthetic-credential"),
    ],
)
def test_nested_content_is_rejected_without_attaching_matched_values(content: object) -> None:
    with pytest.raises(SensitiveInputError) as raised:
        require_safe_content(content)
    assert "synthetic-credential" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_safe_json_values_pass() -> None:
    require_safe_content({"goal": "Learn JWT authentication", "items": [None, True, 42, 1.5]})
