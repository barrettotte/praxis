import json
from pathlib import Path

from praxis.agent.gateway_smoke import write_evidence


def test_write_deterministic_strands_discovery_evidence(tmp_path: Path) -> None:
    evidence_path = write_evidence(
        tmp_path,
        (
            "praxis-dev-catalog___get_catalog_item",
            "praxis-dev-catalog___score_project_candidates",
            "praxis-dev-catalog___search_catalog",
            "praxis-dev-catalog___summarize_experience",
        ),
    )

    assert json.loads(evidence_path.read_text()) == {
        "authentication": "AWS_IAM",
        "client": "Strands MCPClient",
        "method": "tools/list",
        "tools": [
            "praxis-dev-catalog___get_catalog_item",
            "praxis-dev-catalog___score_project_candidates",
            "praxis-dev-catalog___search_catalog",
            "praxis-dev-catalog___summarize_experience",
        ],
    }
