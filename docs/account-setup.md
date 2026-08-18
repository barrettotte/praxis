# AWS account setup

Praxis uses a simplified development-only IAM setup for its single-user AWS account.

## Configuration

1. Create the IAM user `barrett` with console access.
2. Add the user to the `praxis-dev` IAM group.
3. Attach the AWS-managed `SignInLocalDevelopmentAccess` and `AdministratorAccess` policies to the group.
4. Enable MFA for the user and do not create IAM access keys.
5. Keep the root identity MFA-protected and out of routine development.

Authenticate with short-lived console credentials:

```bash
aws login --profile praxis-dev --region us-east-1
aws sts get-caller-identity --profile praxis-dev --region us-east-1
```

The identity check must resolve to the `barrett` IAM user, never the root identity. The CLI refreshes credentials 
during the login session; rerun `aws login` when the overall session expires.

`AdministratorAccess` is a deliberate convenience for this personal development account, not an application permission model. 
Review every OpenTofu plan before applying it, configure budget alerts before deploying resources, and give each deployed 
workload its own least-privilege IAM role. Revisit the human-access model before the project becomes shared, persistent, or production-like.
