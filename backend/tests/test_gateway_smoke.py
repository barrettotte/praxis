import json
from unittest.mock import patch

import pytest

from praxis import gateway_smoke
from praxis.gateway_smoke import (
    GatewaySmokeError,
    catalog_payload,
    decode_response,
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
    "failure", [None, "unsigned", "missing_tool", "empty", "wrong_id", "tool_error"]
)
def test_gateway_checks_a_bounded_round_trip(failure: str | None) -> None:
    names = list(gateway_smoke.EXPECTED_TOOL_SUFFIXES)
    if failure == "missing_tool":
        names.pop()
    responses = [
        {"result": {"tools": [{"name": f"catalog___{name}"} for name in names]}},
        {
            "result": {
                "structuredContent": {
                    "results": []
                    if failure == "empty"
                    else [{"evidence_id": "book:aaaaaaaaaaaaaaaa"}]
                }
            }
        },
        {
            "result": {
                "isError": failure == "tool_error",
                "structuredContent": {
                    "item": {
                        "evidence_id": "wrong" if failure == "wrong_id" else "book:aaaaaaaaaaaaaaaa"
                    }
                },
            }
        },
    ]
    with (
        patch.object(
            gateway_smoke,
            "_request_mcp",
            return_value=(200 if failure == "unsigned" else 403, b"", ""),
        ) as unsigned,
        patch.object(gateway_smoke, "_post_mcp", side_effect=responses) as signed,
    ):
        if failure:
            with pytest.raises(GatewaySmokeError):
                gateway_smoke.run_smoke(
                    "https://gateway.example/mcp", profile="test", region="us-east-1"
                )
        else:
            assert "passed" in gateway_smoke.run_smoke(
                "https://gateway.example/mcp", profile="test", region="us-east-1"
            )
            assert [call.args[1]["method"] for call in signed.call_args_list] == [
                "tools/list",
                "tools/call",
                "tools/call",
            ]
        unsigned.assert_called_once()
        assert signed.call_count <= 3
