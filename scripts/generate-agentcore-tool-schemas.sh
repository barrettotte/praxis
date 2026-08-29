#!/usr/bin/env bash
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_schema_path="${praxis_repo_root}/infra/schemas/agentcore-tools.json"
praxis_generated_path="$(mktemp)"
trap 'rm -f "${praxis_generated_path}"' EXIT

UV_CACHE_DIR="${praxis_repo_root}/.cache/uv" uv run --project "${praxis_repo_root}" \
  python -c 'from praxis.tools import gateway_tool_definitions_json; print(gateway_tool_definitions_json(), end="")' \
  >"${praxis_generated_path}"

case "${1:-write}" in
  write)
    mkdir -p "$(dirname "${praxis_schema_path}")"
    mv "${praxis_generated_path}" "${praxis_schema_path}"
    ;;
  --check)
    if ! cmp -s "${praxis_generated_path}" "${praxis_schema_path}"; then
      echo "AgentCore tool schema artifact is stale; run 'make tool-schemas'." >&2
      exit 1
    fi
    ;;
  *)
    echo "Usage: $0 [write|--check]" >&2
    exit 2
    ;;
esac
