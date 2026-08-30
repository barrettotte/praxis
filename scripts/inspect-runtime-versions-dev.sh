#!/usr/bin/env bash
# List sanitized model, image, and readiness metadata for development Runtime versions.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"

for praxis_command in "${praxis_tofu}" aws jq; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command not found: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

# Resolve the Runtime ID without printing resource or account identifiers.
praxis_runtime_id="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw agentcore_runtime_id
)"
praxis_versions="$(
  AWS_PROFILE="${praxis_profile}" aws bedrock-agentcore-control list-agent-runtime-versions \
    --region "${praxis_region}" \
    --agent-runtime-id "${praxis_runtime_id}" \
    --query 'agentRuntimes[].agentRuntimeVersion' \
    --output json
)"

printf '%-8s %-10s %-31s %-71s %s\n' 'VERSION' 'STATUS' 'MODEL' 'IMAGE DIGEST' 'MMDSV2'
while IFS= read -r praxis_version; do
  # Query only fields needed to review an immutable promotion candidate.
  praxis_metadata="$(
    AWS_PROFILE="${praxis_profile}" aws bedrock-agentcore-control get-agent-runtime \
      --region "${praxis_region}" \
      --agent-runtime-id "${praxis_runtime_id}" \
      --agent-runtime-version "${praxis_version}" \
      --query '{status:status,model:environmentVariables.PRAXIS_MODEL_ID,container:agentRuntimeArtifact.containerConfiguration.containerUri,mmdsv2:metadataConfiguration.requireMMDSV2}' \
      --output json
  )"
  praxis_status="$(jq -r '.status // "unknown"' <<<"${praxis_metadata}")"
  praxis_model_id="$(jq -r '.model // "unknown"' <<<"${praxis_metadata}")"
  praxis_container_uri="$(jq -r '.container // "unknown"' <<<"${praxis_metadata}")"
  praxis_container_digest="${praxis_container_uri##*@}"
  praxis_mmdsv2="$(jq -r '.mmdsv2 // false' <<<"${praxis_metadata}")"
  printf '%-8s %-10s %-31s %-71s %s\n' \
    "${praxis_version}" "${praxis_status}" "${praxis_model_id}" \
    "${praxis_container_digest}" "${praxis_mmdsv2}"
done < <(jq -r '.[]' <<<"${praxis_versions}" | sort -n)
