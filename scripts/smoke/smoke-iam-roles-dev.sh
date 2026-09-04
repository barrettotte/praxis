#!/usr/bin/env bash
# Verify deployed components retain distinct OpenTofu-owned execution roles.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"

praxis_require_commands aws jq "${praxis_tofu}"

praxis_expected_roles="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -json application_execution_role_arns
)"

# Read each component's active role from its service rather than trusting state alone.
praxis_api_role="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    lambda get-function-configuration \
    --function-name "$(praxis_tofu_output api_lambda_name)" \
    --query Role --output text
)"
praxis_worker_role="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    lambda get-function-configuration \
    --function-name "$(praxis_tofu_output recommendation_worker_name)" \
    --query Role --output text
)"
praxis_runtime_role="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id "$(praxis_tofu_output agentcore_runtime_id)" \
    --query roleArn --output text
)"
praxis_gateway_role="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    bedrock-agentcore-control get-gateway \
    --gateway-identifier "$(praxis_tofu_output agentcore_gateway_id)" \
    --query roleArn --output text
)"
praxis_catalog_role="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    lambda get-function-configuration \
    --function-name "$(praxis_tofu_output catalog_lambda_name)" \
    --query Role --output text
)"
praxis_ingestion_role="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    lambda get-function-configuration \
    --function-name "$(praxis_tofu_output ingestion_lambda_name)" \
    --query Role --output text
)"

praxis_actual_roles="$(
  jq -n \
    --arg api "${praxis_api_role}" \
    --arg worker "${praxis_worker_role}" \
    --arg runtime "${praxis_runtime_role}" \
    --arg gateway "${praxis_gateway_role}" \
    --arg catalog "${praxis_catalog_role}" \
    --arg ingestion "${praxis_ingestion_role}" \
    '{api: $api, worker: $worker, runtime: $runtime, gateway: $gateway, catalog: $catalog, ingestion: $ingestion}'
)"

if ! jq -e --argjson expected "${praxis_expected_roles}" '
  . == $expected and ([.[]] | length == (unique | length))
' <<<"${praxis_actual_roles}" >/dev/null; then
  printf 'Deployed execution roles are shared or differ from the OpenTofu contract.\n' >&2
  exit 1
fi

# Managed-policy attachments would bypass the reviewed inline-policy boundaries.
while IFS= read -r praxis_role_arn; do
  praxis_role_name="${praxis_role_arn##*/}"
  praxis_attached_count="$(
    aws --profile "${praxis_profile}" iam list-attached-role-policies \
      --role-name "${praxis_role_name}" \
      --query 'length(AttachedPolicies)' --output text
  )"
  if [[ "${praxis_attached_count}" != "0" ]]; then
    printf 'Execution role has an unmanaged policy attachment: %s\n' "${praxis_role_name}" >&2
    exit 1
  fi
done < <(jq -r '.[]' <<<"${praxis_actual_roles}")

mkdir -p "${praxis_evidence_dir}"
jq -n '{
  distinct_execution_roles: true,
  managed_policy_attachments: 0,
  verified_components: ["api", "worker", "runtime", "gateway", "catalog", "ingestion"]
}' >"${praxis_evidence_dir}/iam-role-separation.json"
jq . "${praxis_evidence_dir}/iam-role-separation.json"
