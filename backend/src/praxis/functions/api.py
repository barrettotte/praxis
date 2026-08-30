"""Private AWS Lambda entry point for the Praxis application API."""

import json

from praxis.api.requests import ApiRequestError, validate_api_request


def _response(status_code: int, message: str) -> dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {
            "cache-control": "no-store",
            "content-type": "application/json",
        },
        "body": json.dumps({"error": message}, separators=(",", ":")),
    }


def lambda_handler(event: object, _context: object) -> dict[str, object]:
    """Validate one API Gateway request before dispatching application work."""
    try:
        validate_api_request(event)
    except ApiRequestError:
        return _response(400, "Invalid request.")
    return _response(503, "Application API routes are unavailable.")
