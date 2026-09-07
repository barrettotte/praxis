#!/usr/bin/env bash
# Dispatch bounded deployment checks; only api and runtime invoke a model.
set -euo pipefail
praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-public}" in
  public) exec "${praxis_script_dir}/smoke-public-dev.sh" ;;
  api) exec "${praxis_script_dir}/smoke-api-gateway-dev.sh" ;;
  tools) exec "${praxis_script_dir}/smoke-gateway-dev.sh" ;;
  runtime) exec "${praxis_script_dir}/smoke-runtime-dev.sh" ;;
  help|--help|-h)
    printf '%s\n' \
      'Usage: make smoke-dev [SUITE=public|api|tools|runtime]' \
      'public: frontend, private origin, anonymous API rejection, and CORS; no inference' \
      'api: authenticated recommendation and brief; metered, requires PRAXIS_ACCESS_TOKEN' \
      'tools: Gateway discovery and catalog round trip; no inference' \
      'runtime: direct signed invocation; metered, optional VERIFY_RUNTIME_TRACES=true' \
      'Local container: make smoke-agent-container'
    ;;
  *) printf 'Unknown smoke suite: %s\n' "$1" >&2; exit 2 ;;
esac
