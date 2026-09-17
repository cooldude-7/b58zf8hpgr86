"""Frozen-app entry point.

PyInstaller runs the entry script as __main__ with no package context, so a
relative import here is a crash on launch. This module uses the absolute
one and does nothing else.
"""
import sys

from tuner.app import main

sys.exit(main())
