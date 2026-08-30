#!/usr/bin/env bash
# Verify the private API Lambda rejects oversized bodies before Runtime work.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_body_limit_bytes=16384
praxis_marker="oversized-body-must-not-be-reflected"
praxis_correlation_id="51f4a405-8835-411d-9821-5980d73f51f6"

praxis_require_commands aws jq "${praxis_tofu}"

mkdir -p "${praxis_build_dir}" "${praxis_evidence_dir}"
praxis_function_name="$(praxis_tofu_output api_lambda_name)"

# Construct a valid API Gateway event whose decoded JSON body exceeds the limit.
praxis_payload="$(
  jq -nc \
    --arg correlation_id "${praxis_correlation_id}" \
    --arg marker "${praxis_marker}" \
    --argjson body_limit "${praxis_body_limit_bytes}" \
    '{
      version: "2.0",
      routeKey: "POST /v1/sessions",
      headers: {
        "content-type": "application/json",
        "x-correlation-id": $correlation_id
      },
      isBase64Encoded: false,
      requestContext: {requestId: "MqgCjHCKoAMEPLw="},
      body: ({goal: $marker, padding: ("x" * ($body_limit + 1))} | tojson)
    }'
)"
praxis_request_body_bytes="$(jq -r '.body | utf8bytelength' <<<"${praxis_payload}")"
if ((praxis_request_body_bytes <= praxis_body_limit_bytes)); then
  printf 'Smoke payload did not exceed %d bytes.\n' "${praxis_body_limit_bytes}" >&2
  exit 1
fi

aws --profile "${praxis_profile}" --region "${praxis_region}" lambda invoke \
  --function-name "${praxis_function_name}" \
  --cli-binary-format raw-in-base64-out \
  --payload "${praxis_payload}" \
  "${praxis_build_dir}/api-payload-smoke-response.json" \
  --output json >"${praxis_build_dir}/api-payload-smoke-metadata.json"

praxis_function_error="$(
  jq -r '.FunctionError // empty' "${praxis_build_dir}/api-payload-smoke-metadata.json"
)"
if [[ -n "${praxis_function_error}" ]]; then
  printf 'API Lambda failed (%s):\n' "${praxis_function_error}" >&2
  jq . "${praxis_build_dir}/api-payload-smoke-response.json" >&2
  exit 1
fi

# The fixed response proves validation stopped before the Runtime-backed handler.
if ! jq -e \
  --arg correlation_id "${praxis_correlation_id}" \
  --arg marker "${praxis_marker}" \
  '.statusCode == 413
    and .headers["cache-control"] == "no-store"
    and .headers["content-type"] == "application/json"
    and .headers["x-correlation-id"] == $correlation_id
    and .isBase64Encoded == false
    and ((.body | fromjson) == {
      error: {
        code: "payload_too_large",
        message: "Request payload is too large."
      }
    })
    and (.body | contains($marker) | not)' \
  "${praxis_build_dir}/api-payload-smoke-response.json" >/dev/null; then
  printf 'API Lambda returned an unexpected oversized-payload response:\n' >&2
  jq . "${praxis_build_dir}/api-payload-smoke-response.json" >&2
  exit 1
fi

jq -n --argjson body_limit "${praxis_body_limit_bytes}" \
  '{authenticated_direct_invocation: true, body_limit_bytes: $body_limit, oversized_status: 413, runtime_invoked: false}' \
  >"${praxis_evidence_dir}/api-payload-limits.json"
jq . "${praxis_evidence_dir}/api-payload-limits.json"
