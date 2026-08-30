#!/usr/bin/env bash
# Verify the Cognito and API Gateway application identity boundary.
set -euo pipefail
umask 077

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"

praxis_require_commands aws curl jq "${praxis_tofu}"

praxis_user_pool_id="$(praxis_tofu_output cognito_user_pool_id)"
praxis_user_pool="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    cognito-idp describe-user-pool \
    --user-pool-id "${praxis_user_pool_id}" \
    --query UserPool \
    --output json
)"
praxis_frontend_client_id="$(praxis_tofu_output cognito_frontend_client_id)"
praxis_frontend_client="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    cognito-idp describe-user-pool-client \
    --user-pool-id "${praxis_user_pool_id}" \
    --client-id "${praxis_frontend_client_id}" \
    --query UserPoolClient \
    --output json
)"
praxis_api_id="$(praxis_tofu_output api_gateway_id)"
praxis_api_url="$(praxis_tofu_output api_gateway_url)"
praxis_api_url="${praxis_api_url%/}"
praxis_authorizer_id="$(praxis_tofu_output api_gateway_jwt_authorizer_id)"
praxis_authorizer="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    apigatewayv2 get-authorizer \
    --api-id "${praxis_api_id}" \
    --authorizer-id "${praxis_authorizer_id}" \
    --output json
)"
praxis_routes="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    apigatewayv2 get-routes \
    --api-id "${praxis_api_id}" \
    --query Items \
    --output json
)"

# Match exact security-relevant settings while ignoring generated identifiers.
if ! jq -e --arg user_pool_id "${praxis_user_pool_id}" '
  .Id == $user_pool_id
  and .DeletionProtection == "INACTIVE"
  and .UserPoolTier == "LITE"
  and .UsernameAttributes == ["email"]
  and .AutoVerifiedAttributes == ["email"]
  and .MfaConfiguration == "OFF"
  and .AdminCreateUserConfig.AllowAdminCreateUserOnly == true
  and .AccountRecoverySetting.RecoveryMechanisms == [
    {Name: "verified_email", Priority: 1}
  ]
  and .EmailConfiguration.EmailSendingAccount == "COGNITO_DEFAULT"
  and .Policies.PasswordPolicy.MinimumLength == 14
  and .Policies.PasswordPolicy.RequireLowercase == true
  and .Policies.PasswordPolicy.RequireNumbers == true
  and .Policies.PasswordPolicy.RequireSymbols == true
  and .Policies.PasswordPolicy.RequireUppercase == true
  and .Policies.PasswordPolicy.TemporaryPasswordValidityDays == 7
  and .UsernameConfiguration.CaseSensitive == false
  and .UserAttributeUpdateSettings.AttributesRequireVerificationBeforeUpdate == ["email"]
' <<<"${praxis_user_pool}" >/dev/null; then
  printf 'Deployed Cognito user pool does not match the reviewed identity policy.\n' >&2
  exit 1
fi

# A browser client must not contain a secret or enable password/plain OAuth flows.
if ! jq -e \
  --arg user_pool_id "${praxis_user_pool_id}" \
  --arg client_id "${praxis_frontend_client_id}" '
  .UserPoolId == $user_pool_id
  and .ClientId == $client_id
  and .ClientSecret == null
  and (.ExplicitAuthFlows | sort) == [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH"
  ]
  and .SupportedIdentityProviders == ["COGNITO"]
  and .PreventUserExistenceErrors == "ENABLED"
  and .EnableTokenRevocation == true
  and .AuthSessionValidity == 3
  and .AccessTokenValidity == 1
  and .IdTokenValidity == 1
  and .RefreshTokenValidity == 7
  and .TokenValidityUnits.AccessToken == "hours"
  and .TokenValidityUnits.IdToken == "hours"
  and .TokenValidityUnits.RefreshToken == "days"
  and (.ReadAttributes | sort) == ["email", "email_verified"]
' <<<"${praxis_frontend_client}" >/dev/null; then
  printf 'Deployed Cognito browser client does not match the reviewed identity policy.\n' >&2
  exit 1
fi

# Bind every declared route to this pool and client at the public API boundary.
if ! jq -e \
  --arg authorizer_id "${praxis_authorizer_id}" \
  --arg audience "${praxis_frontend_client_id}" \
  --arg issuer "https://cognito-idp.${praxis_region}.amazonaws.com/${praxis_user_pool_id}" '
  .AuthorizerId == $authorizer_id
  and .AuthorizerType == "JWT"
  and .IdentitySource == ["$request.header.Authorization"]
  and .JwtConfiguration.Audience == [$audience]
  and .JwtConfiguration.Issuer == $issuer
' <<<"${praxis_authorizer}" >/dev/null; then
  printf 'Deployed API JWT authorizer does not match the reviewed identity policy.\n' >&2
  exit 1
fi

if ! jq -e --arg authorizer_id "${praxis_authorizer_id}" '
  length == 4
  and all(.[];
    .AuthorizationType == "JWT"
    and .AuthorizerId == $authorizer_id)
  and ([.[].RouteKey] | sort) == [
    "GET /v1/sessions/{sessionId}",
    "POST /v1/projects/{candidateId}/select",
    "POST /v1/sessions",
    "POST /v1/sessions/{sessionId}/messages"
  ]
' <<<"${praxis_routes}" >/dev/null; then
  printf 'Deployed API routes are not all protected by the reviewed JWT authorizer.\n' >&2
  exit 1
fi

# A missing bearer token must stop before Lambda and metered Runtime invocation.
praxis_unauthenticated_status="$(
  curl --silent --show-error --max-time 15 \
    --output /dev/null \
    --write-out '%{http_code}' \
    --request POST \
    --header 'content-type: application/json' \
    --data '{"goal":"compiler"}' \
    "${praxis_api_url}/v1/sessions"
)"
if [[ "${praxis_unauthenticated_status}" != "401" ]]; then
  printf 'Unauthenticated API request returned HTTP %s instead of 401.\n' \
    "${praxis_unauthenticated_status}" >&2
  exit 1
fi

mkdir -p "${praxis_evidence_dir}"
jq -n '{
  account_recovery: "verified_email",
  admin_created_users_only: true,
  api_authorization: {
    all_declared_routes_protected: true,
    audience_bound_to_browser_client: true,
    issuer_bound_to_user_pool: true,
    type: "JWT",
    unauthenticated_status: 401
  },
  browser_client: {
    access_token_hours: 1,
    auth_flows: ["refresh_token", "user_srp"],
    client_secret: false,
    id_token_hours: 1,
    refresh_token_days: 7,
    token_revocation: true,
    user_existence_errors_suppressed: true
  },
  case_insensitive_email_sign_in: true,
  deletion_protection: false,
  minimum_password_length: 14,
  mfa: "OFF",
  user_pool_tier: "LITE"
}' >"${praxis_evidence_dir}/cognito-user-pool.json"
jq . "${praxis_evidence_dir}/cognito-user-pool.json"
