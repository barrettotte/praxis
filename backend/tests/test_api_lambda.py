"""Tests for the private application API Lambda shell."""

import json

from praxis.functions.api import lambda_handler


def test_api_lambda_returns_fixed_non_cacheable_unavailable_response() -> None:
    response = lambda_handler({"untrusted": "do-not-reflect"}, object())

    assert response == {
        "statusCode": 503,
        "headers": {
            "cache-control": "no-store",
            "content-type": "application/json",
        },
        "body": '{"error":"Application API routes are unavailable."}',
    }
    assert "do-not-reflect" not in json.dumps(response)


def test_api_lambda_returns_independent_response_objects() -> None:
    first = lambda_handler({}, object())
    second = lambda_handler({}, object())

    assert first is not second
    assert first["headers"] is not second["headers"]
