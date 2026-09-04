#!/usr/bin/env bash
# Verify private S3 frontend hosting and CloudFront browser delivery.
set -euo pipefail
umask 077

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"

praxis_require_commands aws curl jq "${praxis_tofu}"

praxis_bucket="$(praxis_tofu_output frontend_bucket_name)"
praxis_distribution_id="$(praxis_tofu_output frontend_distribution_id)"
praxis_frontend_url="$(praxis_tofu_output frontend_url)"
praxis_public_access="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    s3api get-public-access-block \
    --bucket "${praxis_bucket}" \
    --query PublicAccessBlockConfiguration \
    --output json
)"
praxis_ownership="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    s3api get-bucket-ownership-controls \
    --bucket "${praxis_bucket}" \
    --query 'OwnershipControls.Rules[0].ObjectOwnership' \
    --output text
)"
praxis_encryption="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    s3api get-bucket-encryption \
    --bucket "${praxis_bucket}" \
    --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' \
    --output text
)"
praxis_policy_public="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    s3api get-bucket-policy-status \
    --bucket "${praxis_bucket}" \
    --query 'PolicyStatus.IsPublic' \
    --output text
)"
praxis_distribution="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    cloudfront get-distribution \
    --id "${praxis_distribution_id}" \
    --query Distribution \
    --output json
)"

if ! jq -e '
  .BlockPublicAcls == true
  and .BlockPublicPolicy == true
  and .IgnorePublicAcls == true
  and .RestrictPublicBuckets == true
' <<<"${praxis_public_access}" >/dev/null || \
  [[ "${praxis_ownership}" != "BucketOwnerEnforced" ]] || \
  [[ "${praxis_encryption}" != "AES256" ]] || \
  [[ "${praxis_policy_public}" != "False" ]]; then
  printf 'Frontend bucket does not match the reviewed private-origin contract.\n' >&2
  exit 1
fi

# Match delivery settings that enforce HTTPS, OAC, bounded edge locations, and SPA routing.
if ! jq -e '
  .Status == "Deployed"
  and .DistributionConfig.Enabled == true
  and .DistributionConfig.DefaultRootObject == "index.html"
  and .DistributionConfig.HttpVersion == "http2and3"
  and .DistributionConfig.IsIPV6Enabled == true
  and .DistributionConfig.PriceClass == "PriceClass_100"
  and .DistributionConfig.Origins.Quantity == 1
  and (.DistributionConfig.Origins.Items[0].OriginAccessControlId | length) > 0
  and .DistributionConfig.Origins.Items[0].S3OriginConfig.OriginAccessIdentity == ""
  and (.DistributionConfig.DefaultCacheBehavior.AllowedMethods.Items | sort) == ["GET", "HEAD"]
  and (.DistributionConfig.DefaultCacheBehavior.AllowedMethods.CachedMethods.Items | sort) == ["GET", "HEAD"]
  and .DistributionConfig.DefaultCacheBehavior.Compress == true
  and .DistributionConfig.DefaultCacheBehavior.ViewerProtocolPolicy == "redirect-to-https"
  and (.DistributionConfig.DefaultCacheBehavior.CachePolicyId | length) > 0
  and (.DistributionConfig.DefaultCacheBehavior.ResponseHeadersPolicyId | length) > 0
  and ([.DistributionConfig.CustomErrorResponses.Items[] |
    {error: .ErrorCode, response: .ResponseCode, page: .ResponsePagePath}] | sort_by(.error)) == [
      {error: 403, response: "200", page: "/index.html"},
      {error: 404, response: "200", page: "/index.html"}
    ]
' <<<"${praxis_distribution}" >/dev/null; then
  printf 'CloudFront does not match the reviewed frontend delivery contract.\n' >&2
  exit 1
fi

praxis_index="$(curl --silent --show-error --fail --max-time 20 "${praxis_frontend_url}/")"
praxis_spa="$(
  curl --silent --show-error --fail --max-time 20 \
    "${praxis_frontend_url}/__praxis_spa_smoke__"
)"
if [[ "${praxis_index}" != *'<div id="root"></div>'* ]] || \
  [[ "${praxis_spa}" != *'<div id="root"></div>'* ]]; then
  printf 'CloudFront did not serve the expected application shell.\n' >&2
  exit 1
fi

mkdir -p "${praxis_evidence_dir}"
jq -n '{
  cloudfront_deployed: true,
  default_https: true,
  private_s3_origin: true,
  security_headers_policy: true,
  spa_fallback: true
}' >"${praxis_evidence_dir}/frontend-hosting.json"
jq . "${praxis_evidence_dir}/frontend-hosting.json"
