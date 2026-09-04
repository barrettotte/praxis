#!/usr/bin/env bash
# Verify the private API and queued worker return buffered Runtime-backed candidates.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_goal="compiler"
praxis_correlation_id="51f4a405-8835-411d-9821-5980d73f51f6"
praxis_actor_id="7b9db85b-9448-4a41-9bb7-235a461429ae"
praxis_foreign_actor_id="945e3fcc-6522-4e07-920d-115a097df1c8"

praxis_require_commands aws jq "${praxis_tofu}"

# Keep transport metadata separate from the Lambda application response.
mkdir -p "${praxis_build_dir}" "${praxis_evidence_dir}"
praxis_function_name="$(praxis_tofu_output api_lambda_name)"
praxis_payload="$(
  jq -nc \
    --arg correlation_id "${praxis_correlation_id}" \
    --arg actor_id "${praxis_actor_id}" \
    --arg goal "${praxis_goal}" \
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
      body: ({goal: $goal} | tojson)
    }'
)"
aws --profile "${praxis_profile}" --region "${praxis_region}" lambda invoke \
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

# Require immediate acceptance without model output in the request path.
if ! jq -e \
  --arg correlation_id "${praxis_correlation_id}" \
  '.statusCode == 202
    and .headers["cache-control"] == "no-store"
    and .headers["content-type"] == "application/json"
    and .headers["x-correlation-id"] == $correlation_id
    and .isBase64Encoded == false
    and ((.body | fromjson) as $body
      | $body.data.status == "pending"
        and ($body.data | keys | sort == ["sessionId", "status"])
        and ($body.data.sessionId
          | test("^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")))' \
  "${praxis_build_dir}/api-lambda-smoke-response.json" >/dev/null; then
  printf 'API Lambda did not accept the asynchronous session:\n' >&2
  jq . "${praxis_build_dir}/api-lambda-smoke-response.json" >&2
  exit 1
fi

praxis_session_id="$(jq -r '.body | fromjson | .data.sessionId' \
  "${praxis_build_dir}/api-lambda-smoke-response.json")"

# Poll the authenticated status handler until the worker completes the session.
praxis_status_payload="$(
  jq -nc \
    --arg correlation_id "${praxis_correlation_id}" \
    --arg actor_id "${praxis_actor_id}" \
    --arg session_id "${praxis_session_id}" \
    '{
      version: "2.0",
      routeKey: "GET /v1/sessions/{sessionId}",
      headers: {"x-correlation-id": $correlation_id},
      isBase64Encoded: false,
      pathParameters: {sessionId: $session_id},
      requestContext: {
        requestId: "MqgCjHCKoAMEPLw=",
        authorizer: {jwt: {claims: {sub: $actor_id}}}
      }
    }'
)"
praxis_status_deadline=$((SECONDS + 120))
while true; do
  aws --profile "${praxis_profile}" --region "${praxis_region}" lambda invoke \
    --function-name "${praxis_function_name}" \
    --cli-binary-format raw-in-base64-out \
    --payload "${praxis_status_payload}" \
    "${praxis_build_dir}/api-lambda-session-response.json" \
    --output json >"${praxis_build_dir}/api-lambda-session-metadata.json"
  praxis_session_function_error="$(
    jq -r '.FunctionError // empty' "${praxis_build_dir}/api-lambda-session-metadata.json"
  )"
  if [[ -n "${praxis_session_function_error}" ]]; then
    printf 'API Lambda session lookup failed (%s):\n' "${praxis_session_function_error}" >&2
    jq . "${praxis_build_dir}/api-lambda-session-response.json" >&2
    exit 1
  fi
  praxis_session_status="$(
    jq -r 'if .statusCode == 200 then (.body | fromjson | .data.status) else "http-error" end' \
      "${praxis_build_dir}/api-lambda-session-response.json"
  )"
  if [[ "${praxis_session_status}" == "ready" ]]; then
    break
  fi
  if [[ "${praxis_session_status}" != "pending" ]] || ((SECONDS >= praxis_status_deadline)); then
    printf 'Recommendation session ended with status %s before candidates were ready:\n' \
      "${praxis_session_status}" >&2
    jq . "${praxis_build_dir}/api-lambda-session-response.json" >&2
    exit 1
  fi
  sleep 2
done

# Require three candidates whose citations resolve to the returned evidence.
if ! jq -e \
  --arg session_id "${praxis_session_id}" \
  '.statusCode == 200
    and ((.body | fromjson).data as $data
      | ($data.evidence | map(.evidence_id)) as $evidence_ids
      | $data.status == "ready"
        and $data.sessionId == $session_id
        and ($data.candidates | length == 3)
        and ([ $data.candidates[].candidateId ]
          == ["candidate_1", "candidate_2", "candidate_3"])
        and ($data.evidence | length >= 1 and length <= 3)
        and all($data.evidence[];
          (.evidence_id | test("^(book|byte|museum|project):[0-9a-f]{16}$"))
          and (.score == null))
        and all($data.candidates[];
          (.evidence_citations | length >= 1)
          and all(.evidence_citations[];
            (.evidence_id | test("^(book|byte|museum|project):[0-9a-f]{16}$"))
            and (.evidence_id as $id | $evidence_ids | index($id) != null))))' \
  "${praxis_build_dir}/api-lambda-session-response.json" >/dev/null; then
  printf 'Ready recommendation session returned invalid candidates:\n' >&2
  jq . "${praxis_build_dir}/api-lambda-session-response.json" >&2
  exit 1
fi

# A different authenticated subject must see the session as absent.
praxis_foreign_status_payload="$(
  jq -c --arg actor_id "${praxis_foreign_actor_id}" \
    '.requestContext.authorizer.jwt.claims.sub = $actor_id' \
    <<<"${praxis_status_payload}"
)"
aws --profile "${praxis_profile}" --region "${praxis_region}" lambda invoke \
  --function-name "${praxis_function_name}" \
  --cli-binary-format raw-in-base64-out \
  --payload "${praxis_foreign_status_payload}" \
  "${praxis_build_dir}/api-lambda-foreign-status-response.json" \
  --output json >"${praxis_build_dir}/api-lambda-foreign-status-metadata.json"
if ! jq -e '
  .statusCode == 404
  and ((.body | fromjson) == {
    error: {
      code: "not_found",
      message: "Requested recommendation session was not found."
    }
  })
' "${praxis_build_dir}/api-lambda-foreign-status-response.json" >/dev/null; then
  printf 'API Lambda exposed a recommendation session across actor boundaries:\n' >&2
  jq . "${praxis_build_dir}/api-lambda-foreign-status-response.json" >&2
  exit 1
fi

# Expand the first server-stored candidate through the same Lambda boundary.
praxis_candidate_id="candidate_1"
praxis_selection_payload="$(
  jq -nc \
    --arg candidate_id "${praxis_candidate_id}" \
    --arg correlation_id "${praxis_correlation_id}" \
    --arg actor_id "${praxis_actor_id}" \
    --arg session_id "${praxis_session_id}" \
    '{
      version: "2.0",
      routeKey: "POST /v1/projects/{candidateId}/select",
      headers: {
        "content-type": "application/json",
        "x-correlation-id": $correlation_id
      },
      isBase64Encoded: false,
      pathParameters: {candidateId: $candidate_id},
      requestContext: {
        requestId: "MqgCjHCKoAMEPLw=",
        authorizer: {jwt: {claims: {sub: $actor_id}}}
      },
      body: ({sessionId: $session_id} | tojson)
    }'
)"

# Candidate expansion applies the same session-owner check before Runtime work.
praxis_foreign_selection_payload="$(
  jq -c --arg actor_id "${praxis_foreign_actor_id}" \
    '.requestContext.authorizer.jwt.claims.sub = $actor_id' \
    <<<"${praxis_selection_payload}"
)"
aws --profile "${praxis_profile}" --region "${praxis_region}" lambda invoke \
  --function-name "${praxis_function_name}" \
  --cli-binary-format raw-in-base64-out \
  --payload "${praxis_foreign_selection_payload}" \
  "${praxis_build_dir}/api-lambda-foreign-selection-response.json" \
  --output json >"${praxis_build_dir}/api-lambda-foreign-selection-metadata.json"
if ! jq -e '
  .statusCode == 404
  and ((.body | fromjson) == {
    error: {
      code: "not_found",
      message: "Requested recommendation session was not found."
    }
  })
' "${praxis_build_dir}/api-lambda-foreign-selection-response.json" >/dev/null; then
  printf 'API Lambda exposed candidate selection across actor boundaries:\n' >&2
  jq . "${praxis_build_dir}/api-lambda-foreign-selection-response.json" >&2
  exit 1
fi

aws --profile "${praxis_profile}" --region "${praxis_region}" lambda invoke \
  --function-name "${praxis_function_name}" \
  --cli-binary-format raw-in-base64-out \
  --payload "${praxis_selection_payload}" \
  "${praxis_build_dir}/api-lambda-selection-response.json" \
  --output json >"${praxis_build_dir}/api-lambda-selection-metadata.json"

praxis_selection_function_error="$(
  jq -r '.FunctionError // empty' "${praxis_build_dir}/api-lambda-selection-metadata.json"
)"
if [[ -n "${praxis_selection_function_error}" ]]; then
  printf 'API Lambda selection failed (%s):\n' "${praxis_selection_function_error}" >&2
  jq . "${praxis_build_dir}/api-lambda-selection-response.json" >&2
  exit 1
fi

if ! jq -e \
  --arg candidate_id "${praxis_candidate_id}" \
  --arg session_id "${praxis_session_id}" \
  '.statusCode == 200
    and ((.body | fromjson).data as $data
      | $data.sessionId == $session_id
      and $data.candidateId == $candidate_id
      and $data.candidate.candidateId == $candidate_id
      and ($data.brief.objective | length > 0)
      and ($data.brief.scope | length > 0)
      and ($data.brief.milestones | length >= 3 and length <= 5)
      and ($data.brief.risks | length >= 2 and length <= 4)
      and ($data.brief.acceptance_criteria | length >= 3 and length <= 6))' \
  "${praxis_build_dir}/api-lambda-selection-response.json" >/dev/null; then
  printf 'API Lambda selection returned an unexpected response:\n' >&2
  jq . "${praxis_build_dir}/api-lambda-selection-response.json" >&2
  exit 1
fi

jq -n \
  '{all_candidates_cited: true, asynchronous_session: true, brief_generated: true, buffered_response: true, candidate_count: 3, correlation_id_propagated: true, cross_actor_selection_rejected: true, cross_actor_status_rejected: true, handler_status: 202, jwt_subject_bound: true, runtime_invoked: true, selection_status: 200, server_authoritative_selection: true, simulated_authorizer_context: true, status_polling: true, supporting_evidence_resolved: true}' \
  >"${praxis_evidence_dir}/api-lambda.json"
jq . "${praxis_evidence_dir}/api-lambda.json"
