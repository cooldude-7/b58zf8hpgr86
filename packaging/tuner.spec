# PyInstaller spec -- build with:  pyinstaller packaging/tuner.spec
# Produces dist/TorqueTune/TorqueTune.exe (onedir: faster startup than onefile)
import os
block_cipher = None
root = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))

a = Analysis(
    [os.path.join(root, "packaging", "launcher.py")],
    pathex=[root],
    # the shift coordinator is the user's own source and is imported at
    # run time, so it ships as data, not as a frozen module
    datas=[(os.path.join(root, "tools", "shift"), os.path.join("tools", "shift")),
           # window icon and About-box art, looked up by tuner/ui/assets.py
           (os.path.join(root, "tuner", "ui", "assets"),
            os.path.join("tuner", "ui", "assets"))],
    hiddenimports=["pyqtgraph", "PySide6.QtOpenGL"],
    excludes=["tkinter", "matplotlib.tests", "numpy.tests"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TorqueTune",
          console=False,
          icon=os.path.join(root, "tuner", "ui", "assets", "torquetune.ico"))
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="TorqueTune")
