#!/usr/bin/env bash
# Verify the packaged AgentCore container reaches its internal health endpoint.
set -euo pipefail

container_tool="${CONTAINER_TOOL:-podman}"
image="${AGENT_IMAGE:-praxis-agent:dev}"
platform="${AGENT_PLATFORM:-linux/arm64}"
container_name="praxis-agent-smoke-$$"

# Always remove the detached smoke container, including after failed health checks.
cleanup() {
  "${container_tool}" rm --force "${container_name}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${container_tool}" run \
  --detach \
  --name "${container_name}" \
  --platform "${platform}" \
  "${image}" >/dev/null

# Probe from inside the container so the smoke test needs no published host port.
for _ in {1..30}; do
  if response="$(
    "${container_tool}" exec "${container_name}" python -c \
      'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/ping", timeout=2).read().decode())' \
      2>/dev/null
  )"; then
    uv run python -c \
      'import json, sys; assert json.loads(sys.argv[1])["status"] == "Healthy"' \
      "${response}"
    printf '%s\n' "${response}"
    exit 0
  fi
  sleep 1
done

"${container_tool}" logs "${container_name}" >&2
printf 'Agent container did not become healthy on port 8080\n' >&2
exit 1
