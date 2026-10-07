"""The backend must import from the project root without legacy path setup."""

import os
import subprocess
import sys
from pathlib import Path


def test_backend_imports_from_project_root():
    project_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.app.main import PROJECT_ROOT; print(PROJECT_ROOT)",
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == project_root
