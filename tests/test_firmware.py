"""Build the firmware for the host and run its test suites.

The C in fw/ is the code that will run on the engine. It is ordinary C
with no peripheral access above the HAL, so it compiles and runs here,
and that is the only reason any of it can be trusted before there is
hardware to try it on.

Skipped, not failed, when cmake or a C compiler is missing: a Python-only
checkout is still a valid way to work on the tuner.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "fw"
BUILD = ROOT / "build" / "fw"

needs_toolchain = pytest.mark.skipif(
    shutil.which("cmake") is None or shutil.which("cc") is None,
    reason="no C toolchain available")


@pytest.fixture(scope="session")
def fw_build():
    subprocess.run(["cmake", "-S", str(FW), "-B", str(BUILD),
                    "-DCMAKE_BUILD_TYPE=Release"],
                   check=True, capture_output=True, text=True)
    subprocess.run(["cmake", "--build", str(BUILD), "-j", "4"],
                   check=True, capture_output=True, text=True)
    return BUILD


@needs_toolchain
@pytest.mark.parametrize("suite", ["test_decoder", "test_sched", "test_model",
                                   "test_fuel", "test_monitor", "test_ecu"])
def test_firmware_suite(fw_build, suite):
    exe = fw_build / suite
    r = subprocess.run([str(exe), str(FW / "tests" / "data" / "golden.txt")],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        pytest.fail(f"{suite} failed:\n{r.stdout}\n{r.stderr}")


@needs_toolchain
def test_golden_file_matches_the_python_model(tmp_path):
    """The C is checked against fw/tests/data/golden.txt, so that file has
    to still be what the Python model produces. A stale golden file means
    the cross-check is comparing the port against a model nobody runs."""
    out = tmp_path / "golden.txt"
    script = (ROOT / "tools" / "gen_golden.py").read_text().replace(
        'OUT = Path(__file__).resolve().parents[1] / "fw" / "tests" / "data" / "golden.txt"',
        f'OUT = Path(r"{out}")')
    gen = tmp_path / "gen.py"
    gen.write_text(script.replace(
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))',
        f'sys.path.insert(0, r"{ROOT}")'))
    subprocess.run([sys.executable, str(gen)], check=True, capture_output=True)
    current = (FW / "tests" / "data" / "golden.txt").read_text()
    assert out.read_text() == current, (
        "fw/tests/data/golden.txt is stale. Run tools/gen_golden.py and "
        "commit the result with whatever changed the model.")
