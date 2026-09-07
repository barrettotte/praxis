"""Command-line entry point for the project-recommendation baseline."""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pydantic import TypeAdapter

from praxis.catalog import InMemoryCatalog
from praxis.config import load_catalog_directory, load_settings
from praxis.evaluation.models import EvaluationExpectations, EvaluationSet
from praxis.evaluation.runner import run_baseline

REPOSITORY = Path(__file__).parents[4]
DEFAULT_PROMPTS = REPOSITORY / "evals" / "project-recommendations" / "prompts.json"
DEFAULT_EXPECTATIONS = REPOSITORY / "evals" / "project-recommendations" / "expectations.json"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY / "build" / "evals"


def build_parser() -> argparse.ArgumentParser:
    """Build the baseline command-line parser."""
    parser = argparse.ArgumentParser(description="Run the local Nova project-candidate baseline.")
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--expectations", type=Path, default=DEFAULT_EXPECTATIONS)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run all evaluation prompts and save a new immutable result file."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    prompts_path = cast(Path, arguments.prompts)
    expectations_path = cast(Path, arguments.expectations)
    data_directory = cast("Path | None", arguments.data_dir) or load_catalog_directory()
    output_directory = cast(Path, arguments.output_dir)

    evaluation_set = TypeAdapter(EvaluationSet).validate_json(prompts_path.read_bytes())
    expectations = TypeAdapter(EvaluationExpectations).validate_json(expectations_path.read_bytes())
    if [case.id for case in evaluation_set.cases] != [
        expectation.case_id for expectation in expectations.expectations
    ]:
        parser.error("prompt and expectation case IDs do not align")

    result = run_baseline(
        evaluation_set=evaluation_set,
        expectations=expectations,
        catalog=InMemoryCatalog.from_directory(data_directory),
        catalog_directory=data_directory,
        repository=REPOSITORY,
        settings=load_settings(),
    )
    timestamp = result.metadata.generated_at.strftime("%Y%m%dT%H%M%SZ")
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"local-{timestamp}.json"
    with output_path.open("x", encoding="utf-8") as output:
        output.write(result.model_dump_json(indent=2))
        output.write("\n")
    print(output_path.relative_to(REPOSITORY))
    print(result.summary.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
