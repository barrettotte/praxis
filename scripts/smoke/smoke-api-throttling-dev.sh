#!/usr/bin/env bash
# Verify deployed route throttles and Lambda execution timeouts.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_routes='["POST /v1/sessions", "POST /v1/projects/{candidateId}/select"]'

praxis_require_commands aws jq "${praxis_tofu}"

praxis_api_id="$(praxis_tofu_output api_gateway_id)"
praxis_route_settings="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    apigatewayv2 get-stage \
    --api-id "${praxis_api_id}" \
    --stage-name '$default' \
    --query RouteSettings \
    --output json
)"

if ! jq -e --argjson routes "${praxis_routes}" '
  . as $settings | all($routes[];
    $settings[.].ThrottlingBurstLimit == 1
    and $settings[.].ThrottlingRateLimit == 0.1)
' <<<"${praxis_route_settings}" >/dev/null; then
  printf 'Deployed route throttling does not match the reviewed limits:\n' >&2
  jq . <<<"${praxis_route_settings}" >&2
  exit 1
fi

# Read configuration only; never force timeouts or consume concurrency to test limits.
praxis_timeouts='{}'
for praxis_component in api:29 catalog:15 recommendation_worker:120; do
  praxis_name="${praxis_component%:*}"
  praxis_expected_timeout="${praxis_component#*:}"
  praxis_output_name="${praxis_name}_lambda_name"
  if [[ "${praxis_name}" == "recommendation_worker" ]]; then
    praxis_output_name="recommendation_worker_name"
  fi
  praxis_timeout="$(
    aws --profile "${praxis_profile}" --region "${praxis_region}" \
      lambda get-function-configuration \
      --function-name "$(praxis_tofu_output "${praxis_output_name}")" \
      --query Timeout --output text
  )"
  if [[ "${praxis_timeout}" != "${praxis_expected_timeout}" ]]; then
    printf 'Unexpected %s Lambda timeout: %s seconds\n' "${praxis_name}" "${praxis_timeout}" >&2
    exit 1
  fi
  praxis_timeouts="$(jq -c --arg name "${praxis_name}" --argjson timeout "${praxis_timeout}" \
    '. + {($name): $timeout}' <<<"${praxis_timeouts}")"
done

mkdir -p "${praxis_evidence_dir}"
jq -n --argjson routes "${praxis_routes}" --argjson timeouts "${praxis_timeouts}" \
  '{configured: true, verification: "read_only_configuration", routes: $routes, lambda_timeouts_seconds: $timeouts, throttling_burst_limit: 1, throttling_rate_limit_rps: 0.1}' \
  >"${praxis_evidence_dir}/api-throttling.json"
jq . "${praxis_evidence_dir}/api-throttling.json"
