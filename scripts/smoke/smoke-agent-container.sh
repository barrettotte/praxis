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
  --network none \
  --read-only \
  --tmpfs /tmp \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  "${image}" >/dev/null

# Probe from inside the container so the smoke test needs no published host port.
for _ in {1..30}; do
  if response="$(
    "${container_tool}" exec "${container_name}" python -c \
      'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/ping", timeout=2).read().decode())' \
      2>/dev/null
  )"; then
    # Verify the serving identity and exclude installers and privilege-elevating files.
    "${container_tool}" exec "${container_name}" python -c '
import importlib.util
import os
import shutil
import stat
import sys
from pathlib import Path
assert sys.version_info[:2] == (3, 13)
assert os.geteuid() != 0
assert importlib.util.find_spec("pip") is None
# Debian retains ensurepip code but supplies no bootstrap wheels in distroless.
assert not list(Path("/usr").rglob("*.whl"))
assert not list(Path("/app").rglob("*.whl"))
assert not Path("/usr/local/lib/python3.13/site-packages/pip").exists()
assert shutil.which("uv") is None
assert shutil.which("uvx") is None
for utility in (
    "sh", "bash", "perl", "apt", "apt-get", "dpkg",
    "mount", "umount", "nsenter", "infocmp", "tic",
):
    assert shutil.which(utility) is None, utility
# Source-package advisories can name utilities absent from the library-only image.
# Check outside PATH too, including the mount library that implements mount hooks.
for root in (Path("/usr"), Path("/app")):
    for name in ("mount", "umount", "nsenter", "infocmp", "tic", "libmount.so*"):
        assert not list(root.rglob(name)), name
# Exercise native dependencies and telemetry imports without cloud calls.
import awscrt.auth
import grpc
import pydantic_core
import sqlite3
import ssl
import opentelemetry.instrumentation.auto_instrumentation
import praxis.agent.runtime
assert ssl.create_default_context().get_ca_certs()
assert sqlite3.connect(":memory:").execute("select 1").fetchone() == (1,)
assert not any(
    path.is_file() and path.stat().st_mode & (stat.S_ISUID | stat.S_ISGID)
    for path in Path("/usr").rglob("*")
)
'
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
