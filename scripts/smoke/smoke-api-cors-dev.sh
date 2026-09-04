#!/usr/bin/env bash
# Verify API Gateway permits only the configured frontend origin through CORS.
set -euo pipefail
umask 077

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_denied_origin="https://not-praxis.invalid"
praxis_work_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_work_dir}"' EXIT

praxis_require_commands aws curl jq "${praxis_tofu}"

praxis_api_id="$(praxis_tofu_output api_gateway_id)"
praxis_api_url="$(praxis_tofu_output api_gateway_url)"
praxis_frontend_origin="$(praxis_tofu_output frontend_url)"
praxis_frontend_origins="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -json frontend_origins
)"
praxis_api_url="${praxis_api_url%/}"
praxis_cors="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    apigatewayv2 get-api \
    --api-id "${praxis_api_id}" \
    --query CorsConfiguration \
    --output json
)"

# Match exact sets so wildcard origins, methods, or headers cannot slip in.
if ! jq -e --argjson origins "${praxis_frontend_origins}" '
  (.AllowOrigins | sort) == ($origins | sort)
  and (.AllowMethods | sort) == ["GET", "OPTIONS", "POST"]
  and (.AllowHeaders | sort) == ["authorization", "content-type", "x-correlation-id"]
  and (.ExposeHeaders | sort) == ["x-correlation-id"]
  and .MaxAge == 300
' <<<"${praxis_cors}" >/dev/null; then
  printf 'Deployed API CORS settings do not match the reviewed contract:\n' >&2
  jq . <<<"${praxis_cors}" >&2
  exit 1
fi

# API Gateway handles preflight directly, so neither probe can invoke Lambda.
praxis_allowed_status="$(
  curl --silent --show-error --max-time 15 \
    --dump-header "${praxis_work_dir}/allowed.headers" \
    --output "${praxis_work_dir}/allowed.body" \
    --write-out '%{http_code}' \
    --request OPTIONS \
    --header "origin: ${praxis_frontend_origin}" \
    --header 'access-control-request-method: POST' \
    --header 'access-control-request-headers: authorization,content-type,x-correlation-id' \
    "${praxis_api_url}/v1/sessions"
)"
praxis_allowed_origin="$(
  awk 'tolower($1) == "access-control-allow-origin:" {gsub("\r", "", $2); print $2}' \
    "${praxis_work_dir}/allowed.headers" | tail -n 1
)"
praxis_allowed_methods="$(
  awk 'tolower($1) == "access-control-allow-methods:" {$1 = ""; sub(/^ /, ""); gsub("\r", ""); print}' \
    "${praxis_work_dir}/allowed.headers" | tail -n 1 | tr '[:upper:]' '[:lower:]' | tr -d ' '
)"
praxis_allowed_headers="$(
  awk 'tolower($1) == "access-control-allow-headers:" {$1 = ""; sub(/^ /, ""); gsub("\r", ""); print}' \
    "${praxis_work_dir}/allowed.headers" | tail -n 1 | tr '[:upper:]' '[:lower:]' | tr -d ' '
)"
if [[ "${praxis_allowed_status}" != "200" && "${praxis_allowed_status}" != "204" ]] || \
  [[ "${praxis_allowed_origin}" != "${praxis_frontend_origin}" ]] || \
  [[ ",${praxis_allowed_methods}," != *",post,"* ]] || \
  [[ ",${praxis_allowed_headers}," != *",authorization,"* ]] || \
  [[ ",${praxis_allowed_headers}," != *",content-type,"* ]] || \
  [[ ",${praxis_allowed_headers}," != *",x-correlation-id,"* ]]; then
  printf 'Configured-origin preflight returned an unexpected response (HTTP %s).\n' \
    "${praxis_allowed_status}" >&2
  exit 1
fi

praxis_denied_status="$(
  curl --silent --show-error --max-time 15 \
    --dump-header "${praxis_work_dir}/denied.headers" \
    --output "${praxis_work_dir}/denied.body" \
    --write-out '%{http_code}' \
    --request OPTIONS \
    --header "origin: ${praxis_denied_origin}" \
    --header 'access-control-request-method: POST' \
    "${praxis_api_url}/v1/sessions"
)"
praxis_denied_allow_origin="$(
  awk 'tolower($1) == "access-control-allow-origin:" {gsub("\r", "", $2); print $2}' \
    "${praxis_work_dir}/denied.headers" | tail -n 1
)"
if [[ -n "${praxis_denied_allow_origin}" ]]; then
  printf 'Unconfigured origin received access-control-allow-origin (HTTP %s).\n' \
    "${praxis_denied_status}" >&2
  exit 1
fi

mkdir -p "${praxis_evidence_dir}"
jq -n --argjson origins "${praxis_frontend_origins}" '{
  allowed_origins: $origins,
  allowed_preflight: true,
  denied_origin_omitted: true,
  lambda_invoked: false,
  wildcard_origin: false
}' >"${praxis_evidence_dir}/api-cors.json"
jq . "${praxis_evidence_dir}/api-cors.json"
