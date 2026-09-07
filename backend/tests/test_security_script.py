"""Exercise the security command without containers or vulnerability databases."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("scanner_status", [0, 1, 2])
@pytest.mark.parametrize("engine", ["docker", "podman"])
def test_security_scans_both_targets_and_propagates_failure(
    tmp_path: Path, scanner_status: int, engine: str
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(Path(__file__).parents[2] / "scripts/security.sh", scripts / "security.sh")
    for name in ("uv.lock", "frontend/package-lock.json", "backend/lambda/requirements.lock"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic lockfile")
    reports = tmp_path / "build/security"
    reports.mkdir(parents=True)
    for name in ("dependencies.json", "image.json"):
        (reports / name).write_text("stale")
    calls = tmp_path / "calls"
    container = tmp_path / engine
    container.write_text(
        "#!/bin/sh\n# Record scanner calls and simulate a dependency scan result.\n"
        'printf "%s\\n" "$*" >> "$TEST_CALLS"\n'
        'case " $* " in *" fs "*) exit "$TEST_SCAN_STATUS" ;; esac\n'
    )
    container.chmod(0o700)
    result = subprocess.run(  # noqa: S603 - fixed repository script and isolated fake tool
        ["/bin/bash", str(scripts / "security.sh")],
        env=os.environ
        | {
            "CONTAINER_TOOL": str(container),
            "TEST_CALLS": str(calls),
            "TEST_SCAN_STATUS": str(scanner_status),
        },
        capture_output=True,
        check=False,
    )
    assert result.returncode == (0 if scanner_status == 0 else 1)
    invocations = calls.read_text().splitlines()
    scans = [line for line in invocations if line.startswith("run ")]
    assert len(scans) == 2
    assert "fs --include-dev-deps /scan/locks" in scans[0]
    assert "image --input /scan/agent.tar" in scans[1]
    for scan in scans:
        assert f"--user {os.getuid()}:{os.getgid()}" in scan
        assert ("--userns=keep-id" in scan) == (engine == "podman")
        assert "--scanners vuln --severity HIGH,CRITICAL --exit-code 1" in scan
        assert "--ignore-unfixed" not in scan
        assert "/var/run/docker.sock" not in scan
        assert "--env" not in scan
    assert not list(reports.iterdir())
    exports = [line for line in invocations if line.startswith("save ")]
    assert len(exports) == 1
    assert "--format" not in exports[0]
    assert "--output" in exports[0]
