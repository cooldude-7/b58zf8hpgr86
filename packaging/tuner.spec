# PyInstaller spec -- build with:  pyinstaller packaging/tuner.spec
# Produces dist/TorqueTune/TorqueTune.exe (onedir: faster startup than onefile)
import os
block_cipher = None
root = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))

a = Analysis(
    [os.path.join(root, "tuner", "__main__.py")],
    pathex=[root],
    hiddenimports=["pyqtgraph", "PySide6.QtOpenGL"],
    excludes=["tkinter", "matplotlib.tests", "numpy.tests"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TorqueTune",
          console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="TorqueTune")
