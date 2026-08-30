#!/usr/bin/env bash
# Verify the application HTTP API reaches only its explicit fixed-response routes.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"
praxis_evidence_dir="${praxis_repo_root}/docs/evidence"
praxis_marker="untrusted-api-gateway-smoke-marker"
praxis_correlation_id="51f4a405-8835-411d-9821-5980d73f51f6"
praxis_work_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_work_dir}"' EXIT

for praxis_command in curl jq "${praxis_tofu}"; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

praxis_api_url="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw api_gateway_url
)"
praxis_api_url="${praxis_api_url%/}"

# A declared route must reach the Lambda without reflecting untrusted input.
praxis_known_status="$(
  curl --silent --show-error \
    --dump-header "${praxis_work_dir}/known-route.headers" \
    --output "${praxis_work_dir}/known-route.json" \
    --write-out '%{http_code}' \
    --request POST \
    --header 'content-type: application/json' \
    --header "x-correlation-id: ${praxis_correlation_id}" \
    --data "{\"goal\":\"${praxis_marker}\"}" \
    "${praxis_api_url}/v1/sessions"
)"
praxis_known_response_id="$(
  awk 'tolower($1) == "x-correlation-id:" {gsub("\r", "", $2); print $2}' \
    "${praxis_work_dir}/known-route.headers" | tail -n 1
)"
if [[ "${praxis_known_status}" != "503" ]] || \
  [[ "${praxis_known_response_id}" != "${praxis_correlation_id}" ]] || \
  ! jq -e --arg marker "${praxis_marker}" \
    '.error.code == "service_unavailable"
      and .error.message == "Application API routes are unavailable."
      and (tostring | contains($marker) | not)' \
    "${praxis_work_dir}/known-route.json" >/dev/null; then
  printf 'Declared API route returned an unexpected response (HTTP %s):\n' \
    "${praxis_known_status}" >&2
  jq . "${praxis_work_dir}/known-route.json" >&2 || true
  exit 1
fi

# A malformed request must fail safely without reflecting its payload.
praxis_invalid_status="$(
  curl --silent --show-error \
    --dump-header "${praxis_work_dir}/invalid-request.headers" \
    --output "${praxis_work_dir}/invalid-request.json" \
    --write-out '%{http_code}' \
    --request POST \
    --header 'content-type: application/json' \
    --header "x-correlation-id: ${praxis_correlation_id}" \
    --data "{\"unexpected\":\"${praxis_marker}\"}" \
    "${praxis_api_url}/v1/sessions"
)"
praxis_invalid_response_id="$(
  awk 'tolower($1) == "x-correlation-id:" {gsub("\r", "", $2); print $2}' \
    "${praxis_work_dir}/invalid-request.headers" | tail -n 1
)"
if [[ "${praxis_invalid_status}" != "400" ]] || \
  [[ "${praxis_invalid_response_id}" != "${praxis_correlation_id}" ]] || \
  ! jq -e --arg marker "${praxis_marker}" \
    '.error.code == "invalid_request"
      and .error.message == "Invalid request."
      and (tostring | contains($marker) | not)' \
    "${praxis_work_dir}/invalid-request.json" >/dev/null; then
  printf 'Invalid API request returned an unexpected response (HTTP %s):\n' \
    "${praxis_invalid_status}" >&2
  jq . "${praxis_work_dir}/invalid-request.json" >&2 || true
  exit 1
fi

# An undeclared route must stop at API Gateway rather than invoke the Lambda.
praxis_unknown_status="$(
  curl --silent --show-error \
    --output "${praxis_work_dir}/unknown-route.json" \
    --write-out '%{http_code}' \
    "${praxis_api_url}/not-a-route"
)"
if [[ "${praxis_unknown_status}" != "404" ]]; then
  printf 'Undeclared API route returned HTTP %s instead of 404:\n' \
    "${praxis_unknown_status}" >&2
  jq . "${praxis_work_dir}/unknown-route.json" >&2 || true
  exit 1
fi

mkdir -p "${praxis_evidence_dir}"
jq -n \
  '{api_gateway_reached: true, correlation_id_propagated: true, error_schema_valid: true, handler_status: 503, invalid_request_status: 400, payload_reflected: false, unknown_route_status: 404}' \
  >"${praxis_evidence_dir}/api-gateway.json"
jq . "${praxis_evidence_dir}/api-gateway.json"
