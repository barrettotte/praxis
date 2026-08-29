#!/usr/bin/env bash
# Preview or explicitly publish the reviewed agent image to development ECR.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_action="${ACTION:-preview}"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
praxis_container_tool="${CONTAINER_TOOL:-podman}"
praxis_source_image="${AGENT_IMAGE:-praxis-agent:dev}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"

# Keep the write path behind a distinct confirmation while preview stays read-only.
case "${praxis_action}" in
  preview) ;;
  push)
    if [[ "${CONFIRM:-}" != "push-agent-image-dev" ]]; then
      printf 'CONFIRM=push-agent-image-dev is required\n' >&2
      exit 2
    fi
    ;;
  *)
    printf 'ACTION must be preview or push\n' >&2
    exit 2
    ;;
esac

for praxis_command in aws git jq "${praxis_tofu}" "${praxis_container_tool}"; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

# An OCI revision label is meaningful only when all image inputs are committed.
praxis_dirty_image_sources="$(
  git -C "${praxis_repo_root}" status --porcelain=v1 --untracked-files=all -- \
    .dockerignore backend/Containerfile backend/src pyproject.toml uv.lock README.md LICENSE
)"
if [[ -n "${praxis_dirty_image_sources}" ]]; then
  printf 'Commit image-affecting changes before publication:\n%s\n' \
    "${praxis_dirty_image_sources}" >&2
  exit 2
fi

# AgentCore requires ARM64; bind the image to the exact source revision as well.
praxis_commit="$(git -C "${praxis_repo_root}" rev-parse --verify HEAD)"
praxis_tag="git-${praxis_commit}"
praxis_architecture="$(
  "${praxis_container_tool}" image inspect \
    --format '{{.Architecture}}' "${praxis_source_image}"
)"
if [[ "${praxis_architecture}" != "arm64" ]]; then
  printf 'Source image must be arm64, found: %s\n' "${praxis_architecture}" >&2
  exit 2
fi

praxis_image_revision="$(
  "${praxis_container_tool}" image inspect \
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    "${praxis_source_image}"
)"
if [[ "${praxis_image_revision}" != "${praxis_commit}" ]]; then
  printf 'Source image revision does not match HEAD; run make agent-image\n' >&2
  exit 2
fi

# Resolve the environment-specific repository from deployed OpenTofu state.
praxis_repository_url="$(
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -json ecr_repository_urls |
    jq -er '.agent'
)"
praxis_registry="${praxis_repository_url%%/*}"
praxis_repository_name="${praxis_repository_url#*/}"
if [[ "${praxis_registry}" == "${praxis_repository_url}" || -z "${praxis_repository_name}" ]]; then
  printf 'Invalid agent ECR repository URL in OpenTofu output\n' >&2
  exit 2
fi
praxis_target_image="${praxis_repository_url}:${praxis_tag}"

# Immutable tags make an existing revision a successful idempotent publication.
praxis_remote_digest="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" ecr list-images \
    --repository-name "${praxis_repository_name}" \
    --filter tagStatus=TAGGED \
    --query "imageIds[?imageTag=='${praxis_tag}'].imageDigest | [0]" \
    --output text \
    --no-cli-pager
)"

printf 'Source image: %s\n' "${praxis_source_image}"
printf 'Architecture: %s\n' "${praxis_architecture}"
printf 'Revision: %s\n' "${praxis_commit}"
printf 'Target image: %s\n' "${praxis_target_image}"

if [[ -n "${praxis_remote_digest}" && "${praxis_remote_digest}" != "None" ]]; then
  printf 'ECR digest: %s\n' "${praxis_remote_digest}"
  printf 'The immutable image is already published.\n'
  exit 0
fi

if [[ "${praxis_action}" == "preview" ]]; then
  printf 'ECR status: not published\n'
  printf 'Run make push-agent-image-dev CONFIRM=push-agent-image-dev after review.\n'
  exit 0
fi

# Always remove the short-lived registry login from the container client.
praxis_logged_in=false
cleanup() {
  if [[ "${praxis_logged_in}" == "true" ]]; then
    "${praxis_container_tool}" logout "${praxis_registry}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

aws --profile "${praxis_profile}" --region "${praxis_region}" ecr get-login-password |
  "${praxis_container_tool}" login \
    --username AWS \
    --password-stdin \
    "${praxis_registry}" >/dev/null
praxis_logged_in=true

# Publish, then re-read ECR so callers receive the registry-assigned digest.
"${praxis_container_tool}" tag "${praxis_source_image}" "${praxis_target_image}"
"${praxis_container_tool}" push "${praxis_target_image}"

praxis_remote_digest="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" ecr describe-images \
    --repository-name "${praxis_repository_name}" \
    --image-ids "imageTag=${praxis_tag}" \
    --query 'imageDetails[0].imageDigest' \
    --output text \
    --no-cli-pager
)"
printf 'Published image: %s@%s\n' "${praxis_repository_url}" "${praxis_remote_digest}"
