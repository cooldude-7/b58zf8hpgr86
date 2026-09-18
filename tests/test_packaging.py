"""The Windows install path.

These are static checks: nothing here can run a PowerShell script on a
Linux CI box. What they do catch is the drift that silently breaks an
install -- a renamed exe, a script that installs something the uninstaller
never removes, a build that stops calling the installer at all.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"
INSTALL = (PKG / "install.ps1").read_text()
UNINSTALL = (PKG / "uninstall.ps1").read_text()
BUILD = (PKG / "build.bat").read_text()


def test_build_installs():
    assert "pyinstaller --noconfirm packaging\\tuner.spec" in BUILD
    assert "install.ps1" in BUILD
    assert "-NoDesktop" in BUILD, "the /nodesktop switch must reach the script"


def test_build_does_not_close_on_failure():
    """Run by double-click, the window shuts the instant the script ends and
    takes the error with it."""
    assert BUILD.rstrip().endswith("pause")
    assert "INSTALL FAILED" in BUILD


def test_install_can_be_run_on_its_own():
    """A build that already exists should not have to be built again just to
    get a shortcut."""
    bat = (PKG / "install.bat").read_text()
    assert "install.ps1" in bat and "ExecutionPolicy Bypass" in bat
    assert '%~dp0\\..' in bat, "must work when double-clicked from packaging\\"


def test_spec_embeds_the_icon():
    spec = (PKG / "tuner.spec").read_text()
    assert "torquetune.ico" in spec
    assert (ROOT / "tuner" / "ui" / "assets" / "torquetune.ico").exists()


def test_shortcuts_take_their_icon_from_the_exe():
    """Not from a loose .ico: the exe carries the icon already, and a second
    copy is one more thing to get out of step."""
    assert '$sc.IconLocation = "$exe,0"' in INSTALL


@pytest.mark.parametrize("what", ["Start Menu\\Programs", "GetFolderPath(\"Desktop\")",
                                  "HKCU:\\Software\\Classes\\.tune",
                                  "CurrentVersion\\Uninstall"])
def test_everything_installed_is_also_removed(what):
    key = what.split("\\")[-1].split("(")[0]
    assert key in INSTALL and key in UNINSTALL, key


def test_association_passes_the_file_to_the_app():
    m = re.search(r'shell\\open\\command.*?-Value "(.*?)"\s*$', INSTALL, re.S | re.M)
    assert m and "%1" in m.group(1), "double-clicking a .tune must pass its path"


def test_uninstall_leaves_a_stolen_association_alone():
    """If another program has taken .tune since, removing the key would
    break it rather than tidy up after us."""
    assert "$cur -eq $progId" in UNINSTALL


def test_app_survives_a_bad_file_on_the_command_line(qapp, tmp_path, monkeypatch):
    """The association hands the app whatever the user double-clicked. A
    windowed build has no console, so a raised exception is a silent death."""
    from PySide6.QtWidgets import QMessageBox

    from tuner.app import open_tune

    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    bad = tmp_path / "broken.tune"
    bad.write_text("{ not json")
    assert open_tune(str(bad)) is None
    assert shown and "broken.tune" in shown[0]

    missing = tmp_path / "gone.tune"
    assert open_tune(str(missing)) is None
    assert len(shown) == 2


def test_a_good_file_still_opens(qapp, tmp_path):
    from tuner.app import open_tune
    from tuner.core.tune import default_tune

    path = tmp_path / "ok.tune"
    default_tune().save(path)
    assert open_tune(str(path)) is not None


@pytest.mark.parametrize("name", ["build.bat", "install.bat", "install.ps1", "uninstall.ps1"])
def test_windows_scripts_are_crlf(name):
    """An LF-only .bat makes cmd mis-parse a block and skip the rest of the
    file without a word of complaint -- the build looks fine and nothing is
    installed. .gitattributes pins the checkout; this pins what is committed."""
    raw = (PKG / name).read_bytes()
    assert raw.count(b"\r\n") > 0
    assert raw.count(b"\n") == raw.count(b"\r\n"), "bare LF in a Windows script"


def test_gitattributes_pins_the_line_endings():
    attrs = (ROOT / ".gitattributes").read_text()
    for pat in ("*.bat", "*.ps1"):
        assert f"{pat}  text eol=crlf" in attrs.replace("\t", " "), pat


def test_build_avoids_multiline_blocks():
    """The construct that broke: a ( ) block spanning lines. Labels and goto
    survive either line ending."""
    for line in BUILD.splitlines():
        assert not line.rstrip().endswith("("), line


def test_install_does_not_lean_on_psscriptroot_in_param_defaults():
    """Windows PowerShell hands back an empty $PSScriptRoot when it is read
    from a param() default, and the script dies on Split-Path before doing
    anything. Resolve the directory in the body, with fallbacks."""
    param_block = INSTALL[INSTALL.index("param("):INSTALL.index(")", INSTALL.index("param("))]
    assert "PSScriptRoot" not in param_block
    assert "$MyInvocation.MyCommand.Definition" in INSTALL, "no fallback for the script path"


def test_install_finds_the_build_relative_to_itself():
    """Double-clicked from Explorer the working directory is anyone's guess,
    so the default source must be derived from the script's own location."""
    assert '$Source = Join-Path $repo "dist\\TorqueTune"' in INSTALL
