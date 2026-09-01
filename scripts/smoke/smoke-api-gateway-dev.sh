#!/usr/bin/env bash
# Verify JWT-authenticated Runtime requests and anonymous API rejection.
set -euo pipefail
umask 077

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_marker="untrusted-api-gateway-smoke-marker"
praxis_goal="compiler"
praxis_correlation_id="51f4a405-8835-411d-9821-5980d73f51f6"
praxis_work_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_work_dir}"' EXIT

praxis_require_commands curl jq "${praxis_tofu}"

praxis_access_token="${PRAXIS_ACCESS_TOKEN:-}"
if [[ -z "${praxis_access_token}" ]]; then
  printf 'PRAXIS_ACCESS_TOKEN is required for the JWT-authenticated API suite.\n' >&2
  exit 2
fi
praxis_api_url="$(praxis_tofu_output api_gateway_url)"
praxis_api_url="${praxis_api_url%/}"

# Keep the short-lived bearer token out of process arguments and evidence captures.
jq -nr --arg header "authorization: Bearer ${praxis_access_token}" \
  '"--header " + ($header | @json)' >"${praxis_work_dir}/curl-jwt.config"
unset praxis_access_token

# An authenticated declared route must return three cited buffered candidates.
praxis_known_status="$(
  curl --config "${praxis_work_dir}/curl-jwt.config" \
    --silent --show-error --max-time 35 \
    --dump-header "${praxis_work_dir}/known-route.headers" \
    --output "${praxis_work_dir}/known-route.json" \
    --write-out '%{http_code}' \
    --request POST \
    --header 'content-type: application/json' \
    --header "x-correlation-id: ${praxis_correlation_id}" \
    --data "{\"goal\":\"${praxis_goal}\"}" \
    "${praxis_api_url}/v1/sessions"
)"
praxis_known_response_id="$(
  awk 'tolower($1) == "x-correlation-id:" {gsub("\r", "", $2); print $2}' \
    "${praxis_work_dir}/known-route.headers" | tail -n 1
)"
if [[ "${praxis_known_status}" != "201" ]] || \
  [[ "${praxis_known_response_id}" != "${praxis_correlation_id}" ]] || \
  ! jq -e '
    (.data.evidence | map(.evidence_id)) as $evidence_ids
    | (.data.sessionId
      | test("^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"))
    and (.data.candidates | length == 3)
    and (.data.evidence | length >= 1 and length <= 3)
    and all(.data.evidence[];
      (.evidence_id
        | test("^(book|byte|museum|project):[0-9a-f]{16}$"))
      and (.score == null))
    and all(.data.candidates[];
      (.evidence_citations | length >= 1)
      and all(.evidence_citations[];
        (.evidence_id
          | test("^(book|byte|museum|project):[0-9a-f]{16}$"))
        and (.evidence_id as $id | $evidence_ids | index($id) != null)))' \
    "${praxis_work_dir}/known-route.json" >/dev/null; then
  printf 'Declared API route returned an unexpected response (HTTP %s):\n' \
    "${praxis_known_status}" >&2
  jq . "${praxis_work_dir}/known-route.json" >&2 || true
  exit 1
fi

# A malformed request must fail safely without reflecting its payload.
praxis_invalid_status="$(
  curl --config "${praxis_work_dir}/curl-jwt.config" \
    --silent --show-error --max-time 35 \
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

# JWT authorization must reject the same declared route before Lambda invocation.
praxis_unauthenticated_status="$(
  curl --silent --show-error \
    --output "${praxis_work_dir}/unauthenticated.json" \
    --write-out '%{http_code}' \
    --request POST \
    --header 'content-type: application/json' \
    --data "{\"goal\":\"${praxis_goal}\"}" \
    "${praxis_api_url}/v1/sessions"
)"
if [[ "${praxis_unauthenticated_status}" != "401" ]]; then
  printf 'Unauthenticated API request returned HTTP %s instead of 401.\n' \
    "${praxis_unauthenticated_status}" >&2
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
  '{all_candidates_cited: true, api_gateway_reached: true, buffered_response: true, candidate_count: 3, correlation_id_propagated: true, error_schema_valid: true, handler_status: 201, invalid_request_status: 400, jwt_authenticated: true, runtime_invoked: true, supporting_evidence_resolved: true, unauthenticated_status: 401, unknown_route_status: 404}' \
  >"${praxis_evidence_dir}/api-gateway.json"
jq . "${praxis_evidence_dir}/api-gateway.json"
