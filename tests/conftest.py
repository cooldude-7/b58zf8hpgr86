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


# Every installation gets its own randomly generated engine -- that is the
# point of plant_seed(), because a shared plant means the first person to
# solve a lab has solved it for everybody. It is also a trap for tests: an
# unseeded SimulatedECU picks up whatever engine this machine happens to
# have, which is stable locally and random on a fresh CI runner. A test
# then passes deterministically for the author and fails intermittently
# for everyone else, which is the worst possible shape for a flake.
#
# Tests get a fixed engine. Anything that genuinely means to exercise the
# per-install behaviour asks for it explicitly.
TEST_PLANT_SEED = 20260920


@pytest.fixture(autouse=True)
def _deterministic_plant(monkeypatch):
    """Pin the per-installation engine for the whole suite.

    Pinning individual SimulatedECU calls in tests is not enough, because
    production code makes its own: MainWindow builds one in its
    constructor with no seed, so any test that opens a window gets this
    machine's engine. Patching the mint itself is the only place that
    covers every construction, including the ones inside the app.

    Without this the suite is deterministic for whoever wrote it and
    random on a fresh runner -- so a flake looks like "CI is broken"
    rather than like a bug, and gets re-run instead of read.
    """
    monkeypatch.setattr("tuner.core.sim_ecu.plant_seed",
                        lambda: TEST_PLANT_SEED)


@pytest.fixture
def sim(qapp, tune):
    from tuner.core.sim_ecu import SimulatedECU
    s = SimulatedECU(tune, seed=TEST_PLANT_SEED)
    s.connect_ecu()
    yield s
    s.disconnect_ecu()
