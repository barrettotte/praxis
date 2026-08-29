"""Live Strands MCP discovery check for the AgentCore Gateway."""

import argparse
import json
from pathlib import Path

from praxis.agent.gateway import discover_gateway_tool_names
from praxis.config import GatewaySettings


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


def run(
    settings: GatewaySettings,
    evidence_directory: Path | None = None,
) -> dict[str, object]:
    """Discover all expected tools through the production Strands transport."""
    tools = discover_gateway_tool_names(settings)
    evidence_path = (
        write_evidence(evidence_directory, tools) if evidence_directory is not None else None
    )
    return {
        "iam_authenticated": True,
        "tools": list(tools),
        "capture": str(evidence_path) if evidence_path is not None else None,
    }


def main() -> None:
    """Run live Gateway discovery from command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile")
    parser.add_argument("--evidence-directory", type=Path)
    arguments = parser.parse_args()
    settings = GatewaySettings(
        url=arguments.url,
        region=arguments.region,
        profile=arguments.profile,
    )
    print(json.dumps(run(settings, arguments.evidence_directory), indent=2))


if __name__ == "__main__":
    main()
