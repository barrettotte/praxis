#!/usr/bin/env bash
# Build and publish the browser application to the development CloudFront origin.
set -euo pipefail

praxis_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
praxis_profile="${AWS_PROFILE:-praxis-dev}"
praxis_region="${AWS_REGION:-us-east-1}"
praxis_tofu="${TOFU:-tofu}"
praxis_infra_dir="${praxis_repo_root}/infra/environments/dev"
praxis_frontend_dir="${praxis_repo_root}/frontend"

if [[ "${CONFIRM:-}" != "deploy-frontend-dev" ]]; then
  printf 'CONFIRM=deploy-frontend-dev is required\n' >&2
  exit 2
fi

for praxis_command in aws npm "${praxis_tofu}"; do
  command -v "${praxis_command}" >/dev/null || {
    printf 'Required command is unavailable: %s\n' "${praxis_command}" >&2
    exit 2
  }
done

praxis_tofu_output() {
  AWS_PROFILE="${praxis_profile}" "${praxis_tofu}" \
    -chdir="${praxis_infra_dir}" output -raw "$1"
}

# Public deployment configuration is embedded by Vite; no credential enters the bundle.
export VITE_API_URL="$(praxis_tofu_output api_gateway_url)"
export VITE_COGNITO_USER_POOL_ID="$(praxis_tofu_output cognito_user_pool_id)"
export VITE_COGNITO_CLIENT_ID="$(praxis_tofu_output cognito_frontend_client_id)"
praxis_bucket="$(praxis_tofu_output frontend_bucket_name)"
praxis_distribution_id="$(praxis_tofu_output frontend_distribution_id)"
praxis_frontend_url="$(praxis_tofu_output frontend_url)"

npm --prefix "${praxis_frontend_dir}" run build
aws --profile "${praxis_profile}" --region "${praxis_region}" s3 sync \
  "${praxis_frontend_dir}/dist/" "s3://${praxis_bucket}/" \
  --cache-control 'public,max-age=300' \
  --delete \
  --only-show-errors
aws --profile "${praxis_profile}" --region "${praxis_region}" s3 cp \
  "${praxis_frontend_dir}/dist/index.html" "s3://${praxis_bucket}/index.html" \
  --cache-control 'no-cache' \
  --content-type 'text/html' \
  --only-show-errors

# Invalidate one wildcard path so the new shell and hashed asset references move together.
praxis_invalidation_id="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    cloudfront create-invalidation \
    --distribution-id "${praxis_distribution_id}" \
    --paths '/*' \
    --query 'Invalidation.Id' \
    --output text \
    --no-cli-pager
)"
printf 'Published frontend: %s\n' "${praxis_frontend_url}"
printf 'CloudFront invalidation: %s\n' "${praxis_invalidation_id}"
