#!/usr/bin/env bash
# Build a reproducible Lambda ZIP with an explicit handler profile and isolated imports.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
  api) praxis_handlers=(api recommendation_worker); praxis_extra_packages=(api) ;;
  functions) praxis_handlers=(catalog ingestion); praxis_extra_packages=() ;;
  *) printf 'Usage: %s api|functions\n' "$0" >&2; exit 2 ;;
esac
praxis_artifact="${praxis_repo_root}/build/lambda/praxis-${1}.zip"
praxis_package_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_package_dir}"' EXIT
praxis_source="${praxis_repo_root}/backend/src/praxis"
mkdir -p "${praxis_repo_root}/build/lambda" "${praxis_package_dir}/package/praxis/functions"
cp "${praxis_repo_root}/backend/lambda/collector.yaml" "${praxis_package_dir}/package/"

# Resolve only locked Lambda dependencies, not the host's agent environment.
UV_CACHE_DIR="${praxis_repo_root}/.cache/uv" uv pip install \
  --python 3.13 --python-platform x86_64-manylinux2014 --link-mode copy \
  --require-hashes --target "${praxis_package_dir}/package" \
  --requirement "${praxis_repo_root}/backend/lambda/requirements.lock"
cp "${praxis_source}/__init__.py" "${praxis_source}/py.typed" "${praxis_package_dir}/package/praxis/"
for praxis_module in catalog domain tools "${praxis_extra_packages[@]}"; do
  cp -R "${praxis_source}/${praxis_module}" "${praxis_package_dir}/package/praxis/"
done
for praxis_module in __init__ tracing "${praxis_handlers[@]}"; do
  cp "${praxis_source}/functions/${praxis_module}.py" "${praxis_package_dir}/package/praxis/functions/"
done

# -I -S prevents installed project/development packages from masking missing ZIP dependencies.
uv run --frozen python -I -S -c \
  'import importlib, sys; sys.path.insert(0, sys.argv[1]); [importlib.import_module("praxis.functions." + name) for name in sys.argv[2:]]' \
  "${praxis_package_dir}/package" "${praxis_handlers[@]}"

# Stable timestamps, ordering, and metadata avoid needless Lambda updates.
find "${praxis_package_dir}/package" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${praxis_package_dir}/package" -type f -exec touch -t 198001010000 {} +
(
  cd "${praxis_package_dir}/package"
  find . -type f -print | LC_ALL=C sort | zip -X -q "${praxis_package_dir}/artifact.zip" -@
)
mv "${praxis_package_dir}/artifact.zip" "${praxis_artifact}"
printf 'Created %s\n' "${praxis_artifact}"
