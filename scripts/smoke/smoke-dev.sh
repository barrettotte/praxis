#!/usr/bin/env bash
# Run a named deployed smoke suite while preserving cost and mutation boundaries.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
praxis_suite="${1:-${SUITE:-config}}"

show_usage() {
  cat <<'EOF'
Usage: make smoke-dev [SUITE=name]

Suites:
  config             Fast configuration and rejection checks; no model inference
  access-logs        Eventually consistent API access-log delivery; no model inference
  tools              Catalog Lambda and AgentCore Gateway tools; no model inference
  api                API Gateway end-to-end request; invokes the configured model
  agent              Local Strands agent through Gateway; invokes the configured model
  runtime            One signed Runtime request; invokes the configured model
  runtime-sessions   Runtime session-isolation check; invokes the configured model twice
  runtime-traces     Runtime request plus CloudWatch trace verification

Memory is intentionally separate: make smoke-memory-dev CONFIRM=smoke-memory-dev
EOF
}

run_check() {
  local praxis_name="$1"
  shift
  printf '\n==> %s\n' "${praxis_name}"
  "$@"
}

case "${praxis_suite}" in
  config)
    run_check "API CORS" "${praxis_script_dir}/smoke-api-cors-dev.sh"
    run_check "API payload limit" "${praxis_script_dir}/smoke-api-payload-dev.sh"
    run_check "API throttling" "${praxis_script_dir}/smoke-api-throttling-dev.sh"
    run_check "Cognito user pool" "${praxis_script_dir}/smoke-cognito-dev.sh"
    run_check "Runtime authorization" "${praxis_script_dir}/smoke-runtime-auth-dev.sh"
    ;;
  access-logs)
    run_check "API access logs" "${praxis_script_dir}/smoke-api-access-logs-dev.sh"
    ;;
  tools)
    run_check "Catalog Lambda" "${praxis_script_dir}/smoke-catalog-dev.sh"
    run_check "AgentCore Gateway tools" "${praxis_script_dir}/smoke-gateway-dev.sh"
    ;;
  api)
    run_check "Application API" "${praxis_script_dir}/smoke-api-gateway-dev.sh"
    ;;
  agent)
    run_check "Local agent through Gateway" "${praxis_script_dir}/smoke-agent-gateway-dev.sh"
    ;;
  runtime)
    run_check "AgentCore Runtime" "${praxis_script_dir}/smoke-runtime-dev.sh"
    ;;
  runtime-sessions)
    run_check "Runtime session isolation" \
      env VERIFY_SESSION_ISOLATION=true "${praxis_script_dir}/smoke-runtime-dev.sh"
    ;;
  runtime-traces)
    run_check "Runtime trace delivery" \
      env VERIFY_RUNTIME_TRACES=true "${praxis_script_dir}/smoke-runtime-dev.sh"
    ;;
  help | --help | -h)
    show_usage
    ;;
  *)
    printf 'Unknown smoke suite: %s\n\n' "${praxis_suite}" >&2
    show_usage >&2
    exit 2
    ;;
esac
