"""Verify image publication identity and confirmation without registry access."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FAKE_TOOL = """
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with Path(os.environ["TEST_CALLS"]).open("a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
if name == "container":
    if args[:2] == ["image", "inspect"]:
        template = args[args.index("--format") + 1]
        if template == "{{.Id}}":
            print(os.environ["TEST_IMAGE_ID"])
        elif template == "{{.Architecture}}":
            print(os.environ["TEST_ARCH"])
        else:
            print("unrelated-git-revision")
    elif args[0] == "login":
        sys.stdin.read()
elif name == "tofu":
    print('{"agent":"registry.invalid/praxis"}')
elif name == "jq":
    print(json.load(sys.stdin)["agent"])
elif name == "aws":
    if "list-images" in args:
        print(os.environ["TEST_REMOTE_DIGEST"])
    elif "get-login-password" in args:
        print("synthetic-password")
    elif "describe-images" in args:
        print("sha256:" + "b" * 64)
    else:
        sys.exit(1)
"""


@pytest.mark.parametrize(
    ("action", "confirmed", "architecture", "image_id", "remote", "success", "push"),
    [
        ("preview", False, "arm64", "sha256:" + "a" * 64, "None", True, False),
        ("push", True, "arm64", "sha256:" + "a" * 64, "None", True, True),
        ("push", True, "arm64", "sha256:" + "a" * 64, "sha256:existing", True, False),
        ("push", False, "arm64", "sha256:" + "a" * 64, "None", False, False),
        ("preview", False, "amd64", "sha256:" + "a" * 64, "None", False, False),
        ("preview", False, "arm64", "invalid", "None", False, False),
    ],
)
def test_publication_uses_content_identity_and_explicit_confirmation(
    tmp_path: Path,
    action: str,
    confirmed: bool,
    architecture: str,
    image_id: str,
    remote: str,
    success: bool,
    push: bool,
) -> None:
    for name in ("aws", "tofu", "jq", "container"):
        tool = tmp_path / name
        tool.write_text(f"#!{sys.executable}\n{FAKE_TOOL}")
        tool.chmod(0o700)
    calls = tmp_path / "calls"
    result = subprocess.run(  # noqa: S603 - repository script with isolated fake cloud tools
        ["/bin/bash", str(Path(__file__).parents[2] / "scripts/push-agent-image-dev.sh")],
        env=os.environ
        | {
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "ACTION": action,
            "CONFIRM": "push-agent-image-dev" if confirmed else "",
            "CONTAINER_TOOL": str(tmp_path / "container"),
            "TOFU": str(tmp_path / "tofu"),
            "TEST_CALLS": str(calls),
            "TEST_IMAGE_ID": image_id,
            "TEST_ARCH": architecture,
            "TEST_REMOTE_DIGEST": remote,
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is success, result.stderr
    invocations = (
        [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    )
    target = "registry.invalid/praxis:image-" + "a" * 64
    assert (["container", "push", target] in invocations) is push
    if success:
        assert target in result.stdout
        assert "unrelated-git-revision" in result.stdout
    else:
        assert not any(call[0] in {"aws", "tofu"} for call in invocations)
    if push:
        assert ["container", "tag", image_id, target] in invocations
        assert ["container", "logout", "registry.invalid"] in invocations
    else:
        assert not any("get-login-password" in call for call in invocations)
