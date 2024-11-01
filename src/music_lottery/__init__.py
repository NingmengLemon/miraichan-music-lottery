import sys, os


if "src" in os.listdir():
    sys.path.insert(0, "src")

from . import core, models, musiclib, utils

app = core.app
