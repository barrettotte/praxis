#!/usr/bin/env bash
# Build the reproducible Python 3.13 deployment ZIP for the API Lambda.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_artifact_dir="${praxis_repo_root}/build/lambda"
praxis_artifact="${praxis_artifact_dir}/praxis-api.zip"
praxis_package_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_package_dir}"' EXIT

mkdir -p "${praxis_artifact_dir}" "${praxis_package_dir}/package/praxis/functions"

# Install locked manylinux validation dependencies for Lambda.
UV_CACHE_DIR="${praxis_repo_root}/.cache/uv" uv pip install \
  --python 3.13 \
  --python-platform x86_64-manylinux2014 \
  --link-mode copy \
  --require-hashes \
  --target "${praxis_package_dir}/package" \
  --requirement "${praxis_repo_root}/backend/lambda/requirements.lock"

# Include the API handler and its shared validation contracts without other Lambda handlers.
cp "${praxis_repo_root}/backend/src/praxis/__init__.py" "${praxis_package_dir}/package/praxis/"
cp "${praxis_repo_root}/backend/src/praxis/py.typed" "${praxis_package_dir}/package/praxis/"
cp -R "${praxis_repo_root}/backend/src/praxis/api" "${praxis_package_dir}/package/praxis/"
cp -R "${praxis_repo_root}/backend/src/praxis/catalog" "${praxis_package_dir}/package/praxis/"
cp -R "${praxis_repo_root}/backend/src/praxis/domain" "${praxis_package_dir}/package/praxis/"
cp -R "${praxis_repo_root}/backend/src/praxis/tools" "${praxis_package_dir}/package/praxis/"
cp "${praxis_repo_root}/backend/src/praxis/functions/__init__.py" \
  "${praxis_package_dir}/package/praxis/functions/"
cp "${praxis_repo_root}/backend/src/praxis/functions/api.py" \
  "${praxis_package_dir}/package/praxis/functions/"
cp "${praxis_repo_root}/backend/src/praxis/functions/recommendation_worker.py" \
  "${praxis_package_dir}/package/praxis/functions/"

# Catch missing transitive application modules before publishing the ZIP.
PYTHONPATH="${praxis_package_dir}/package" uv run --frozen python -c \
  'import praxis.functions.api; import praxis.functions.recommendation_worker'

# Normalize contents, timestamps, ordering, and ZIP metadata for a stable hash.
find "${praxis_package_dir}/package" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${praxis_package_dir}/package" -type f -exec touch -t 198001010000 {} +
rm -f "${praxis_artifact}"
(
  cd "${praxis_package_dir}/package"
  find . -type f -print | LC_ALL=C sort | zip -X -q "${praxis_artifact}" -@
)

printf 'Created %s\n' "${praxis_artifact}"
