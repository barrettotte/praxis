# Container vulnerability review

Status: **open; no accepted exceptions or scanner suppressions**.

This review applies to the local ARM64 image identified in
[scan evidence](evidence/security-scanning.json), not the deployed Runtime image.
The scan reports 51 HIGH and 3 CRITICAL package/advisory pairs across 18 unique
advisories, with no fixed versions listed. Revalidate these observations when
the image or application changes; package presence is not proof of exploitation,
and an unused application path is not proof that vulnerable code is unreachable.

## Verified image properties

Network-disabled local inspection confirms UID 10001, 64-bit Perl pointer and
integer sizes, missing `Archive::Tar`, `File::GlobMapper`, and `Storable` modules,
no configured `/etc/fstab` entries, and no `/usr/lib/systemd/systemd-homed` binary.
There are no setuid/setgid regular files under `/usr`; `/bin` and `/sbin` resolve
inside `/usr`. Native and ARM64 health/packaging smoke checks pass.

Application-source inspection found no direct Perl, shell-command, SQLite/FTS5,
archive-extraction, or ACL-manipulation calls in the agent, domain, catalog, or
tool code. The configured Gateway client uses HTTP and an allowlist of four
read-only catalog tools, not a shell transport. This is a reachability inference,
not an exhaustive audit of transitive SDKs, native libraries, or the managed host.

## Advisory assessment

Links below point to Debian's advisory assessments. Component and architecture
observations are local evidence, separate from Debian's package-level status.

| Advisory | Affected behavior | Image assessment |
| --- | --- | --- |
| [CVE-2026-8376](https://security-tracker.debian.org/tracker/CVE-2026-8376) (critical) | Perl regex overflow on 32-bit builds | Architecture prerequisite absent: pointer and integer sizes are 8 bytes. |
| [CVE-2026-42496](https://security-tracker.debian.org/tracker/CVE-2026-42496) (critical), [CVE-2026-42497](https://security-tracker.debian.org/tracker/CVE-2026-42497), [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | `Archive::Tar` symlink/hardlink extraction escapes and memory exhaustion | Affected module absent; Perl reports that it cannot locate the module. |
| [CVE-2026-48962](https://security-tracker.debian.org/tracker/CVE-2026-48962), [CVE-2026-57433](https://security-tracker.debian.org/tracker/CVE-2026-57433) | `File::GlobMapper` evaluation and `Storable` deserialization | Both affected modules absent; module-load failures explicitly report missing files. |
| [CVE-2026-13221](https://security-tracker.debian.org/tracker/CVE-2026-13221) (critical), [CVE-2026-57432](https://security-tracker.debian.org/tracker/CVE-2026-57432) | Perl regex matching and pack/unpack size handling | Perl remains installed. No application invocation identified; further reachability review or explicit risk acceptance needed. |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642), [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408), [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409), [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | Privileged mount helpers, `nsenter`, and restricted mount handling | Non-root execution, absent setid bits, and empty fstab limit privilege prerequisites. No application mount/nsenter path identified; this does not establish every managed-host privilege boundary. |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | `systemd-homed` local privilege escalation | Affected service executable absent; entry point is the instrumented Python application. |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | `infocmp` processing crafted terminal descriptions | No application invocation identified; affected package remains installed. |
| [CVE-2026-11822](https://security-tracker.debian.org/tracker/CVE-2026-11822), [CVE-2026-11824](https://security-tracker.debian.org/tracker/CVE-2026-11824) | SQLite FTS5 processing crafted databases | Application uses DynamoDB, not SQLite/FTS5. Native library remains installed; optional SDK paths have not been exhaustively audited. |
| [CVE-2026-41992](https://security-tracker.debian.org/tracker/CVE-2026-41992) | `gzip` processing crafted LZW/LZH streams | No application invocation or archive-upload workflow identified; package remains installed. |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | Privileged ACL operations on attacker-controlled paths | Non-root application has no identified ACL manipulation path; indirect native-library use remains a review limit. |

## Release decision

Keep the HIGH/CRITICAL gate failing until findings are remediated or exceptions
are explicitly reviewed and approved. Do not force-remove Essential Debian
packages, mix distribution repositories, or broadly ignore unfixed findings to
obtain a passing scan.

Any proposed exception must name its advisory and package scope, image identity,
supporting evidence, residual exposure, owner, expiration, and revalidation
conditions. Verified missing components and architecture mismatches can support
narrow applicability exceptions; "no application path found" requires a separate
risk decision. This document grants neither kind of exception. Publication and
deployment require their normal review and verification.
