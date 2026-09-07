"""Check that runtime packaging refuses accidental host execution."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("opt_in", [None, "", "0", "true"])
def test_runtime_packaging_requires_build_opt_in(opt_in: str | None) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/package-python-runtime.sh"
    bash = shutil.which("bash")
    assert bash is not None
    environment = {
        key: value for key, value in os.environ.items() if key != "PRAXIS_CONTAINER_BUILD"
    }
    if opt_in is not None:
        environment["PRAXIS_CONTAINER_BUILD"] = opt_in
    result = subprocess.run(  # noqa: S603 -- fixed repository script, no valid build opt-in
        [bash, str(script)], env=environment, capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "Run this script only through backend/Containerfile." in result.stderr
