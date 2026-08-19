# Development environment

This independent OpenTofu root owns temporary Praxis application resources in
`us-east-1`. It stores state in the encrypted, versioned bootstrap S3 bucket and
uses native S3 state locking. Initialize it after the bootstrap stack:

```shell
make tofu-init-dev
```

All resources use the `praxis-dev` name prefix and inherit the required
`Project`, `Environment`, and `ManagedBy` tags. Coding agents may plan and
inspect this environment, but the user must run every apply or destroy command
manually.

The agent image repository uses immutable tags, scan-on-push, S3-managed
AES-256 encryption, and a lifecycle policy that removes untagged images after
seven days and retains at most ten images. `force_delete` permits the guarded
development teardown target to remove the repository and its temporary images.
