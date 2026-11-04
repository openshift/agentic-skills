"""Run the create-backup shell behavior suite in the repository unit job."""

from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by the skill scripts")
def test_create_backup_scripts():
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "evals/skills/create-backup/test-scripts.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
