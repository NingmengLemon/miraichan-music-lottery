import sys, os
import logging

if "src" in os.listdir():
    sys.path.insert(0, "src")
    
logging.basicConfig(level=logging.INFO)

__all__ = (
    "core",
    "models",
    "musiclib",
    "utils",
    "app",
)

from . import core, models, musiclib, utils

app = core.app
