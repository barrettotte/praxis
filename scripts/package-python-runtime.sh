#!/usr/bin/env bash
# Assemble the application-specific Python runtime inside the container build stage.
set -euo pipefail

# Build engines need not expose container marker files. Explicit opt-in prevents
# accidental host execution; it is not an isolation or authorization boundary.
[[ "${PRAXIS_CONTAINER_BUILD:-}" == "1" ]] || {
  printf 'Run this script only through backend/Containerfile.\n' >&2
  exit 2
}
[[ ! -e /runtime && ! -L /runtime ]] || {
  printf 'Refusing to reuse /runtime staging directory.\n' >&2
  exit 2
}
mkdir -p /runtime/usr /runtime/etc /runtime/tmp /runtime/var/lib/dpkg/status.d
chmod 1777 /runtime/tmp
ln -s usr/lib /runtime/lib
if [[ -d /usr/lib64 ]]; then
  ln -s usr/lib64 /runtime/lib64
fi
cp -L /etc/os-release /runtime/etc/os-release
# Trivy uses lsb-release for Ubuntu detection; os-release alone is insufficient.
cp /etc/lsb-release /runtime/etc/lsb-release
cp -a /etc/ssl /runtime/etc/
ln -s /usr/share/zoneinfo/Etc/UTC /runtime/etc/localtime
printf 'nonroot:x:65532:65532:Runtime:/tmp:/sbin/nologin\n' > /runtime/etc/passwd
printf 'nonroot:x:65532:\n' > /runtime/etc/group
printf 'hosts: files dns\n' > /runtime/etc/nsswitch.conf
cp -a /usr/local /runtime/usr/local

# These optional modules are outside the serving contract. Remove their actual
# code, not just package records, so their native libraries are unnecessary.
python_lib=/runtime/usr/local/lib/python3.13
for module in curses dbm ensurepip idlelib sqlite3 tkinter turtledemo test site-packages; do
  rm -rf "${python_lib:?}/${module}"
done
mkdir -p "${python_lib}/site-packages"
find "${python_lib}/lib-dynload" -type f \
  \( -name '_curses*.so' -o -name '_dbm*.so' -o -name '_gdbm*.so' \
     -o -name '_sqlite3*.so' -o -name '_tkinter*.so' -o -name '_uuid*.so' \
     -o -name 'readline*.so' \) -delete
find /runtime/usr/local/bin -type f -name 'pip*' -delete
find /runtime/usr/local/bin -type l -name 'pip*' -delete
find /runtime/usr/local/lib -type f -name 'libpython*.a' -delete

# Keep runtime library payloads, data, package records and licenses together.
# No compiler, shell, installer, or package-manager executable enters the rootfs.
for package in base-files libc6 libgcc-s1 libstdc++6 libssl3t64 zlib1g libbz2-1.0 libffi8 liblzma5 ca-certificates tzdata; do
  dpkg-query --status "${package}" > "/runtime/var/lib/dpkg/status.d/${package}"
  while IFS= read -r path; do
    case "${path}" in
      /usr/lib/*.so* | /lib/*.so* | /usr/lib64/ld-* | /lib64/ld-* | \
      /usr/lib/*/gconv/* | /usr/lib/ssl/* | /usr/share/doc/*/copyright | \
      /usr/share/zoneinfo/* | /usr/share/ca-certificates/*)
        cp -a --parents "${path}" /runtime/
        ;;
    esac
  done < <(dpkg-query --listfiles "${package}")
done
