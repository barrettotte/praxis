"""Check live endpoint resolution without contacting AWS."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

LIBRARY = Path(__file__).resolve().parents[2] / "scripts/smoke/lib/dev-smoke.sh"


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ({"status": "READY", "liveVersion": "62"}, "62"),
        ({"status": "UPDATING", "liveVersion": "60"}, None),
        ({"status": "UPDATE_FAILED", "liveVersion": "60"}, None),
        ({"status": "READY"}, None),
        ({"status": "READY", "liveVersion": ""}, None),
    ],
)
def test_live_endpoint_version(endpoint: dict[str, str], expected: str | None) -> None:
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(  # noqa: S603 -- fixed script with synthetic fixture arguments
        [
            bash,
            "-c",
            'source "$1"; praxis_tofu_output() { printf "test"; }; '
            'endpoint="$2"; aws() { printf "%s" "$endpoint"; }; '
            "praxis_runtime_endpoint_version",
            "test",
            str(LIBRARY),
            json.dumps(endpoint),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if expected is None:
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
