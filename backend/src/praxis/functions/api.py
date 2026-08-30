"""Private AWS Lambda entry point for the Praxis application API."""

import json


def lambda_handler(_event: object, _context: object) -> dict[str, object]:
    """Reject requests safely while the private API has no configured routes."""
    return {
        "statusCode": 503,
        "headers": {
            "cache-control": "no-store",
            "content-type": "application/json",
        },
        "body": json.dumps(
            {"error": "Application API routes are unavailable."},
            separators=(",", ":"),
        ),
    }
