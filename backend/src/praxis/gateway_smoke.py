"""IAM-signed smoke checks for the deployed AgentCore Gateway."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from http.client import HTTPSConnection
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
) -> tuple[int, bytes, str]:
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
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        status = response.status
        content_type = response.getheader("Content-Type", "")
    finally:
        connection.close()
    return status, response_body, content_type


def _post_mcp(
    url: str, payload: Mapping[str, object], *, profile: str, region: str
) -> dict[str, object]:
    status, body, content_type = _request_mcp(url, payload, profile=profile, region=region)
    if not 200 <= status < 300:
        raise GatewayHTTPError(status, body.decode("utf-8", errors="replace"))
    return decode_response(body, content_type)


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


def catalog_payload(response: Mapping[str, object]) -> dict[str, object]:
    result = _result(response)
    if result.get("isError") is True:
        raise GatewaySmokeError("Gateway tool call failed")
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


def run_smoke(url: str, *, profile: str, region: str) -> str:
    """Check authorization, discovery, and one search/lookup round trip."""
    discovery = {"jsonrpc": "2.0", "id": "list-tools", "method": "tools/list"}
    status, _, _ = _request_mcp(url, discovery, profile=None, region=region)
    if status not in {401, 403}:
        raise GatewaySmokeError(f"Unsigned Gateway request returned HTTP {status}")
    listed = _listed_tools(_post_mcp(url, discovery, profile=profile, region=region))
    names: dict[str, str] = {}
    for suffix in EXPECTED_TOOL_SUFFIXES:
        matches = [name for name in listed if name.endswith(f"___{suffix}")]
        if len(matches) != 1:
            raise GatewaySmokeError(f"Expected one Gateway tool for {suffix}")
        names[suffix] = matches[0]

    def call(name: str, arguments: dict[str, object]) -> dict[str, object]:
        return catalog_payload(
            _post_mcp(
                url,
                {
                    "jsonrpc": "2.0",
                    "id": name,
                    "method": "tools/call",
                    "params": {"name": names[name], "arguments": arguments},
                },
                profile=profile,
                region=region,
            )
        )

    results = call("search_catalog", {"query": "compiler", "limit": 1}).get("results")
    if not isinstance(results, list) or not results:
        raise GatewaySmokeError("Catalog search returned no results")
    first = _object(cast("list[object]", results)[0], "Search result must be an object")
    evidence_id = first.get("evidence_id")
    if not isinstance(evidence_id, str) or not evidence_id:
        raise GatewaySmokeError("Search result is missing its evidence ID")
    item = _object(
        call("get_catalog_item", {"id": evidence_id}).get("item"), "Catalog lookup failed"
    )
    if item.get("evidence_id") != evidence_id:
        raise GatewaySmokeError("Catalog lookup returned the wrong evidence item")
    return "Gateway authorization, tool discovery, and catalog round trip passed."


def main() -> None:
    """Run the deployed Gateway diagnostic."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--profile", default="praxis-dev")
    parser.add_argument("--region", default="us-east-1")
    arguments = parser.parse_args()
    print(run_smoke(arguments.url, profile=arguments.profile, region=arguments.region))


if __name__ == "__main__":
    main()
