#!/usr/bin/env bash
# Verify API Gateway writes privacy-safe structured access records to CloudWatch.
set -euo pipefail
umask 077

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"
praxis_evidence_dir="${praxis_repo_root}/docs/evidence"
praxis_route="GET /v1/sessions/{sessionId}"
praxis_session_id="6bc42ae4-cfac-4bf5-b3a7-a866bab17af4"
praxis_timeout_seconds="${API_ACCESS_LOG_TIMEOUT_SECONDS:-120}"
praxis_work_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_work_dir}"' EXIT

for praxis_command in aws curl jq "${praxis_tofu}"; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

praxis_api_id="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw api_gateway_id
)"
praxis_api_url="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw api_gateway_url
)"
praxis_log_group="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw api_gateway_access_log_group_name
)"
praxis_api_url="${praxis_api_url%/}"

praxis_stage_settings="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    apigatewayv2 get-stage \
    --api-id "${praxis_api_id}" \
    --stage-name '$default' \
    --query AccessLogSettings \
    --output json
)"
praxis_log_groups="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    logs describe-log-groups \
    --log-group-name-prefix "${praxis_log_group}" \
    --output json
)"
praxis_log_group_record="$(
  jq -c --arg name "${praxis_log_group}" \
    '.logGroups[] | select(.logGroupName == $name)' <<<"${praxis_log_groups}"
)"
praxis_expected_format="$(
  jq -nc '{
    http_method: "$context.httpMethod",
    integration_latency_ms: "$context.integration.latency",
    integration_request_id: "$context.integration.requestId",
    integration_status: "$context.integration.status",
    request_id: "$context.requestId",
    request_time_epoch_ms: "$context.requestTimeEpoch",
    response_latency_ms: "$context.responseLatency",
    response_length_bytes: "$context.responseLength",
    route_key: "$context.routeKey",
    status: "$context.status"
  }'
)"

# Require the exact reviewed destination, schema, and short development retention.
if [[ -z "${praxis_log_group_record}" ]] || \
  ! jq -e --argjson group "${praxis_log_group_record}" \
    --arg expected_format "${praxis_expected_format}" '
      .DestinationArn == $group.logGroupArn
      and ((.Format | fromjson) == ($expected_format | fromjson))
      and $group.retentionInDays == 7
    ' <<<"${praxis_stage_settings}" >/dev/null; then
  printf 'Deployed API access log settings do not match the reviewed contract.\n' >&2
  jq -n \
    --argjson stage "${praxis_stage_settings}" \
    --argjson group "${praxis_log_group_record:-null}" \
    '{stage: $stage, log_group: $group}' >&2
  exit 1
fi

printf 'Sending an unsigned declared-route request that cannot invoke Lambda...\n'
praxis_start_time_ms="$(($(date +%s) * 1000))"
praxis_status="$(
  curl --silent --show-error --max-time 15 \
    --dump-header "${praxis_work_dir}/response.headers" \
    --output "${praxis_work_dir}/response.json" \
    --write-out '%{http_code}' \
    "${praxis_api_url}/v1/sessions/${praxis_session_id}"
)"
praxis_request_id="$(
  awk '
    tolower($1) == "apigw-requestid:" || tolower($1) == "x-amzn-requestid:" {
      gsub("\r", "", $2)
      print $2
    }
  ' "${praxis_work_dir}/response.headers" | tail -n 1
)"
if [[ "${praxis_status}" != "403" ]] || [[ -z "${praxis_request_id}" ]]; then
  printf 'Unsigned access-log probe returned HTTP %s without a request ID.\n' \
    "${praxis_status}" >&2
  exit 1
fi

# CloudWatch delivery is asynchronous, so poll only for this request identifier.
printf 'Waiting up to %s seconds for the matching access record in CloudWatch...\n' \
  "${praxis_timeout_seconds}"
praxis_deadline=$((SECONDS + praxis_timeout_seconds))
praxis_delivery_verified=false
while ((SECONDS < praxis_deadline)); do
  praxis_events="$(
    aws --profile "${praxis_profile}" --region "${praxis_region}" \
      logs filter-log-events \
      --log-group-name "${praxis_log_group}" \
      --start-time "${praxis_start_time_ms}" \
      --limit 100 \
      --output json
  )"
  if jq -e --arg request_id "${praxis_request_id}" --arg route "${praxis_route}" '
    any(.events[]?;
      ((try (.message | fromjson) catch {}) as $entry
        | $entry.request_id == $request_id
        and $entry.http_method == "GET"
        and $entry.route_key == $route
        and $entry.status == "403"
        and (($entry | keys | sort) == [
          "http_method",
          "integration_latency_ms",
          "integration_request_id",
          "integration_status",
          "request_id",
          "request_time_epoch_ms",
          "response_latency_ms",
          "response_length_bytes",
          "route_key",
          "status"
        ])))
  ' <<<"${praxis_events}" >/dev/null; then
    praxis_delivery_verified=true
    break
  fi
  sleep 5
done

if [[ "${praxis_delivery_verified}" != true ]]; then
  printf 'No matching privacy-safe API access record appeared within %s seconds.\n' \
    "${praxis_timeout_seconds}" >&2
  exit 1
fi

mkdir -p "${praxis_evidence_dir}"
jq -n '{
  access_log_delivery: true,
  fields: [
    "http_method",
    "integration_latency_ms",
    "integration_request_id",
    "integration_status",
    "request_id",
    "request_time_epoch_ms",
    "response_latency_ms",
    "response_length_bytes",
    "route_key",
    "status"
  ],
  retention_days: 7,
  unauthorized_probe_status: 403
}' >"${praxis_evidence_dir}/api-access-logs.json"
jq . "${praxis_evidence_dir}/api-access-logs.json"
