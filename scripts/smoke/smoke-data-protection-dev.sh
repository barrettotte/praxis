#!/usr/bin/env bash
# Verify deployed storage encryption and finite application log retention.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"

praxis_require_commands aws jq "${praxis_tofu}"

praxis_source_bucket="$(praxis_tofu_output source_data_bucket_name)"
praxis_frontend_bucket="$(praxis_tofu_output frontend_bucket_name)"
for praxis_bucket in "${praxis_source_bucket}" "${praxis_frontend_bucket}"; do
  praxis_algorithm="$(
    aws --profile "${praxis_profile}" --region "${praxis_region}" \
      s3api get-bucket-encryption --bucket "${praxis_bucket}" \
      --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' \
      --output text
  )"
  if [[ "${praxis_algorithm}" != "AES256" ]]; then
    printf 'S3 bucket does not use the reviewed encryption: %s\n' "${praxis_bucket}" >&2
    exit 1
  fi
done

praxis_catalog_table="$(praxis_tofu_output catalog_table_name)"
praxis_session_table="$(praxis_tofu_output api_session_table_name)"
for praxis_table in "${praxis_catalog_table}" "${praxis_session_table}"; do
  praxis_sse_status="$(
    aws --profile "${praxis_profile}" --region "${praxis_region}" \
      dynamodb describe-table --table-name "${praxis_table}" \
      --query 'Table.SSEDescription.Status' --output text
  )"
  if [[ "${praxis_sse_status}" != "ENABLED" ]]; then
    printf 'DynamoDB table encryption is not enabled: %s\n' "${praxis_table}" >&2
    exit 1
  fi
done

praxis_queue_names="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -json recommendation_queue_names
)"
while IFS= read -r praxis_queue_name; do
  praxis_queue_url="$(
    aws --profile "${praxis_profile}" --region "${praxis_region}" \
      sqs get-queue-url --queue-name "${praxis_queue_name}" \
      --query QueueUrl --output text
  )"
  praxis_sse_enabled="$(
    aws --profile "${praxis_profile}" --region "${praxis_region}" \
      sqs get-queue-attributes --queue-url "${praxis_queue_url}" \
      --attribute-names SqsManagedSseEnabled \
      --query 'Attributes.SqsManagedSseEnabled' --output text
  )"
  if [[ "${praxis_sse_enabled}" != "true" ]]; then
    printf 'SQS managed encryption is not enabled: %s\n' "${praxis_queue_name}" >&2
    exit 1
  fi
done < <(jq -er '.[]' <<<"${praxis_queue_names}")

praxis_repository_url="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -json ecr_repository_urls |
    jq -er '.agent'
)"
praxis_repository_name="${praxis_repository_url##*/}"
praxis_ecr_encryption="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    ecr describe-repositories --repository-names "${praxis_repository_name}" \
    --query 'repositories[0].encryptionConfiguration.encryptionType' --output text
)"
if [[ "${praxis_ecr_encryption}" != "AES256" ]]; then
  printf 'ECR repository does not use the reviewed encryption.\n' >&2
  exit 1
fi

# CloudWatch encrypts every log group; require finite retention on project-owned groups.
praxis_expected_log_groups="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -json application_log_group_names
)"
praxis_log_groups="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    logs describe-log-groups --query logGroups --output json
)"
if ! jq -e --argjson expected "${praxis_expected_log_groups}" '
  . as $actual |
  all($expected[];
    . as $name |
    any($actual[]; .logGroupName == $name and .retentionInDays == 7))
' <<<"${praxis_log_groups}" >/dev/null; then
  printf 'A project log group is missing or does not retain seven days.\n' >&2
  exit 1
fi

mkdir -p "${praxis_evidence_dir}"
jq -n --argjson log_group_count "$(jq 'length' <<<"${praxis_expected_log_groups}")" '{
  encryption_at_rest: {
    agentcore: "AWS-owned keys",
    cloudwatch_logs: "service-managed AES-256-GCM",
    dynamodb: "enabled",
    ecr: "AES256",
    s3: "AES256",
    sqs: "SQS-managed"
  },
  log_group_count: $log_group_count,
  log_retention_days: 7
}' >"${praxis_evidence_dir}/data-protection.json"
jq . "${praxis_evidence_dir}/data-protection.json"
