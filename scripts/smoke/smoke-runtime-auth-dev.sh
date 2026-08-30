#!/usr/bin/env bash
# Verify the deployed AgentCore Runtime rejects direct unsigned invocation.
set -euo pipefail
umask 077

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"
praxis_work_dir="$(mktemp -d)"
trap 'rm -rf "${praxis_work_dir}"' EXIT

praxis_require_commands aws curl jq "${praxis_tofu}"

# Resolve the exact immutable version served by the reviewed stable endpoint.
praxis_runtime_id="$(praxis_tofu_output agentcore_runtime_id)"
praxis_runtime_arn="$(praxis_tofu_output agentcore_runtime_arn)"
praxis_endpoint_name="$(praxis_tofu_output agentcore_runtime_endpoint_name)"
praxis_endpoint_version="$(praxis_tofu_output agentcore_runtime_endpoint_version)"

# An omitted custom JWT authorizer selects AgentCore Runtime's default IAM mode.
praxis_runtime_configuration="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id "${praxis_runtime_id}" \
    --agent-runtime-version "${praxis_endpoint_version}" \
    --output json
)"
if ! jq -e \
  --arg runtime_arn "${praxis_runtime_arn}" \
  --arg runtime_version "${praxis_endpoint_version}" '
    .agentRuntimeArn == $runtime_arn
    and .agentRuntimeVersion == $runtime_version
    and .status == "READY"
    and .protocolConfiguration.serverProtocol == "HTTP"
    and ((has("authorizerConfiguration") | not) or .authorizerConfiguration == null)
  ' <<<"${praxis_runtime_configuration}" >/dev/null; then
  printf 'The deployed stable Runtime version does not use the expected default IAM authorization.\n' >&2
  exit 1
fi

# Exercise the public service address without credentials; IAM must reject the
# request before dispatch to the Runtime container and its metered model path.
praxis_encoded_runtime_arn="$(
  jq -rn --arg value "${praxis_runtime_arn}" '$value | @uri'
)"
praxis_encoded_qualifier="$(
  jq -rn --arg value "${praxis_endpoint_name}" '$value | @uri'
)"
praxis_invoke_url="https://bedrock-agentcore.${praxis_region}.amazonaws.com/runtimes/${praxis_encoded_runtime_arn}/invocations?qualifier=${praxis_encoded_qualifier}"
praxis_unsigned_status="$(
  curl --silent --show-error \
    --connect-timeout 5 \
    --max-time 15 \
    --output "${praxis_work_dir}/unsigned-response.json" \
    --write-out '%{http_code}' \
    --request POST \
    --header 'accept: application/json' \
    --header 'content-type: application/json' \
    --header 'x-amzn-bedrock-agentcore-runtime-session-id: praxis-runtime-auth-probe-000000000001' \
    --data '{"prompt":"authorization boundary probe"}' \
    "${praxis_invoke_url}"
)"
if [[ "${praxis_unsigned_status}" != "403" ]]; then
  printf 'Unsigned direct Runtime request returned HTTP %s instead of 403.\n' \
    "${praxis_unsigned_status}" >&2
  exit 1
fi

mkdir -p "${praxis_evidence_dir}"
jq -n --argjson status "${praxis_unsigned_status}" '{
  authorization: "AWS_IAM",
  direct_unsigned_request_rejected: true,
  direct_unsigned_status: $status,
  runtime_handler_reached: false,
  model_invoked: false,
  stable_runtime_ready: true
}' >"${praxis_evidence_dir}/agentcore-runtime-auth.json"
jq . "${praxis_evidence_dir}/agentcore-runtime-auth.json"
