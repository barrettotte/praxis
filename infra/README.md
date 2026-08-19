# Infrastructure

OpenTofu configuration is separated into bootstrap resources, development
environment configuration, and reusable modules.

The bootstrap and development directories are independent root modules. Both
require OpenTofu 1.12.5 and AWS provider 6.60.0 exactly; upgrade their version
constraints and provider lock files together. Reusable modules declare only the
minimum provider capabilities they need and do not select provider versions.

## Naming and tagging

AWS names use lowercase kebab case. Environment-scoped resources follow
`praxis-<environment>-<component>`; globally unique durable resources append
the account and region without hard-coding either value. Reusable modules accept
names from their calling root rather than inventing independent prefixes.

Every tagged AWS resource receives these provider-level tags:

- `Project`: `praxis`
- `Environment`: lifecycle boundary such as `bootstrap` or `dev`
- `ManagedBy`: `OpenTofu`

Resources add a `Name` tag matching their AWS name and a concise `Purpose` tag
where that improves cost and operations visibility. Do not place identities,
credentials, or other sensitive values in names or tags.

## Encryption keys

Bootstrap state and development container images use explicit AWS
service-managed AES-256 encryption. Praxis does not create customer-managed KMS
keys unless a resource demonstrates a requirement such as a custom key policy,
cross-account access, or independent key rotation and audit control. This keeps
the development environment simpler and avoids unnecessary key cost.
