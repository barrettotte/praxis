#!/usr/bin/env bash
# Enable and verify mandatory MMDSv2 on an OpenTofu-managed AgentCore Runtime.
set -euo pipefail

# OpenTofu passes the complete desired Runtime configuration because the update
# API requires the artifact and execution role along with the MMDSv2 setting.
for praxis_name in \
  PRAXIS_AGENT_CONTAINER_URI \
  PRAXIS_AGENT_GATEWAY_URL \
  PRAXIS_AGENT_IDLE_TIMEOUT \
  PRAXIS_AGENT_MAX_LIFETIME \
  PRAXIS_AGENT_MAX_RESULTS \
  PRAXIS_AGENT_MAX_TOOL_CALLS \
  PRAXIS_AGENT_MODEL_ID \
  PRAXIS_AGENT_ROLE_ARN \
  PRAXIS_AGENT_RUNTIME_ID \
  PRAXIS_AGENT_RUNTIME_REGION; do
  if [[ -z "${!praxis_name:-}" ]]; then
    printf '%s is required\n' "${praxis_name}" >&2
    exit 2
  fi
done

for praxis_command in aws jq; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

# Translate flat provisioner environment variables into AWS CLI request shapes.
praxis_artifact="$(
  jq -cn \
    --arg uri "${PRAXIS_AGENT_CONTAINER_URI}" \
    '{containerConfiguration: {containerUri: $uri}}'
)"
praxis_environment="$(
  jq -cn \
    --arg region "${PRAXIS_AGENT_RUNTIME_REGION}" \
    --arg gateway_url "${PRAXIS_AGENT_GATEWAY_URL}" \
    --arg max_results "${PRAXIS_AGENT_MAX_RESULTS}" \
    --arg max_tool_calls "${PRAXIS_AGENT_MAX_TOOL_CALLS}" \
    --arg model_id "${PRAXIS_AGENT_MODEL_ID}" \
    '{
      AWS_REGION: $region,
      PRAXIS_GATEWAY_URL: $gateway_url,
      PRAXIS_MAX_CATALOG_RESULTS: $max_results,
      PRAXIS_MAX_TOOL_CALLS: $max_tool_calls,
      PRAXIS_MODEL_ID: $model_id
    }'
)"
praxis_lifecycle="$(
  jq -cn \
    --argjson idle_timeout "${PRAXIS_AGENT_IDLE_TIMEOUT}" \
    --argjson max_lifetime "${PRAXIS_AGENT_MAX_LIFETIME}" \
    '{
      idleRuntimeSessionTimeout: $idle_timeout,
      maxLifetime: $max_lifetime
    }'
)"

# Applying the security setting creates a new immutable Runtime version.
aws \
  --region "${PRAXIS_AGENT_RUNTIME_REGION}" \
  bedrock-agentcore-control update-agent-runtime \
  --agent-runtime-id "${PRAXIS_AGENT_RUNTIME_ID}" \
  --agent-runtime-artifact "${praxis_artifact}" \
  --role-arn "${PRAXIS_AGENT_ROLE_ARN}" \
  --description "Evidence-backed project recommendation agent" \
  --environment-variables "${praxis_environment}" \
  --lifecycle-configuration "${praxis_lifecycle}" \
  --metadata-configuration '{"requireMMDSV2":true}' \
  --network-configuration '{"networkMode":"PUBLIC"}' \
  --protocol-configuration '{"serverProtocol":"HTTP"}' \
  --no-cli-pager >/dev/null

# Wait for the asynchronous update before OpenTofu reports a successful apply.
for _ in {1..60}; do
  praxis_status="$(
    aws \
      --region "${PRAXIS_AGENT_RUNTIME_REGION}" \
      bedrock-agentcore-control get-agent-runtime \
      --agent-runtime-id "${PRAXIS_AGENT_RUNTIME_ID}" \
      --query status \
      --output text \
      --no-cli-pager
  )"
  case "${praxis_status}" in
    READY) break ;;
    CREATE_FAILED | UPDATE_FAILED)
      printf 'AgentCore Runtime entered %s\n' "${praxis_status}" >&2
      exit 1
      ;;
  esac
  sleep 5
done

if [[ "${praxis_status}" != "READY" ]]; then
  printf 'Timed out waiting for AgentCore Runtime MMDSv2 update\n' >&2
  exit 1
fi

# Verify the control plane persisted the setting required for invocation.
praxis_mmdsv2="$(
  aws \
    --region "${PRAXIS_AGENT_RUNTIME_REGION}" \
    bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id "${PRAXIS_AGENT_RUNTIME_ID}" \
    --query metadataConfiguration.requireMMDSV2 \
    --output text \
    --no-cli-pager
)"
if [[ "${praxis_mmdsv2}" != "True" && "${praxis_mmdsv2}" != "true" ]]; then
  printf 'AgentCore Runtime did not report MMDSv2 as enabled\n' >&2
  exit 1
fi

printf 'AgentCore Runtime is READY with MMDSv2 enabled.\n'
