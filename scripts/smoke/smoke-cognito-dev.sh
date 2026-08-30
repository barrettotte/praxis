#!/usr/bin/env bash
# Verify the deployed application user pool matches its reviewed identity policy.
set -euo pipefail
umask 077

praxis_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${praxis_script_dir}/lib/dev-smoke.sh"

praxis_require_commands aws jq "${praxis_tofu}"

praxis_user_pool_id="$(praxis_tofu_output cognito_user_pool_id)"
praxis_user_pool="$(
  aws --profile "${praxis_profile}" --region "${praxis_region}" \
    cognito-idp describe-user-pool \
    --user-pool-id "${praxis_user_pool_id}" \
    --query UserPool \
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

mkdir -p "${praxis_evidence_dir}"
jq -n '{
  account_recovery: "verified_email",
  admin_created_users_only: true,
  case_insensitive_email_sign_in: true,
  deletion_protection: false,
  minimum_password_length: 14,
  mfa: "OFF",
  user_pool_tier: "LITE"
}' >"${praxis_evidence_dir}/cognito-user-pool.json"
jq . "${praxis_evidence_dir}/cognito-user-pool.json"
