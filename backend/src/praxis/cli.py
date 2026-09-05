"""Command-line entry point for the local Praxis agent."""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from praxis.agent import invoke_project_candidates
from praxis.agent.planner import CandidatePlanningError
from praxis.catalog import CatalogLoadError, InMemoryCatalog
from praxis.config import SettingsError, load_catalog_directory
from praxis.domain import ProjectCandidateSet
from praxis.domain.prompt_safety import SensitiveInputError, require_safe_content


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Generate three evidence-backed project candidates."
    )
    parser.add_argument("prompt", help="Goal or project-planning request")
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Directory containing books.json, projects.json, bytes.json, and museum.json",
    )
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output")
    return parser


def render_candidates(result: ProjectCandidateSet) -> str:
    """Render structured candidates for a readable terminal demonstration."""
    sections: list[str] = []
    for index, candidate in enumerate(result.candidates, start=1):
        technologies = ", ".join(candidate.technologies)
        evidence = "\n".join(
            f"   - {reference.evidence_id}: {reference.generated_connection}"
            for reference in candidate.evidence_citations
        )
        sections.append(
            f"{index}. {candidate.title} [{candidate.estimated_scope}]\n"
            f"   {candidate.summary}\n"
            f"   Why: {candidate.rationale}\n"
            f"   Technologies: {technologies}\n"
            f"   First milestone: {candidate.first_milestone}\n"
            f"   Evidence connections (generated):\n{evidence}"
        )
    return "\n\n".join(sections)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    prompt = cast(str, arguments.prompt)
    data_directory = cast("Path | None", arguments.data_dir) or load_catalog_directory()
    json_output = cast(bool, arguments.json)

    try:
        require_safe_content(prompt)
        catalog = InMemoryCatalog.from_directory(data_directory)
        response = invoke_project_candidates(prompt, catalog)
    except (CandidatePlanningError, CatalogLoadError, SettingsError, SensitiveInputError) as error:
        parser.error(str(error))

    print(response.model_dump_json(indent=2) if json_output else render_candidates(response))
    return 0
