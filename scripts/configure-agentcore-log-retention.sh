#!/usr/bin/env bash
# Apply finite retention to service-created AgentCore Runtime log groups.
set -euo pipefail

for praxis_name in \
  PRAXIS_LOG_GROUP_NAMES \
  PRAXIS_LOG_RETENTION_DAYS \
  PRAXIS_RUNTIME_REGION; do
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

# AgentCore owns log-group creation, which can finish shortly after endpoint creation.
while IFS= read -r praxis_log_group; do
  praxis_deadline=$((SECONDS + 60))
  while true; do
    praxis_match_count="$(
      aws --region "${PRAXIS_RUNTIME_REGION}" logs describe-log-groups \
        --log-group-name-prefix "${praxis_log_group}" \
        --query 'logGroups[].logGroupName' \
        --output json \
        --no-cli-pager |
        jq --arg name "${praxis_log_group}" \
          '[.[] | select(. == $name)] | length'
    )"
    if [[ "${praxis_match_count}" == "1" ]]; then
      break
    fi
    if ((SECONDS >= praxis_deadline)); then
      printf 'Timed out waiting for AgentCore log group: %s\n' "${praxis_log_group}" >&2
      exit 1
    fi
    sleep 2
  done

  aws --region "${PRAXIS_RUNTIME_REGION}" logs put-retention-policy \
    --log-group-name "${praxis_log_group}" \
    --retention-in-days "${PRAXIS_LOG_RETENTION_DAYS}" \
    --no-cli-pager
done < <(jq -er '.[]' <<<"${PRAXIS_LOG_GROUP_NAMES}")

printf 'AgentCore Runtime log retention is %s days.\n' "${PRAXIS_LOG_RETENTION_DAYS}"
