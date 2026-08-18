"""Command-line entry point for the local Praxis agent."""

import argparse
from collections.abc import Sequence
from typing import cast

from praxis.agent import invoke
from praxis.config import SettingsError


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Run the local Praxis agent.")
    parser.add_argument("prompt", help="Goal or project-planning request")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    prompt = cast(str, arguments.prompt)

    try:
        response = invoke(prompt)
    except SettingsError as error:
        parser.error(str(error))

    print(response)
    return 0
