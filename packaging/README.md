# Building and installing on Windows

Nothing installs itself. These scripts run on your machine, from the repo.

```bat
git pull
packaging\build.bat
```

That builds `dist\TorqueTune\TorqueTune.exe` and then installs it for the
current user: a copy under `%LOCALAPPDATA%\Programs\TorqueTune`, a Start
menu entry, a desktop shortcut, `.tune` files associated, and an entry in
Apps & features. No admin rights needed.

Already built, just want the shortcut? Double-click `packaging\install.bat`.

`packaging\build.bat /nodesktop` skips the desktop shortcut.

## Check you are on the right branch

The installer lives on `claude/zen-goldberg-jdw51o`. On the default branch
`build.bat` only builds, which looks like the install silently doing nothing.

```bat
git branch --show-current
git log --oneline -1
```

## When it does not appear

Work down the list; each step tells you which part failed.

1. **Does the exe exist?** `dir dist\TorqueTune\TorqueTune.exe`
   Missing means the build failed, not the install. Run `packaging\build.bat`
   from a Command Prompt (not by double-clicking) and read the error.
2. **Did the install run?** Run `packaging\install.bat` on its own. It prints
   what it did and pauses, so the window stays open.
3. **Is it actually installed?**
   `dir "%LOCALAPPDATA%\Programs\TorqueTune"` and
   `dir "%APPDATA%\Microsoft\Windows\Start Menu\Programs\TorqueTune.lnk"`
   If both exist, the install worked and the problem is the shell's search
   index — press Start and type TorqueTune, or open the Start menu folder
   with `explorer "%APPDATA%\Microsoft\Windows\Start Menu\Programs"`.
4. **Blocked by policy?** If PowerShell refuses to run the script,
   `-ExecutionPolicy Bypass` is already passed, so the block is a machine
   policy. Say so and the install can be done with a `.bat` instead.

## Running from source

Installing is only for the packaged build. From a checkout:

```bat
pip install -e .
python -m tuner --demo
```
