# Security scanning

```bash
make security SCAN=dependencies
make agent-image
make security                       # dependencies and the local ARM64 image
```

`SCAN=image` scans only the existing `AGENT_IMAGE` (default `praxis-agent:dev`).
Build the intended image first; scanning does not rebuild, publish, or inspect
AWS. `CONTAINER_TOOL=docker` selects Docker instead of Podman. CI builds and
scans a native AMD64 image; scan the ARM64 deployment image locally before
publication because architecture-specific packages can differ. Hosted checks
require an available GitHub Actions allowance.

The digest-pinned Trivy container scans `uv.lock` and
`frontend/package-lock.json`, including development dependencies, plus the
fully pinned `backend/lambda/requirements.lock` copied as `requirements.txt`
for discovery. Image scanning inspects OS packages and installed language
dependencies from a local archive, without executing the target image.
See Trivy's [Python coverage](https://trivy.dev/docs/latest/guide/coverage/language/python/)
and [container archive support](https://trivy.dev/docs/latest/guide/target/container_image/).

`make security` fails for HIGH/CRITICAL vulnerabilities, including unfixed
findings, and scanner/database errors. It attempts both scans when a scanner
returns findings. Reports are `build/security/dependencies.json` and
`build/security/image.json`; each selected scan removes its previous report
before starting. A missing or partial report after an error is not a passing scan.
Reports contain HIGH/CRITICAL findings only, not a full security assessment.

The scanner downloads public vulnerability databases into `.cache/trivy`;
this network-dependent check stays separate from `make check`. Only staged
lockfiles/image contents, the report directory, and its database cache are
mounted. Neither AWS credentials nor the container socket is exposed.

For each finding, review the advisory, installed/fixed versions, affected
artifact, and reachable behavior. Update the relevant lockfile or base image,
run `make check`, rebuild artifacts, and rescan. Do not use automatic audit
fixes or blanket ignores. An unfixed finding needs an explicit risk decision,
not a silently passing gate. Lambda's AWS-managed runtime and service-side
dependencies are outside the lockfile scan; vulnerability databases and package
detection are incomplete, and a passing scan is not proof of safety.

## Runtime packaging

Use the official Python 3.13 slim Trixie base to retain the locked Python
environment while consuming Debian 13 packages. Debian records Trixie fixes
for [SQLite CVE-2025-7458](https://security-tracker.debian.org/tracker/CVE-2025-7458)
and [util-linux CVE-2026-53613](https://security-tracker.debian.org/tracker/CVE-2026-53613).
Changing the base does not resolve every advisory. Rebuild and test both native
and ARM64 images because system libraries can affect Python binary extensions.

The Runtime does not install packages while serving requests. The Containerfile
removes pip and its `ensurepip` bootstrap bundle after the locked installation,
and excludes uv/uvx from the finished filesystem. This also removes pip's
vendored libraries and their bundled metadata; do not add unrelated packages
to `uv.lock` to patch dependencies carried by build tooling. Verify with the
container health/packaging smoke check and an ARM64 image scan. Debian package
findings still require their own vendor-advisory and reachability review.

The build removes inherited setuid/setgid bits under `/usr`, including utilities
such as `mount`, `su`, and `passwd`. The application runs as UID 10001 and has no
need for these utilities to elevate its identity. The container smoke check
verifies those bits are absent. This hardening does not change package versions
or suppress scan findings. The [container risk review](container-risk-review.md)
records advisory-specific evidence and its limits; it is not a risk acceptance.
