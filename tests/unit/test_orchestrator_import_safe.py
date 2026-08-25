"""Import-safety guard for the orchestrator module.

The orchestrator must import with no OpenRouter key set. Constructing the model at
module scope requires a key and previously broke CI (no ``OPENROUTER_API_KEY``
secret there); ``build_orchestrator`` defers construction to call time. This mirrors
the subprocess pattern in ``tests/unit/test_notion_mapper.py``.
"""

import os
import subprocess
import sys


def test_orchestrator_importable_without_openrouter_api_key() -> None:
    env = os.environ.copy()
    env["OPENROUTER_API_KEY"] = ""
    result = subprocess.run(
        [sys.executable, "-c", "import webtonotion.agents.orchestrator"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
