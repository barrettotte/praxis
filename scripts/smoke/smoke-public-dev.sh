#!/usr/bin/env bash
# Check browser delivery and anonymous access boundaries without submitting a valid goal.
set -euo pipefail
umask 077
praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_require_commands curl "${praxis_tofu}"
praxis_work_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_work_dir}"' EXIT
praxis_frontend="$(praxis_tofu_output frontend_url)"
praxis_api="$(praxis_tofu_output api_gateway_url)"
praxis_bucket="$(praxis_tofu_output frontend_bucket_name)"

request() {
  curl --silent --show-error --max-time 20 \
    --dump-header "${praxis_work_dir}/headers" --output "${praxis_work_dir}/body" \
    --write-out '%{http_code}' "$@"
}
header() {
  awk -v name="$1" 'tolower($1) == name ":" {$1=""; sub(/^ /, ""); gsub("\r", ""); print}' \
    "${praxis_work_dir}/headers" | tail -n 1
}
fail() { printf '%s\n' "$1" >&2; exit 1; }

for praxis_path in / /__praxis_spa_smoke__; do
  [[ "$(request "${praxis_frontend%/}${praxis_path}")" == 200 ]] || fail 'Frontend delivery failed.'
  grep -q '<div id="root"></div>' "${praxis_work_dir}/body" || fail 'Application shell is missing.'
done
# Request the same object through S3 directly; the public edge must not imply a public origin.
[[ "$(request "https://${praxis_bucket}.s3.${praxis_region}.amazonaws.com/index.html")" == 403 ]] || \
  fail 'S3 origin did not reject anonymous access.'

# An invalid body avoids queued work even if the authorizer is misconfigured.
[[ "$(request --request POST --header 'content-type: application/json' --data '{}' \
  "${praxis_api%/}/v1/sessions")" == 401 ]] || fail 'API did not reject anonymous access.'

praxis_status="$(request --request OPTIONS --header "origin: ${praxis_frontend%/}" \
  --header 'access-control-request-method: POST' \
  --header 'access-control-request-headers: authorization,content-type,x-correlation-id' \
  "${praxis_api%/}/v1/sessions")"
[[ "${praxis_status}" == 200 || "${praxis_status}" == 204 ]] || fail 'CORS preflight failed.'
[[ "$(header access-control-allow-origin)" == "${praxis_frontend%/}" ]] || fail 'CORS origin mismatch.'
praxis_methods=",$(header access-control-allow-methods | tr '[:upper:]' '[:lower:]' | tr -d ' '),"
[[ "${praxis_methods}" == *",post,"* ]] || fail 'CORS does not allow POST.'
praxis_headers=",$(header access-control-allow-headers | tr '[:upper:]' '[:lower:]' | tr -d ' '),"
for praxis_header in authorization content-type x-correlation-id; do
  [[ "${praxis_headers}" == *",${praxis_header},"* ]] || fail "CORS does not allow ${praxis_header}."
done
request --request OPTIONS --header 'origin: https://not-praxis.invalid' \
  --header 'access-control-request-method: POST' "${praxis_api%/}/v1/sessions" >/dev/null
[[ -z "$(header access-control-allow-origin)" ]] || fail 'CORS permits an unconfigured origin.'
printf 'Frontend delivery, private origin, anonymous API rejection, and CORS checks passed.\n'
