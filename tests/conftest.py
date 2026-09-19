"""Test setup shared by every test in this directory.

Qt must be told to run headless BEFORE PySide6 is imported anywhere, so
this happens at module scope, not in a fixture.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LAMBDAONE_NO_AUDIO", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest        # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session. Qt does not support a second
    one in the same process, so it is never torn down."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def tune():
    from tuner.core.tune import default_tune
    return default_tune()


@pytest.fixture
def sim(qapp, tune):
    from tuner.core.sim_ecu import SimulatedECU
    s = SimulatedECU(tune)
    s.connect_ecu()
    yield s
    s.disconnect_ecu()
