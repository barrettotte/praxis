"""Render the dashboard with OpenTofu without providers, state, or AWS access."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_dashboard_renders_scoped_metrics_and_aggregate_logs(tmp_path: Path) -> None:
    tofu = shutil.which("tofu")
    if tofu is None:
        pytest.skip("OpenTofu is required to render the dashboard template")
    template = Path(__file__).parents[2] / "infra/environments/dev/templates/dashboard.json.tftpl"
    variables = {
        "region": "us-east-1",
        "api_function": "test-api",
        "worker_function": "test-worker",
        "catalog_function": "test-catalog",
        "api_log_group": "/aws/lambda/test-api",
        "model_id": 'test-model"quoted',
    }
    result = subprocess.run(  # noqa: S603 - local template in an empty, provider-free directory
        [tofu, "console"],
        input=f"jsonencode(templatefile({json.dumps(str(template))}, {json.dumps(variables)}))\n",
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        timeout=15,
    )
    # jsonencode converts the multiline template to a quoted value for portable parsing.
    dashboard = json.loads(json.loads(json.loads(result.stdout)))
    widgets = dashboard["widgets"]
    metrics = [widget["properties"] for widget in widgets if widget["type"] == "metric"]
    assert metrics
    observed: set[tuple[str, str]] = set()
    for panel in metrics:
        assert panel["region"] == variables["region"]
        assert panel["period"] > 0
        for namespace, name, dimension, value in panel["metrics"]:
            if namespace == "AWS/Bedrock":
                assert dimension == "ModelId"
                assert value == variables["model_id"]
            else:
                assert namespace == "AWS/Lambda"
                assert dimension == "FunctionName"
                assert value in {
                    variables["api_function"],
                    variables["worker_function"],
                    variables["catalog_function"],
                }
            assert panel["stat"] == ("p95" if name == "Duration" else "Sum")
            observed.add((namespace, name))
    assert {
        ("AWS/Bedrock", "InputTokenCount"),
        ("AWS/Bedrock", "OutputTokenCount"),
        ("AWS/Lambda", "Duration"),
        ("AWS/Lambda", "Errors"),
        ("AWS/Lambda", "Invocations"),
    } <= observed
    queries = [widget["properties"]["query"] for widget in widgets if widget["type"] == "log"]
    assert queries
    for query in queries:
        assert f"SOURCE '{variables['api_log_group']}'" in query
        assert "stats count(*)" in query
        assert "status_code" in query
        assert "outcome" in query
