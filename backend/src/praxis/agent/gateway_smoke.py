"""Live Strands agent invocation check for the AgentCore Gateway."""

import argparse
import json
from pathlib import Path

from praxis.agent.gateway import (
    GatewayAgentError,
    GatewayAgentRun,
    discover_gateway_tool_names,
    invoke_gateway_agent,
)
from praxis.config import (
    DEFAULT_MAX_CATALOG_RESULTS,
    DEFAULT_MAX_TOOL_CALLS,
    AgentSettings,
    GatewaySettings,
)

DEFAULT_PROMPT = "compiler"


def write_evidence(evidence_directory: Path, tools: tuple[str, ...]) -> Path:
    """Write a deterministic, credential-free Strands discovery capture."""
    evidence_directory.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_directory / "strands-gateway-tools-list.json"
    capture = {
        "authentication": "AWS_IAM",
        "client": "Strands MCPClient",
        "method": "tools/list",
        "tools": list(tools),
    }
    evidence_path.write_text(f"{json.dumps(capture, indent=2, sort_keys=True)}\n")
    return evidence_path


def write_agent_evidence(
    evidence_directory: Path,
    settings: AgentSettings,
    agent_run: GatewayAgentRun,
) -> Path:
    """Write a credential-free capture of the model and Gateway tool interaction."""
    evidence_directory.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_directory / "strands-gateway-agent-run.json"
    capture = {
        "all_candidates_cited": all(
            candidate.evidence_citations for candidate in agent_run.candidates.candidates
        ),
        "authentication": "AWS_IAM",
        "candidate_count": len(agent_run.candidates.candidates),
        "client": "Strands Agent with MCPClient",
        "evidence_citation_count": sum(
            len(candidate.evidence_citations) for candidate in agent_run.candidates.candidates
        ),
        "model_id": settings.model_id,
        "catalog_result_budget": settings.max_catalog_results,
        "tool_call_budget": settings.max_tool_calls,
        "tool_calls": [{"count": count, "name": name} for name, count in agent_run.tool_calls],
    }
    evidence_path.write_text(f"{json.dumps(capture, indent=2, sort_keys=True)}\n")
    return evidence_path


def run(
    agent_settings: AgentSettings,
    gateway_settings: GatewaySettings,
    prompt: str = DEFAULT_PROMPT,
    evidence_directory: Path | None = None,
) -> dict[str, object]:
    """Discover Gateway tools and require one tool-using Strands invocation."""
    tools = discover_gateway_tool_names(gateway_settings)
    agent_run = invoke_gateway_agent(prompt, agent_settings, gateway_settings)
    if not agent_run.tool_calls:
        raise GatewayAgentError("Strands did not call an AgentCore Gateway tool")
    tools_evidence_path = (
        write_evidence(evidence_directory, tools) if evidence_directory is not None else None
    )
    agent_evidence_path = (
        write_agent_evidence(evidence_directory, agent_settings, agent_run)
        if evidence_directory is not None
        else None
    )
    return {
        "iam_authenticated": True,
        "model_id": agent_settings.model_id,
        "candidates": agent_run.candidates.model_dump(mode="json"),
        "tool_calls": [{"count": count, "name": name} for name, count in agent_run.tool_calls],
        "tools": list(tools),
        "captures": {
            "agent_run": (str(agent_evidence_path) if agent_evidence_path is not None else None),
            "tools_list": (str(tools_evidence_path) if tools_evidence_path is not None else None),
        },
    }


def main() -> None:
    """Run a live Gateway-backed Strands invocation from command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile")
    parser.add_argument("--model-id", required=True)
    parser.add_argument(
        "--max-catalog-results",
        type=int,
        default=DEFAULT_MAX_CATALOG_RESULTS,
    )
    parser.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--evidence-directory", type=Path)
    arguments = parser.parse_args()
    agent_settings = AgentSettings(
        model_id=arguments.model_id,
        region=arguments.region,
        max_catalog_results=arguments.max_catalog_results,
        max_tool_calls=arguments.max_tool_calls,
    )
    gateway_settings = GatewaySettings(
        url=arguments.url,
        region=arguments.region,
        profile=arguments.profile,
    )
    print(
        json.dumps(
            run(
                agent_settings,
                gateway_settings,
                arguments.prompt,
                arguments.evidence_directory,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
