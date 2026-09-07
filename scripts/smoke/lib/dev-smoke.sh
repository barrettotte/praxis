#!/usr/bin/env bash
# Provide shared paths, settings, and command checks for deployed smoke scripts.

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"

praxis_require_commands() {
  local praxis_command
  for praxis_command in "$@"; do
    command -v "${praxis_command}" >/dev/null || {
      printf 'Required command is unavailable: %s\n' "${praxis_command}" >&2
      return 2
    }
  done
}

praxis_tofu_output() {
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw "$1"
}
