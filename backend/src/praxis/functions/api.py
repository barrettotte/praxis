"""Private AWS Lambda entry point for the Praxis application API."""

from praxis.api.correlation import response_correlation_id
from praxis.api.requests import ApiRequestError, validate_api_request
from praxis.api.responses import ApiErrorCode, error_response


def lambda_handler(event: object, context: object) -> dict[str, object]:
    """Validate one API Gateway request before dispatching application work."""
    fallback_correlation_id = response_correlation_id(event, context)
    try:
        request = validate_api_request(event)
    except ApiRequestError:
        return error_response(ApiErrorCode.INVALID_REQUEST, fallback_correlation_id)
    return error_response(ApiErrorCode.SERVICE_UNAVAILABLE, request.correlation_id)
