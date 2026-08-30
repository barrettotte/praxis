#!/usr/bin/env bash
# Verify the deployed private API Lambda returns its safe unavailable response.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"
praxis_build_dir="${praxis_repo_root}/build"
praxis_evidence_dir="${praxis_repo_root}/docs/evidence"
praxis_marker="untrusted-api-smoke-marker"

for praxis_command in aws jq "${praxis_tofu}"; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

# Keep transport metadata separate from the Lambda application response.
mkdir -p "${praxis_build_dir}" "${praxis_evidence_dir}"
praxis_function_name="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw api_lambda_name
)"
praxis_payload="$(
  jq -nc --arg marker "${praxis_marker}" \
    '{
      version: "2.0",
      routeKey: "POST /v1/sessions",
      headers: {"content-type": "application/json"},
      isBase64Encoded: false,
      body: ({goal: $marker} | tojson)
    }'
)"
aws --profile "${praxis_profile}" --region us-east-1 lambda invoke \
  --function-name "${praxis_function_name}" \
  --cli-binary-format raw-in-base64-out \
  --payload "${praxis_payload}" \
  "${praxis_build_dir}/api-lambda-smoke-response.json" \
  --output json >"${praxis_build_dir}/api-lambda-smoke-metadata.json"

praxis_function_error="$(
  jq -r '.FunctionError // empty' "${praxis_build_dir}/api-lambda-smoke-metadata.json"
)"
if [[ -n "${praxis_function_error}" ]]; then
  printf 'API Lambda failed (%s):\n' "${praxis_function_error}" >&2
  jq . "${praxis_build_dir}/api-lambda-smoke-response.json" >&2
  exit 1
fi

# Require the fixed response and prove the untrusted event was not reflected.
if ! jq -e --arg marker "${praxis_marker}" \
  '.statusCode == 503
    and .headers["cache-control"] == "no-store"
    and .headers["content-type"] == "application/json"
    and (.body | contains($marker) | not)' \
  "${praxis_build_dir}/api-lambda-smoke-response.json" >/dev/null; then
  printf 'API Lambda returned an unexpected response:\n' >&2
  jq . "${praxis_build_dir}/api-lambda-smoke-response.json" >&2
  exit 1
fi

jq -n \
  '{authenticated_direct_invocation: true, handler_status: 503, payload_reflected: false}' \
  >"${praxis_evidence_dir}/api-lambda.json"
jq . "${praxis_evidence_dir}/api-lambda.json"
