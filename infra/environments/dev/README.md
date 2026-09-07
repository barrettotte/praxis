# Development environment

This OpenTofu root owns disposable Praxis resources in `us-east-1`. State lives
in the separately managed, encrypted bootstrap S3 bucket with native locking.
Resources use the `praxis-dev` prefix and project/environment/management tags.

Follow the [operations guide](../../../docs/infrastructure-operations.md) for:

- [Bootstrap setup](../../../docs/infrastructure-operations.md#bootstrap-lifecycle).
- [ECR-first deployment](../../../docs/infrastructure-operations.md#first-deployment).
- [Full deployment and updates](../../../docs/infrastructure-operations.md#full-deployment-and-updates).
- [Teardown and residual checks](../../../docs/infrastructure-operations.md#teardown).

Keep the published image digest in ignored `deployment.auto.tfvars`, using the
adjacent example. `DEFAULT` follows Runtime updates; pause submissions during
apply and verify READY/MMDSv2 before resuming. Infrastructure does not create
Cognito users or publish frontend assets.

See [architecture](../../../docs/architecture.md) for boundaries and
[security](../../../docs/security.md) for controls and limits. Resource settings
and IAM permissions are defined in the adjacent OpenTofu files, not duplicated here.
