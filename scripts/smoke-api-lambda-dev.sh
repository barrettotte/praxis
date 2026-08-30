#!/usr/bin/env bash
# Verify the private API Lambda returns buffered Runtime-backed candidates.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"
praxis_build_dir="${praxis_repo_root}/build"
praxis_evidence_dir="${praxis_repo_root}/docs/evidence"
praxis_goal="compiler"
praxis_correlation_id="51f4a405-8835-411d-9821-5980d73f51f6"

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
  jq -nc \
    --arg correlation_id "${praxis_correlation_id}" \
    --arg goal "${praxis_goal}" \
    '{
      version: "2.0",
      routeKey: "POST /v1/sessions",
      headers: {
        "content-type": "application/json",
        "x-correlation-id": $correlation_id
      },
      isBase64Encoded: false,
      requestContext: {requestId: "MqgCjHCKoAMEPLw="},
      body: ({goal: $goal} | tojson)
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

# Require the public envelope and three evidence-backed Runtime candidates.
if ! jq -e \
  --arg correlation_id "${praxis_correlation_id}" \
  '.statusCode == 201
    and .headers["cache-control"] == "no-store"
    and .headers["content-type"] == "application/json"
    and .headers["x-correlation-id"] == $correlation_id
    and .isBase64Encoded == false
    and ((.body | fromjson) as $body
      | ($body.data.sessionId
          | test("^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"))
        and ($body.data.candidates | length == 3)
        and all($body.data.candidates[];
          (.evidence_citations | length >= 1)
          and all(.evidence_citations[];
            .evidence_id
            | test("^(book|byte|museum|project):[0-9a-f]{16}$"))))' \
  "${praxis_build_dir}/api-lambda-smoke-response.json" >/dev/null; then
  printf 'API Lambda returned an unexpected response:\n' >&2
  jq . "${praxis_build_dir}/api-lambda-smoke-response.json" >&2
  exit 1
fi

jq -n \
  '{all_candidates_cited: true, authenticated_direct_invocation: true, buffered_response: true, candidate_count: 3, correlation_id_propagated: true, handler_status: 201, runtime_invoked: true}' \
  >"${praxis_evidence_dir}/api-lambda.json"
jq . "${praxis_evidence_dir}/api-lambda.json"
