#!/usr/bin/env bash
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_tofu="${TOFU:-tofu}"
praxis_source_data_dir="${SOURCE_DATA_DIR:-${praxis_repo_root}/../barrettotte.github.io/data}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"
praxis_build_dir="${praxis_repo_root}/build"

if [[ "${CONFIRM:-}" != "seed-dev" ]]; then
  printf 'CONFIRM=seed-dev is required\n' >&2
  exit 2
fi

for praxis_command in aws jq "${praxis_tofu}"; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

praxis_source_files=(books.json projects.json bytes.json museum.json)
for praxis_source_file in "${praxis_source_files[@]}"; do
  if [[ ! -f "${praxis_source_data_dir}/${praxis_source_file}" ]]; then
    printf 'Missing %s/%s\n' "${praxis_source_data_dir}" "${praxis_source_file}" >&2
    exit 2
  fi
done

praxis_source_bucket="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw source_data_bucket_name
)"
for praxis_source_file in "${praxis_source_files[@]}"; do
  aws --profile "${praxis_profile}" --region us-east-1 s3 cp --only-show-errors \
    "${praxis_source_data_dir}/${praxis_source_file}" \
    "s3://${praxis_source_bucket}/${praxis_source_file}"
done
printf 'Uploaded four source files to the development bucket.\n'

mkdir -p "${praxis_build_dir}"
praxis_function_name="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw ingestion_lambda_name
)"
aws --profile "${praxis_profile}" --region us-east-1 lambda invoke \
  --function-name "${praxis_function_name}" \
  --cli-binary-format raw-in-base64-out \
  --payload '{}' \
  "${praxis_build_dir}/ingestion-response.json" \
  --output json >"${praxis_build_dir}/ingestion-metadata.json"

praxis_function_error="$(
  jq -r '.FunctionError // empty' "${praxis_build_dir}/ingestion-metadata.json"
)"
if [[ -n "${praxis_function_error}" ]]; then
  printf 'Ingestion Lambda failed (%s):\n' "${praxis_function_error}" >&2
  jq . "${praxis_build_dir}/ingestion-response.json" >&2
  exit 1
fi

jq . "${praxis_build_dir}/ingestion-response.json"
