#!/usr/bin/env bash
# Verify the versioned prompt-attack guardrail and its stable Runtime attachment.
set -euo pipefail

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"

praxis_require_commands aws jq "${praxis_tofu}"

praxis_guardrail_id="$(praxis_tofu_output bedrock_guardrail_id)"
praxis_guardrail_version="$(praxis_tofu_output bedrock_guardrail_version)"
praxis_guardrail="$(aws \
  --profile "${praxis_profile}" --region "${praxis_region}" \
  bedrock get-guardrail \
  --guardrail-identifier "${praxis_guardrail_id}" \
  --guardrail-version "${praxis_guardrail_version}" \
  --output json)"

# Only prompt-attack input detection is enabled; broad domain filters stay absent.
if ! jq -e --arg version "${praxis_guardrail_version}" '
  .status == "READY" and
  .version == $version and
  .contentPolicy.tier.tierName == "CLASSIC" and
  (.contentPolicy.filters | length) == 1 and
  (.contentPolicy.filters[0] |
    .type == "PROMPT_ATTACK" and
    .inputStrength == "HIGH" and
    .inputAction == "BLOCK" and
    .inputEnabled == true and
    .outputStrength == "NONE" and
    .outputAction == "NONE" and
    .outputEnabled == false)
' <<<"${praxis_guardrail}" >/dev/null; then
  printf 'Deployed Bedrock guardrail does not match the reviewed policy.\n' >&2
  exit 1
fi

praxis_runtime_id="$(praxis_tofu_output agentcore_runtime_id)"
praxis_runtime_version="$(praxis_tofu_output agentcore_runtime_endpoint_version)"
praxis_runtime_environment="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id "${praxis_runtime_id}" \
    --agent-runtime-version "${praxis_runtime_version}" \
    --query environmentVariables --output json
)"
if ! jq -e \
  --arg id "${praxis_guardrail_id}" \
  --arg version "${praxis_guardrail_version}" \
  '.PRAXIS_GUARDRAIL_ID == $id and .PRAXIS_GUARDRAIL_VERSION == $version' \
  <<<"${praxis_runtime_environment}" >/dev/null; then
  printf 'Stable AgentCore Runtime version does not use the reviewed guardrail.\n' >&2
  exit 1
fi

mkdir -p "${praxis_evidence_dir}"
jq -n '{
  attached_to_stable_runtime: true,
  filter: {
    input_action: "BLOCK",
    input_strength: "HIGH",
    output_enabled: false,
    type: "PROMPT_ATTACK"
  },
  status: "READY",
  tier: "CLASSIC",
  versioned: true
}' >"${praxis_evidence_dir}/bedrock-guardrail.json"
jq . "${praxis_evidence_dir}/bedrock-guardrail.json"
