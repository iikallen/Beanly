import subprocess
import sys
from pathlib import Path


def test_integration_worker_registers_all_related_models() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from beanly.modules.integrations import worker; "
            "from sqlalchemy.orm import configure_mappers; configure_mappers()",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_outbox_worker_registers_all_related_models() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from beanly.core.events import worker; "
            "from sqlalchemy.orm import configure_mappers; configure_mappers()",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
