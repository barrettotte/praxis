#!/usr/bin/env bash
# Verify the deployed catalog Lambda can retrieve a known ingested evidence record.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"
praxis_build_dir="${praxis_repo_root}/build"
praxis_expected_title="LLVM Code Generation A Deep Dive Into Compiler Backend Development"

for praxis_command in aws jq "${praxis_tofu}"; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

# Keep transport metadata separate from the Lambda application response.
mkdir -p "${praxis_build_dir}"
praxis_function_name="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw catalog_lambda_name
)"
aws --profile "${praxis_profile}" --region us-east-1 lambda invoke \
  --function-name "${praxis_function_name}" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"operation":"search_catalog","arguments":{"query":"LLVM Code Generation","kinds":["book"],"limit":3}}' \
  "${praxis_build_dir}/catalog-smoke-response.json" \
  --output json >"${praxis_build_dir}/catalog-smoke-metadata.json"

praxis_function_error="$(
  jq -r '.FunctionError // empty' "${praxis_build_dir}/catalog-smoke-metadata.json"
)"
if [[ -n "${praxis_function_error}" ]]; then
  printf 'Catalog Lambda failed (%s):\n' "${praxis_function_error}" >&2
  jq . "${praxis_build_dir}/catalog-smoke-response.json" >&2
  exit 1
fi

# Assert semantic content, not merely a successful Lambda transport response.
if ! jq -e --arg expected_title "${praxis_expected_title}" \
  '.operation == "search_catalog" and any(.results[]; .kind == "book" and .title == $expected_title)' \
  "${praxis_build_dir}/catalog-smoke-response.json" >/dev/null; then
  printf 'Catalog smoke response did not contain the expected ingested book:\n' >&2
  jq . "${praxis_build_dir}/catalog-smoke-response.json" >&2
  exit 1
fi

jq . "${praxis_build_dir}/catalog-smoke-response.json"
