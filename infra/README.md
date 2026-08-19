# Infrastructure

OpenTofu configuration is separated into bootstrap resources, development
environment configuration, and reusable modules.

The bootstrap and development directories are independent root modules. Both
require OpenTofu 1.12.5 and AWS provider 6.60.0 exactly; upgrade their version
constraints and provider lock files together. Reusable modules declare only the
minimum provider capabilities they need and do not select provider versions.
