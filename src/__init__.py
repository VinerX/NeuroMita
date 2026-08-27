"""Compatibility bootstrap for launching flat-layout modules through ``src``."""

from pathlib import Path
import sys


_SOURCE_DIRECTORY = str(Path(__file__).resolve().parent)
if _SOURCE_DIRECTORY not in sys.path:
    sys.path.insert(0, _SOURCE_DIRECTORY)
