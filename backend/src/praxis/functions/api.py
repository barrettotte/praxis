"""Private AWS Lambda entry point for the Praxis application API."""

from praxis.api.requests import ApiRequestError, validate_api_request
from praxis.api.responses import ApiErrorCode, error_response


def lambda_handler(event: object, _context: object) -> dict[str, object]:
    """Validate one API Gateway request before dispatching application work."""
    try:
        validate_api_request(event)
    except ApiRequestError:
        return error_response(ApiErrorCode.INVALID_REQUEST)
    return error_response(ApiErrorCode.SERVICE_UNAVAILABLE)
