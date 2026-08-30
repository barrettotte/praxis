#!/usr/bin/env bash
# Verify the deployed session route declares the reviewed API Gateway limits.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_route="POST /v1/sessions"

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

if ! jq -e --arg route "${praxis_route}" '
  .[$route].ThrottlingBurstLimit == 1
  and .[$route].ThrottlingRateLimit == 0.1
' <<<"${praxis_route_settings}" >/dev/null; then
  printf 'Deployed session-route throttling does not match the reviewed limits:\n' >&2
  jq . <<<"${praxis_route_settings}" >&2
  exit 1
fi

mkdir -p "${praxis_evidence_dir}"
jq -n --arg route "${praxis_route}" \
  '{configured: true, route: $route, throttling_burst_limit: 1, throttling_rate_limit_rps: 0.1}' \
  >"${praxis_evidence_dir}/api-throttling.json"
jq . "${praxis_evidence_dir}/api-throttling.json"
