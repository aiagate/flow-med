from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("example", "expected_result"),
    [
        ("basic_usage.py", "Result: Hello, User 42!"),
        ("di_usage.py", "Result: Retrieved: User_123_from_DB"),
    ],
)
def test_usage_example_runs_successfully(example: str, expected_result: str) -> None:
    result = subprocess.run(
        [sys.executable, PROJECT_ROOT / "examples" / example],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert expected_result in result.stdout.splitlines()
