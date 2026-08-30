#!/usr/bin/env bash
# Verify the deployed catalog Lambda can retrieve a known ingested evidence record.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_expected_title="LLVM Code Generation A Deep Dive Into Compiler Backend Development"

praxis_require_commands aws jq "${praxis_tofu}"

# Keep transport metadata separate from the Lambda application response.
mkdir -p "${praxis_build_dir}"
praxis_function_name="$(praxis_tofu_output catalog_lambda_name)"
aws --profile "${praxis_profile}" --region "${praxis_region}" lambda invoke \
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
