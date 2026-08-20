"""IAM-signed smoke checks for the deployed AgentCore Gateway."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from http.client import HTTPSConnection
from pathlib import Path
from time import perf_counter_ns
from typing import cast
from urllib.parse import urlsplit

from boto3.session import Session
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

MCP_PROTOCOL_VERSION = "2025-03-26"
SIGNING_SERVICE = "bedrock-agentcore"
EXPECTED_TOOL_SUFFIXES = (
    "get_catalog_item",
    "score_project_candidates",
    "search_catalog",
    "summarize_experience",
)


class GatewaySmokeError(RuntimeError):
    """Raised when the deployed Gateway violates its smoke-test contract."""


class GatewayHTTPError(GatewaySmokeError):
    """Preserve an unsuccessful Gateway HTTP response for assertions."""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        super().__init__(f"Gateway returned HTTP {status}: {detail}")


@dataclass(frozen=True)
class MCPMeasurement:
    """Client-observed body sizes and HTTPS round-trip latency."""

    latency_ms: float
    request_bytes: int
    response_bytes: int

    def as_dict(self) -> dict[str, object]:
        """Return the stable measurement fields written to evidence."""
        return {
            "latency_ms": self.latency_ms,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
        }


def _object(value: object, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GatewaySmokeError(message)
    return cast("dict[str, object]", value)


def decode_response(body: bytes, content_type: str) -> dict[str, object]:
    text = body.decode("utf-8")
    if "text/event-stream" not in content_type.lower():
        return _object(json.loads(text), "Gateway response must be a JSON object")

    for event in text.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(
            line.removeprefix("data:").lstrip()
            for line in event.splitlines()
            if line.startswith("data:")
        )
        if data and data != "[DONE]":
            return _object(json.loads(data), "Gateway SSE data must be a JSON object")
    raise GatewaySmokeError("Gateway SSE response contained no JSON data")


def _request_mcp(
    url: str,
    payload: Mapping[str, object],
    *,
    profile: str | None,
    region: str,
) -> tuple[int, bytes, str, MCPMeasurement]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise GatewaySmokeError("Gateway URL must be HTTPS")

    body = json.dumps(payload, separators=(",", ":")).encode()
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "Host": parsed.netloc,
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }

    if profile is not None:
        session = Session(profile_name=profile, region_name=region)
        credentials = session.get_credentials()
        if credentials is None:
            raise GatewaySmokeError(f"AWS profile has no credentials: {profile}")
        request = AWSRequest(method="POST", url=url, data=body, headers=headers)
        SigV4Auth(credentials.get_frozen_credentials(), SIGNING_SERVICE, region).add_auth(request)
        headers = dict(request.headers.items())

    connection = HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=30)
    try:
        started_at = perf_counter_ns()
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        elapsed_ns = perf_counter_ns() - started_at
        status = response.status
        content_type = response.getheader("Content-Type", "")
    finally:
        connection.close()
    measurement = MCPMeasurement(
        latency_ms=round(elapsed_ns / 1_000_000, 3),
        request_bytes=len(body),
        response_bytes=len(response_body),
    )
    return status, response_body, content_type, measurement


def _post_mcp_measured(
    url: str,
    payload: Mapping[str, object],
    *,
    profile: str,
    region: str,
) -> tuple[dict[str, object], MCPMeasurement]:
    status, response_body, content_type, measurement = _request_mcp(
        url, payload, profile=profile, region=region
    )
    if status < 200 or status >= 300:
        detail = response_body.decode("utf-8", errors="replace")
        raise GatewayHTTPError(status, detail)
    return decode_response(response_body, content_type), measurement


def _post_mcp(
    url: str,
    payload: Mapping[str, object],
    *,
    profile: str,
    region: str,
) -> dict[str, object]:
    response, _ = _post_mcp_measured(url, payload, profile=profile, region=region)
    return response


def _result(response: Mapping[str, object]) -> dict[str, object]:
    error = response.get("error")
    if error is not None:
        raise GatewaySmokeError(f"Gateway returned an MCP error: {error}")
    return _object(response.get("result"), "Gateway response is missing an MCP result")


def _listed_tools(response: Mapping[str, object]) -> dict[str, dict[str, object]]:
    tools = _result(response).get("tools")
    if not isinstance(tools, list):
        raise GatewaySmokeError("tools/list result must contain a tools array")
    listed: dict[str, dict[str, object]] = {}
    for value in cast("list[object]", tools):
        tool = _object(value, "Each listed tool must be an object")
        name = tool.get("name")
        if isinstance(name, str):
            listed[name] = tool
    return listed


def write_tools_list_evidence(
    evidence_directory: Path, listed: Mapping[str, dict[str, object]]
) -> Path:
    """Write a deterministic, credential-free capture of signed tool discovery."""
    evidence_directory.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_directory / "phase4-tools-list.json"
    capture = {
        "authentication": "AWS_IAM",
        "method": "tools/list",
        "protocol_version": MCP_PROTOCOL_VERSION,
        "tools": [listed[name] for name in sorted(listed)],
    }
    evidence_path.write_text(f"{json.dumps(capture, indent=2, sort_keys=True)}\n")
    return evidence_path


def write_tool_calls_evidence(
    evidence_directory: Path, calls: Mapping[str, Mapping[str, object]]
) -> Path:
    """Write deterministic, credential-free captures of signed tool calls."""
    evidence_directory.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_directory / "phase4-tool-calls.json"
    capture = {
        "authentication": "AWS_IAM",
        "method": "tools/call",
        "protocol_version": MCP_PROTOCOL_VERSION,
        "calls": [calls[name] for name in EXPECTED_TOOL_SUFFIXES],
    }
    evidence_path.write_text(f"{json.dumps(capture, indent=2, sort_keys=True)}\n")
    return evidence_path


def write_negative_calls_evidence(
    evidence_directory: Path,
    *,
    excessive_limit_observation: str,
    malformed_arguments_observation: str,
    unsigned_status: int,
) -> Path:
    """Write deterministic negative-call results without response internals."""
    evidence_directory.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_directory / "phase4-negative-calls.json"
    capture = {
        "protocol_version": MCP_PROTOCOL_VERSION,
        "tests": [
            {
                "authentication": "AWS_IAM",
                "name": "excessive_result_limit",
                "observation": excessive_limit_observation,
                "rejected": True,
            },
            {
                "authentication": "AWS_IAM",
                "name": "malformed_tool_arguments",
                "observation": malformed_arguments_observation,
                "rejected": True,
            },
            {
                "authentication": "none",
                "http_status": unsigned_status,
                "name": "unsigned_tools_list",
                "rejected": True,
            },
        ],
    }
    evidence_path.write_text(f"{json.dumps(capture, indent=2, sort_keys=True)}\n")
    return evidence_path


def write_tool_metrics_evidence(
    evidence_directory: Path,
    measurements: Mapping[str, MCPMeasurement],
) -> Path:
    """Write one client-side latency and body-size measurement per tool."""
    evidence_directory.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_directory / "phase4-tool-metrics.json"
    capture = {
        "method": "tools/call",
        "protocol_version": MCP_PROTOCOL_VERSION,
        "scope": "Client-observed HTTPS round trip; sizes are JSON request and raw response bodies.",
        "tools": [
            {"name": name, **measurements[name].as_dict()} for name in EXPECTED_TOOL_SUFFIXES
        ],
    }
    evidence_path.write_text(f"{json.dumps(capture, indent=2, sort_keys=True)}\n")
    return evidence_path


def catalog_payload(response: Mapping[str, object]) -> dict[str, object]:
    result = _result(response)
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return cast("dict[str, object]", structured)

    content = result.get("content")
    if isinstance(content, list):
        for value in cast("list[object]", content):
            item = _object(value, "Tool content entries must be objects")
            text = item.get("text")
            if isinstance(text, str):
                decoded = json.loads(text)
                if isinstance(decoded, dict):
                    return cast("dict[str, object]", decoded)
    raise GatewaySmokeError("Tool response contains no structured catalog payload")


def tool_call_rejected(response: Mapping[str, object]) -> bool:
    """Return whether an MCP response explicitly rejects a tool call."""
    if response.get("error") is not None:
        return True
    result = response.get("result")
    if not isinstance(result, dict):
        return False
    return cast("dict[str, object]", result).get("isError") is True


def _signed_rejection_observation(
    url: str,
    payload: Mapping[str, object],
    *,
    profile: str,
    region: str,
) -> str:
    try:
        response = _post_mcp(url, payload, profile=profile, region=region)
    except GatewayHTTPError as error:
        if error.status not in {400, 422, 500}:
            raise
        return f"HTTP {error.status}"
    if tool_call_rejected(response):
        return "MCP error"
    raise GatewaySmokeError("Gateway accepted a request expected to be rejected")


def _call_catalog_tool(
    url: str,
    *,
    request_id: str,
    tool_name: str,
    arguments: dict[str, object],
    profile: str,
    region: str,
) -> tuple[dict[str, object], MCPMeasurement]:
    response, measurement = _post_mcp_measured(
        url,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
        profile=profile,
        region=region,
    )
    return catalog_payload(response), measurement


def run_smoke(
    url: str,
    *,
    profile: str,
    region: str,
    evidence_directory: Path | None = None,
) -> dict[str, object]:
    """List the deployed tools and run one evidence search."""
    listed = _listed_tools(
        _post_mcp(
            url,
            {"jsonrpc": "2.0", "id": "list-tools", "method": "tools/list"},
            profile=profile,
            region=region,
        )
    )
    expected_names = {
        suffix: next(
            (name for name in listed if name.endswith(f"___{suffix}")),
            "",
        )
        for suffix in EXPECTED_TOOL_SUFFIXES
    }
    missing = sorted(suffix for suffix, name in expected_names.items() if not name)
    if missing:
        raise GatewaySmokeError(f"Gateway is missing catalog tools: {', '.join(missing)}")
    evidence_path = (
        write_tools_list_evidence(evidence_directory, listed)
        if evidence_directory is not None
        else None
    )

    search_arguments: dict[str, object] = {"query": "compiler", "limit": 1}
    search_payload, search_measurement = _call_catalog_tool(
        url,
        request_id="search-catalog",
        tool_name=expected_names["search_catalog"],
        arguments=search_arguments,
        profile=profile,
        region=region,
    )
    results = search_payload.get("results")
    if not isinstance(results, list) or not results:
        raise GatewaySmokeError("Catalog search returned no results")
    first = _object(cast("list[object]", results)[0], "Search result must be an object")
    evidence_id = first.get("evidence_id")
    if not isinstance(evidence_id, str):
        raise GatewaySmokeError("Search result is missing its evidence ID")

    get_arguments: dict[str, object] = {"id": evidence_id}
    get_payload, get_measurement = _call_catalog_tool(
        url,
        request_id="get-catalog-item",
        tool_name=expected_names["get_catalog_item"],
        arguments=get_arguments,
        profile=profile,
        region=region,
    )
    item = _object(get_payload.get("item"), "Catalog lookup returned no item")
    if item.get("evidence_id") != evidence_id:
        raise GatewaySmokeError("Catalog lookup returned the wrong evidence item")

    summarize_arguments: dict[str, object] = {
        "description": "A browser notebook for electronics experiments",
        "languages": ["TypeScript"],
        "limit": 1,
    }
    summarize_payload, summarize_measurement = _call_catalog_tool(
        url,
        request_id="summarize-experience",
        tool_name=expected_names["summarize_experience"],
        arguments=summarize_arguments,
        profile=profile,
        region=region,
    )
    matches = summarize_payload.get("matches")
    if not isinstance(matches, list) or not matches:
        raise GatewaySmokeError("Experience summary returned no project evidence")

    score_arguments: dict[str, object] = {
        "candidates": [
            {
                "candidate_id": "notebook",
                "description": "A browser notebook for electronics experiments",
                "languages": ["TypeScript"],
            },
            {
                "candidate_id": "unrelated",
                "description": "zyxwvutsrq",
                "languages": [],
            },
        ]
    }
    score_payload, score_measurement = _call_catalog_tool(
        url,
        request_id="score-project-candidates",
        tool_name=expected_names["score_project_candidates"],
        arguments=score_arguments,
        profile=profile,
        region=region,
    )
    scores = score_payload.get("scores")
    if not isinstance(scores, list) or len(cast("list[object]", scores)) != 2:
        raise GatewaySmokeError("Candidate scoring returned an invalid result count")

    calls = {
        "get_catalog_item": {
            "arguments": get_arguments,
            "result": get_payload,
            "tool": expected_names["get_catalog_item"],
        },
        "score_project_candidates": {
            "arguments": score_arguments,
            "result": score_payload,
            "tool": expected_names["score_project_candidates"],
        },
        "search_catalog": {
            "arguments": search_arguments,
            "result": search_payload,
            "tool": expected_names["search_catalog"],
        },
        "summarize_experience": {
            "arguments": summarize_arguments,
            "result": summarize_payload,
            "tool": expected_names["summarize_experience"],
        },
    }
    calls_evidence_path = (
        write_tool_calls_evidence(evidence_directory, calls)
        if evidence_directory is not None
        else None
    )
    metrics_evidence_path = (
        write_tool_metrics_evidence(
            evidence_directory,
            {
                "get_catalog_item": get_measurement,
                "score_project_candidates": score_measurement,
                "search_catalog": search_measurement,
                "summarize_experience": summarize_measurement,
            },
        )
        if evidence_directory is not None
        else None
    )

    excessive_limit_observation = _signed_rejection_observation(
        url,
        {
            "jsonrpc": "2.0",
            "id": "reject-excessive-limit",
            "method": "tools/call",
            "params": {
                "name": expected_names["search_catalog"],
                "arguments": {"query": "compiler", "limit": 21},
            },
        },
        profile=profile,
        region=region,
    )
    malformed_arguments_observation = _signed_rejection_observation(
        url,
        {
            "jsonrpc": "2.0",
            "id": "reject-malformed-arguments",
            "method": "tools/call",
            "params": {
                "name": expected_names["search_catalog"],
                "arguments": {"limit": 1},
            },
        },
        profile=profile,
        region=region,
    )
    unsigned_status, _, _, _ = _request_mcp(
        url,
        {"jsonrpc": "2.0", "id": "reject-unsigned", "method": "tools/list"},
        profile=None,
        region=region,
    )
    if unsigned_status not in {401, 403}:
        raise GatewaySmokeError(
            f"Unsigned Gateway request returned unexpected HTTP {unsigned_status}"
        )
    negative_calls_evidence_path = (
        write_negative_calls_evidence(
            evidence_directory,
            excessive_limit_observation=excessive_limit_observation,
            malformed_arguments_observation=malformed_arguments_observation,
            unsigned_status=unsigned_status,
        )
        if evidence_directory is not None
        else None
    )

    return {
        "iam_authenticated": True,
        "excessive_limit_rejected": True,
        "malformed_arguments_rejected": True,
        "unsigned_request_rejected": True,
        "tools": sorted(expected_names),
        "search_result": first,
        "tool_metrics_capture": (
            str(metrics_evidence_path) if metrics_evidence_path is not None else None
        ),
        "negative_calls_capture": (
            str(negative_calls_evidence_path) if negative_calls_evidence_path is not None else None
        ),
        "tool_calls_capture": (
            str(calls_evidence_path) if calls_evidence_path is not None else None
        ),
        "tools_list_capture": str(evidence_path) if evidence_path is not None else None,
    }


def main() -> None:
    """Run the deployed Gateway smoke check from command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--profile", default="praxis-dev")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--evidence-directory", type=Path)
    arguments = parser.parse_args()
    print(
        json.dumps(
            run_smoke(
                arguments.url,
                profile=arguments.profile,
                region=arguments.region,
                evidence_directory=arguments.evidence_directory,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
