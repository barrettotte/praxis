# Infrastructure

Two independent OpenTofu roots manage infrastructure:

- [bootstrap/](bootstrap/README.md): durable state bucket and cost budget.
- [environments/dev/](environments/dev/README.md): disposable application resources.

Both pin OpenTofu and the AWS provider in `versions.tf`; update their constraints
and provider lock files together.

Resources carry `Project`, `Environment`, and `ManagedBy` tags. Development names
use the `praxis-dev` prefix, with service-specific normalization or unique
suffixes where required. Keep credentials and personal information out of tags.

Use the [operations guide](../docs/infrastructure-operations.md) for setup,
ECR-first deployment, plan review, and teardown. Bootstrap resources survive
development teardown; shared account-level tracing is outside both roots.
