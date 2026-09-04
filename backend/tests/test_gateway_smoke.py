import json
from pathlib import Path
from typing import cast

import pytest

from praxis.gateway_smoke import (
    GatewaySmokeError,
    MCPMeasurement,
    catalog_payload,
    decode_response,
    tool_call_rejected,
    write_negative_calls_evidence,
    write_tool_calls_evidence,
    write_tool_metrics_evidence,
    write_tools_list_evidence,
)


def test_decode_gateway_json_and_sse_responses() -> None:
    payload: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": "tools",
        "result": {"tools": []},
    }
    encoded = json.dumps(payload).encode()

    assert decode_response(encoded, "application/json") == payload
    assert (
        decode_response(b"event: message\ndata: " + encoded + b"\n\n", "text/event-stream")
        == payload
    )


def test_extract_catalog_payload_from_text_content() -> None:
    response = {
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": '{"results":[{"evidence_id":"book:0f5ba253568e4836"}]}',
                }
            ]
        }
    }

    assert catalog_payload(response) == {"results": [{"evidence_id": "book:0f5ba253568e4836"}]}


def test_reject_mcp_errors() -> None:
    with pytest.raises(GatewaySmokeError, match="MCP error"):
        catalog_payload({"error": {"code": -32603, "message": "failed"}})


@pytest.mark.parametrize(
    "response",
    [
        {"error": {"code": -32602, "message": "invalid arguments"}},
        {"result": {"isError": True, "content": []}},
    ],
)
def test_detect_explicit_tool_rejections(response: dict[str, object]) -> None:
    assert tool_call_rejected(response)


def test_do_not_treat_successful_tool_result_as_rejected() -> None:
    assert not tool_call_rejected({"result": {"content": []}})


def test_write_deterministic_tools_list_evidence(tmp_path: Path) -> None:
    capture_path = write_tools_list_evidence(
        tmp_path,
        {
            "target___search_catalog": {
                "name": "target___search_catalog",
                "description": "Search catalog evidence.",
                "inputSchema": {"type": "object"},
            }
        },
    )

    assert json.loads(capture_path.read_text()) == {
        "authentication": "AWS_IAM",
        "method": "tools/list",
        "protocol_version": "2025-03-26",
        "tools": [
            {
                "name": "target___search_catalog",
                "description": "Search catalog evidence.",
                "inputSchema": {"type": "object"},
            }
        ],
    }


def test_write_deterministic_tool_call_evidence(tmp_path: Path) -> None:
    calls = {
        name: {
            "arguments": {"fixture": name},
            "result": {"ok": True},
            "tool": f"target___{name}",
        }
        for name in (
            "get_catalog_item",
            "score_project_candidates",
            "search_catalog",
            "summarize_experience",
        )
    }

    capture_path = write_tool_calls_evidence(tmp_path, calls)
    capture = cast("dict[str, object]", json.loads(capture_path.read_text()))

    assert capture["authentication"] == "AWS_IAM"
    assert capture["method"] == "tools/call"
    assert capture["protocol_version"] == "2025-03-26"
    capture_calls = cast("list[dict[str, object]]", capture["calls"])
    assert [call["tool"] for call in capture_calls] == [
        "target___get_catalog_item",
        "target___score_project_candidates",
        "target___search_catalog",
        "target___summarize_experience",
    ]


def test_write_negative_call_evidence_without_response_details(tmp_path: Path) -> None:
    capture_path = write_negative_calls_evidence(
        tmp_path,
        excessive_limit_observation="MCP error",
        malformed_arguments_observation="HTTP 400",
        oversized_candidate_batch_observation="MCP error",
        oversized_query_observation="MCP error",
        unregistered_tool_observation="MCP error",
        unsigned_status=403,
    )

    assert json.loads(capture_path.read_text()) == {
        "protocol_version": "2025-03-26",
        "tests": [
            {
                "authentication": "AWS_IAM",
                "name": "excessive_result_limit",
                "observation": "MCP error",
                "rejected": True,
            },
            {
                "authentication": "AWS_IAM",
                "name": "malformed_tool_arguments",
                "observation": "HTTP 400",
                "rejected": True,
            },
            {
                "authentication": "AWS_IAM",
                "name": "oversized_candidate_batch",
                "observation": "MCP error",
                "rejected": True,
            },
            {
                "authentication": "AWS_IAM",
                "name": "oversized_search_query",
                "observation": "MCP error",
                "rejected": True,
            },
            {
                "authentication": "AWS_IAM",
                "name": "unregistered_tool",
                "observation": "MCP error",
                "rejected": True,
            },
            {
                "authentication": "none",
                "http_status": 403,
                "name": "unsigned_tools_list",
                "rejected": True,
            },
        ],
    }


def test_write_one_latency_and_payload_measurement_per_tool(tmp_path: Path) -> None:
    measurements = {
        name: MCPMeasurement(
            latency_ms=float(index),
            request_bytes=index * 10,
            response_bytes=index * 20,
        )
        for index, name in enumerate(
            (
                "get_catalog_item",
                "score_project_candidates",
                "search_catalog",
                "summarize_experience",
            ),
            start=1,
        )
    }

    capture_path = write_tool_metrics_evidence(tmp_path, measurements)
    capture = cast("dict[str, object]", json.loads(capture_path.read_text()))
    tools = cast("list[dict[str, object]]", capture["tools"])

    assert [tool["name"] for tool in tools] == [
        "get_catalog_item",
        "score_project_candidates",
        "search_catalog",
        "summarize_experience",
    ]
    assert tools[0] == {
        "latency_ms": 1.0,
        "name": "get_catalog_item",
        "request_bytes": 10,
        "response_bytes": 20,
    }
