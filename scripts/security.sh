#!/usr/bin/env bash
# Scan locked dependencies and a local Runtime image without AWS access or credentials.
set -euo pipefail
umask 077

praxis_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_container_tool="${CONTAINER_TOOL:-podman}"
praxis_mode="${1:-all}"
# Trivy 0.74.0, pinned to its multi-architecture image index.
praxis_scanner="docker.io/aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969"
# Grype 0.118.0 also inventories upstream CPython binaries outside dpkg ownership.
praxis_binary_scanner="docker.io/anchore/grype@sha256:8a93fc48da96bd6ec5981279d099b69de11541dc68fdf222fb9161f8ff284af7"
case "${praxis_mode}" in
  all | dependencies | image) ;;
  *) printf 'Usage: %s [all|dependencies|image]\n' "$0" >&2; exit 2 ;;
esac
command -v "${praxis_container_tool}" >/dev/null
# Bind mounts retain host ownership. Rootless Podman also needs matching namespace IDs.
praxis_identity=(--user "$(id -u):$(id -g)")
if [[ "${praxis_container_tool##*/}" == "podman" ]]; then
  praxis_identity+=(--userns=keep-id)
fi
praxis_work="$(mktemp -d)"
trap 'rm -rf "${praxis_work}"' EXIT
mkdir -p "${praxis_root}/build/security" "${praxis_root}/.cache/trivy" \
  "${praxis_root}/.cache/grype"

# Mount only scan inputs, reports, and the database cache: no repository, home,
# cloud credentials, container socket, or host environment is passed to Trivy.
scan() {
  "${praxis_container_tool}" run --rm --read-only --cap-drop=ALL \
    "${praxis_identity[@]}" \
    --security-opt=no-new-privileges --tmpfs /tmp:rw,mode=1777 \
    --volume "${praxis_work}:/scan:ro,Z" \
    --volume "${praxis_root}/build/security:/reports:Z" \
    --volume "${praxis_root}/.cache/trivy:/cache:Z" \
    "${praxis_scanner}" --cache-dir /cache "$@"
}

praxis_status=0
for praxis_scan in dependencies image; do
  if [[ "${praxis_mode}" != all && "${praxis_mode}" != "${praxis_scan}" ]]; then
    continue
  fi
  # A failed scan must not leave a previous report looking current.
  rm -f "${praxis_root}/build/security/${praxis_scan}.json"
  if [[ "${praxis_scan}" == dependencies ]]; then
    mkdir -p "${praxis_work}/locks/frontend" "${praxis_work}/locks/lambda"
    cp "${praxis_root}/uv.lock" "${praxis_work}/locks/"
    cp "${praxis_root}/frontend/package-lock.json" "${praxis_work}/locks/frontend/"
    # Trivy recognizes requirements.txt; the Lambda lock already pins transitives.
    cp "${praxis_root}/backend/lambda/requirements.lock" \
      "${praxis_work}/locks/lambda/requirements.txt"
    praxis_arguments=(fs --include-dev-deps /scan/locks)
  else
    rm -f "${praxis_root}/build/security/image-binaries.json"
    # Saving a local image avoids registry credentials and works without executing ARM64 code.
    "${praxis_container_tool}" image inspect "${AGENT_IMAGE:-praxis-agent:dev}" >/dev/null
    # Both Docker and Podman default to the Docker archive format.
    "${praxis_container_tool}" save \
      --output "${praxis_work}/agent.tar" "${AGENT_IMAGE:-praxis-agent:dev}"
    praxis_arguments=(image --input /scan/agent.tar)
  fi
  # Collect both reports even when one scan finds vulnerabilities. Tool/database
  # errors also fail the command; never suppress unfixed findings or use an allowlist.
  if ! scan "${praxis_arguments[@]}" --scanners vuln --severity HIGH,CRITICAL \
    --exit-code 1 --timeout 10m --no-progress --list-all-pkgs --format json \
    --output "/reports/${praxis_scan}.json"; then
    praxis_status=1
  fi
  printf 'Scan report: build/security/%s.json\n' "${praxis_scan}"
  if [[ -f "${praxis_root}/build/security/${praxis_scan}.json" ]]; then
    scan convert --format table "/reports/${praxis_scan}.json" || praxis_status=1
  fi
  [[ -s "${praxis_root}/build/security/${praxis_scan}.json" ]] || praxis_status=1
  if [[ "${praxis_scan}" == image ]]; then
    # A clean language-only result must not conceal missing OS detection or inventory.
    if ! jq -e '
      .Metadata.OS.Family == "ubuntu" and .Metadata.OS.Name == "24.04" and
      ([.Results[]? | select(.Class == "os-pkgs") | .Packages[]?.Name] |
        index("libc6") != null and index("zlib1g") != null)
    ' "${praxis_root}/build/security/image.json" >/dev/null; then
      printf 'Runtime OS/package inventory is missing or unexpected.\n' >&2
      praxis_status=1
    fi
    # Fixed scanner settings only; never forward the caller's environment.
    if ! "${praxis_container_tool}" run --rm --read-only --cap-drop=ALL \
      "${praxis_identity[@]}" --security-opt=no-new-privileges --tmpfs /tmp:rw,mode=1777 \
      --volume "${praxis_work}:/scan:ro,Z" \
      --volume "${praxis_root}/build/security:/reports:Z" \
      --volume "${praxis_root}/.cache/grype:/cache:Z" \
      --env GRYPE_DB_CACHE_DIR=/cache --env GRYPE_CHECK_FOR_APP_UPDATE=false \
      "${praxis_binary_scanner}" docker-archive:/scan/agent.tar \
      --fail-on high --output json --file /reports/image-binaries.json; then
      praxis_status=1
    fi
    printf 'Binary-aware scan report: build/security/image-binaries.json\n'
    [[ -s "${praxis_root}/build/security/image-binaries.json" ]] || praxis_status=1
  fi
done
exit "${praxis_status}"
