#!/usr/bin/env bash
# Build the dependency-free Python 3.13 deployment ZIP for the API Lambda.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_artifact_dir="${praxis_repo_root}/build/lambda"
praxis_artifact="${praxis_artifact_dir}/praxis-api.zip"
praxis_package_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_package_dir}"' EXIT

mkdir -p "${praxis_artifact_dir}" "${praxis_package_dir}/package/praxis/functions"

# Include only the API import path so unrelated Lambda code cannot affect its hash.
cp "${praxis_repo_root}/backend/src/praxis/__init__.py" "${praxis_package_dir}/package/praxis/"
cp "${praxis_repo_root}/backend/src/praxis/py.typed" "${praxis_package_dir}/package/praxis/"
cp "${praxis_repo_root}/backend/src/praxis/functions/__init__.py" \
  "${praxis_package_dir}/package/praxis/functions/"
cp "${praxis_repo_root}/backend/src/praxis/functions/api.py" \
  "${praxis_package_dir}/package/praxis/functions/"

# Normalize contents, timestamps, ordering, and ZIP metadata for a stable hash.
find "${praxis_package_dir}/package" -type f -exec touch -t 198001010000 {} +
rm -f "${praxis_artifact}"
(
  cd "${praxis_package_dir}/package"
  find . -type f -print | LC_ALL=C sort | zip -X -q "${praxis_artifact}" -@
)

printf 'Created %s\n' "${praxis_artifact}"
