#!/usr/bin/env bash
# Verify the private API Lambda rejects oversized bodies before Runtime work.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_body_limit_bytes=16384
praxis_prompt_limit_characters=4000
praxis_marker="oversized-body-must-not-be-reflected"
praxis_prompt_marker="oversized-prompt-must-not-be-reflected"
praxis_correlation_id="51f4a405-8835-411d-9821-5980d73f51f6"
praxis_actor_id="7b9db85b-9448-4a41-9bb7-235a461429ae"

praxis_require_commands aws jq "${praxis_tofu}"

mkdir -p "${praxis_build_dir}" "${praxis_evidence_dir}"
praxis_function_name="$(praxis_tofu_output api_lambda_name)"

# Construct a valid API Gateway event whose decoded JSON body exceeds the limit.
praxis_payload="$(
  jq -nc \
    --arg correlation_id "${praxis_correlation_id}" \
    --arg actor_id "${praxis_actor_id}" \
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
      requestContext: {
        requestId: "MqgCjHCKoAMEPLw=",
        authorizer: {jwt: {claims: {sub: $actor_id}}}
      },
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

# A goal above the field limit must fail before queueing model-backed work.
praxis_prompt_payload="$(
  jq -nc \
    --arg actor_id "${praxis_actor_id}" \
    --arg correlation_id "${praxis_correlation_id}" \
    --arg marker "${praxis_prompt_marker}" \
    --argjson prompt_limit "${praxis_prompt_limit_characters}" \
    '{
      version: "2.0",
      routeKey: "POST /v1/sessions",
      headers: {
        "content-type": "application/json",
        "x-correlation-id": $correlation_id
      },
      isBase64Encoded: false,
      requestContext: {
        requestId: "MqgCjHCKoAMEPLw=",
        authorizer: {jwt: {claims: {sub: $actor_id}}}
      },
      body: ({goal: ($marker + ("x" * ($prompt_limit + 1 - ($marker | length))))} | tojson)
    }'
)"
praxis_prompt_characters="$(jq -r '.body | fromjson | .goal | length' <<<"${praxis_prompt_payload}")"
if ((praxis_prompt_characters != praxis_prompt_limit_characters + 1)); then
  printf 'Smoke prompt was not exactly one character above the %d-character limit.\n' \
    "${praxis_prompt_limit_characters}" >&2
  exit 1
fi

aws --profile "${praxis_profile}" --region "${praxis_region}" lambda invoke \
  --function-name "${praxis_function_name}" \
  --cli-binary-format raw-in-base64-out \
  --payload "${praxis_prompt_payload}" \
  "${praxis_build_dir}/api-prompt-smoke-response.json" \
  --output json >"${praxis_build_dir}/api-prompt-smoke-metadata.json"

praxis_prompt_function_error="$(
  jq -r '.FunctionError // empty' "${praxis_build_dir}/api-prompt-smoke-metadata.json"
)"
if [[ -n "${praxis_prompt_function_error}" ]]; then
  printf 'API Lambda failed (%s):\n' "${praxis_prompt_function_error}" >&2
  jq . "${praxis_build_dir}/api-prompt-smoke-response.json" >&2
  exit 1
fi

if ! jq -e \
  --arg correlation_id "${praxis_correlation_id}" \
  --arg marker "${praxis_prompt_marker}" \
  '.statusCode == 400
    and .headers["cache-control"] == "no-store"
    and .headers["content-type"] == "application/json"
    and .headers["x-correlation-id"] == $correlation_id
    and .isBase64Encoded == false
    and ((.body | fromjson) == {
      error: {
        code: "invalid_request",
        message: "Invalid request."
      }
    })
    and (.body | contains($marker) | not)' \
  "${praxis_build_dir}/api-prompt-smoke-response.json" >/dev/null; then
  printf 'API Lambda returned an unexpected oversized-prompt response:\n' >&2
  jq . "${praxis_build_dir}/api-prompt-smoke-response.json" >&2
  exit 1
fi

jq -n \
  --argjson body_limit "${praxis_body_limit_bytes}" \
  --argjson prompt_limit "${praxis_prompt_limit_characters}" \
  '{body_limit_bytes: $body_limit, oversized_body_status: 413, oversized_prompt_status: 400, prompt_limit_characters: $prompt_limit, runtime_invoked: false, simulated_authorizer_context: true}' \
  >"${praxis_evidence_dir}/api-payload-limits.json"
jq . "${praxis_evidence_dir}/api-payload-limits.json"
