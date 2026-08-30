#!/usr/bin/env bash
# Verify signed application requests reach Runtime while anonymous requests stop.
set -euo pipefail
umask 077

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"
praxis_evidence_dir="${praxis_repo_root}/docs/evidence"
praxis_marker="untrusted-api-gateway-smoke-marker"
praxis_goal="compiler"
praxis_correlation_id="51f4a405-8835-411d-9821-5980d73f51f6"
praxis_work_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_work_dir}"' EXIT

for praxis_command in aws curl jq "${praxis_tofu}"; do
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

# Keep short-lived credentials out of process arguments and evidence captures.
aws configure export-credentials --profile "${praxis_profile}" --format process |
  jq -r --arg signature "aws:amz:${praxis_region}:execute-api" '
    "--aws-sigv4 " + ($signature | @json),
    "--user " + ((.AccessKeyId + ":" + .SecretAccessKey) | @json),
    (if (.SessionToken // "") != ""
      then "--header " + (("x-amz-security-token: " + .SessionToken) | @json)
      else empty
    end)
  ' >"${praxis_work_dir}/curl-aws.config"

# A signed declared route must return three buffered, evidence-backed candidates.
praxis_known_status="$(
  curl --config "${praxis_work_dir}/curl-aws.config" \
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
    (.data.sessionId
      | test("^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"))
    and (.data.candidates | length == 3)
    and all(.data.candidates[];
      (.evidence_citations | length >= 1)
      and all(.evidence_citations[];
        .evidence_id
        | test("^(book|byte|museum|project):[0-9a-f]{16}$")))' \
    "${praxis_work_dir}/known-route.json" >/dev/null; then
  printf 'Declared API route returned an unexpected response (HTTP %s):\n' \
    "${praxis_known_status}" >&2
  jq . "${praxis_work_dir}/known-route.json" >&2 || true
  exit 1
fi

# A malformed request must fail safely without reflecting its payload.
praxis_invalid_status="$(
  curl --config "${praxis_work_dir}/curl-aws.config" \
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

# IAM authorization must reject the same declared route before Lambda invocation.
praxis_unauthenticated_status="$(
  curl --silent --show-error \
    --output "${praxis_work_dir}/unauthenticated.json" \
    --write-out '%{http_code}' \
    --request POST \
    --header 'content-type: application/json' \
    --data "{\"goal\":\"${praxis_goal}\"}" \
    "${praxis_api_url}/v1/sessions"
)"
if [[ "${praxis_unauthenticated_status}" != "403" ]]; then
  printf 'Unauthenticated API request returned HTTP %s instead of 403.\n' \
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
  '{all_candidates_cited: true, api_gateway_reached: true, buffered_response: true, candidate_count: 3, correlation_id_propagated: true, error_schema_valid: true, handler_status: 201, iam_authenticated: true, invalid_request_status: 400, runtime_invoked: true, unauthenticated_status: 403, unknown_route_status: 404}' \
  >"${praxis_evidence_dir}/api-gateway.json"
jq . "${praxis_evidence_dir}/api-gateway.json"
