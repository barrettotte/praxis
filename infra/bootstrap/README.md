# Bootstrap stack

This independent OpenTofu root owns the durable resources required before the
temporary development environment can use remote state. It starts with local
state because the remote-state resources do not exist yet. Do not apply it
until `tofu plan` has been reviewed explicitly. A coding agent may apply only
the exact saved plan it generated, reviewed, and summarized. Teardown requires
explicit user approval for each run.

Application resources do not belong in this stack. Bootstrap resources must be
documented before they are preserved during development-environment teardown.

The state bucket name is derived from the current AWS account and fixed region
without hard-coding an account identifier. S3-managed AES-256 encryption is
explicit because a customer-managed KMS key is not required for this single-user
development state. Public access is blocked, non-TLS requests are denied, and
destruction requires an explicit guarded Make target.

After destroying the temporary development stack, the bootstrap resources can
also be removed permanently with:

```shell
make tofu-plan-destroy-bootstrap
tofu -chdir=infra/bootstrap show bootstrap-destroy.tfplan
make tofu-destroy-bootstrap CONFIRM=destroy-bootstrap
```

The bucket uses `force_destroy` so this command can remove versioned state
objects. It is intentionally destructive and cannot recover deleted state.
See `docs/infrastructure-operations.md` for the complete plan, apply, and
teardown procedure.

Bucket versioning permits recovery from accidental state replacement or
deletion. Development state uses OpenTofu's native S3 lockfile mechanism rather
than a separate DynamoDB table. Bootstrap state remains local so the bootstrap
stack can destroy the bucket cleanly; do not delete `terraform.tfstate` from
this directory while the bootstrap resources exist.

The durable bootstrap stack also owns the annual `$10` development cost budget. AWS
Budgets has no non-resetting project-total period, so the annual period is the
reporting period for the temporary development environment. This unfiltered
budget includes all account spending, not only Praxis, and does not stop services
or cap charges. Its
email subscriber is a sensitive runtime input and must not be committed. Supply
it when planning and applying:

```shell
export TF_VAR_budget_notification_email="you@example.com"
make tofu-plan-bootstrap
make tofu-apply-bootstrap CONFIRM=apply-bootstrap
```

Notifications fire at 50% and 100% of actual annual spend. Apply the saved plan
only after its budget address and resource actions have been reviewed.
