"""The narrative test scripts, run as subprocesses.

Each of these builds its own QApplication and prints a readable report, so
they stay useful to run by hand. Qt allows only one QApplication per
process, which is the other reason they get a process each.
"""
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = ["test_tableops.py", "test_sim.py", "test_editor_gui.py", "test_live.py"]


@pytest.mark.parametrize("script", SCRIPTS)
def test_script(script):
    r = subprocess.run([sys.executable, str(HERE / script)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        pytest.fail(f"{script} failed:\n{r.stdout}\n{r.stderr}")
