"""Exercise the security command without containers or vulnerability databases."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("engine", ["docker", "podman"])
@pytest.mark.parametrize(
    ("scanner_status", "failed_target", "report_kind"),
    [
        (0, "fs", "complete"),
        (1, "fs", "complete"),
        (2, "fs", "complete"),
        (1, "image", "complete"),
        (2, "image", "complete"),
        (1, "docker-archive:/scan/agent.tar", "complete"),
        (2, "docker-archive:/scan/agent.tar", "complete"),
        (0, "fs", "missing"),
        (0, "fs", "no_os"),
        (0, "fs", "no_libc6"),
        (0, "fs", "no_zlib1g"),
    ],
)
def test_security_scans_both_targets_and_propagates_failure(
    tmp_path: Path, scanner_status: int, engine: str, failed_target: str, report_kind: str
) -> None:
    write_reports = report_kind != "missing"
    report_content = json.dumps(
        {
            "Metadata": {
                "OS": {"Family": "none" if report_kind == "no_os" else "ubuntu", "Name": "24.04"}
            },
            "Results": [
                {
                    "Class": "os-pkgs",
                    "Packages": [
                        {"Name": name}
                        for name in ("libc6", "zlib1g")
                        if report_kind != f"no_{name}"
                    ],
                }
            ],
        }
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(Path(__file__).parents[2] / "scripts/security.sh", scripts / "security.sh")
    for name in ("uv.lock", "frontend/package-lock.json", "backend/lambda/requirements.lock"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic lockfile")
    reports = tmp_path / "build/security"
    reports.mkdir(parents=True)
    for name in ("dependencies.json", "image.json", "image-binaries.json"):
        (reports / name).write_text("stale")
    calls = tmp_path / "calls"
    container = tmp_path / engine
    container.write_text(
        "#!/bin/sh\n# Record scanner calls and simulate scan reports and exit codes.\n"
        'printf "%s\\n" "$*" >> "$TEST_CALLS"\n'
        'if [ "$TEST_WRITE_REPORTS" = 1 ]; then\n'
        '  case " $* " in\n'
        '    *" fs "*) report=dependencies ;;\n'
        '    *" image --input "*) report=image ;;\n'
        '    *" docker-archive:/scan/agent.tar "*) report=image-binaries ;;\n'
        "    *) report= ;;\n"
        "  esac\n"
        '  if [ -n "$report" ]; then printf "%s" "$TEST_REPORT" > "$TEST_REPORT_DIR/$report.json"; fi\n'
        "fi\n"
        'if [ "$1" = run ]; then\n'
        '  case " $* " in *" $TEST_FAILED_TARGET "*) exit "$TEST_SCAN_STATUS" ;; esac\n'
        "fi\n"
        "exit 0\n"
    )
    container.chmod(0o700)
    result = subprocess.run(  # noqa: S603 - fixed repository script and isolated fake tool
        ["/bin/bash", str(scripts / "security.sh")],
        env=os.environ
        | {
            "CONTAINER_TOOL": str(container),
            "TEST_CALLS": str(calls),
            "TEST_SCAN_STATUS": str(scanner_status),
            "TEST_FAILED_TARGET": failed_target,
            "TEST_WRITE_REPORTS": str(int(write_reports)),
            "TEST_REPORT_DIR": str(reports),
            "TEST_REPORT": report_content,
        },
        capture_output=True,
        check=False,
    )
    assert result.returncode == (0 if scanner_status == 0 and report_kind == "complete" else 1)
    invocations = calls.read_text().splitlines()
    scans = [line for line in invocations if line.startswith("run ") and " convert " not in line]
    assert len(scans) == 3
    assert "fs --include-dev-deps /scan/locks" in scans[0]
    assert "image --input /scan/agent.tar" in scans[1]
    for scan in scans:
        assert f"--user {os.getuid()}:{os.getgid()}" in scan
        assert ("--userns=keep-id" in scan) == (engine == "podman")
        assert "--ignore-unfixed" not in scan
        assert "--only-fixed" not in scan
        assert "/var/run/docker.sock" not in scan
        assert "--tmpfs /tmp:rw,mode=1777" in scan
    for scan in scans[:2]:
        assert "--scanners vuln --severity HIGH,CRITICAL --exit-code 1" in scan
        assert "--env" not in scan
    assert "docker-archive:/scan/agent.tar --fail-on high" in scans[2]
    assert "--env GRYPE_DB_CACHE_DIR=/cache --env GRYPE_CHECK_FOR_APP_UPDATE=false" in scans[2]
    assert len(list(reports.iterdir())) == (3 if write_reports else 0)
    assert all(report.read_text() == report_content for report in reports.iterdir())
    exports = [line for line in invocations if line.startswith("save ")]
    assert len(exports) == 1
    assert "--format" not in exports[0]
    assert "--output" in exports[0]
