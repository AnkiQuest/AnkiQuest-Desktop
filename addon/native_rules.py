"""The shared rules for Python: AnkiQuest-Server's crates/rules as a UniFFI library and its
Python bindings, for rules the add-on needs synchronously, outside a page (day verdicts).

The packager writes the library of each desktop platform, with a copy of the bindings, to
rules/<platform>/ from the release ankiquest-rules.json pins. The bindings load the library
next to them with ctypes, so one library serves every Python version:

    rules/<platform>/ankiquest_rules.py ──ctypes──▶ rules/<platform>/libankiquest_rules.so
          ▲ load()
    day_verdict.verdict

What pages draw uses the WebAssembly module instead (rules.py).
"""

import importlib.util
import platform
import sys
from pathlib import Path

# Where the packager writes each platform's folder.
FOLDER = Path(__file__).resolve().parent / "rules"

# The bindings' file in each folder.
BINDINGS = "ankiquest_rules.py"

# platform.machine()'s names for the CPUs the release builds for.
_CPUS = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "arm64"}

# The platform folder for (operating system, CPU).
_PLATFORMS = {
    ("linux", "x86_64"): "linux-x86_64",
    ("linux", "aarch64"): "linux-aarch64",
    ("windows", "x86_64"): "windows-x86_64",
    ("macos", "arm64"): "macos-arm64",
    ("macos", "aarch64"): "macos-arm64",
    ("macos", "x86_64"): "macos-x86_64",
}

_cache = {}


def _system(name):
    """sys.platform as the folder names it: linux, windows or macos."""
    if name.startswith("linux"):
        return "linux"
    if name in ("win32", "cygwin"):
        return "windows"
    if name == "darwin":
        return "macos"
    return name


def platform_folder(system=None, machine=None):
    """The folder name of this platform's library, or None where the add-on ships none."""
    system = _system(sys.platform if system is None else system)
    cpu = _CPUS.get((platform.machine() if machine is None else machine).lower())
    return _PLATFORMS.get((system, cpu))


def load():
    """The bindings module for this platform, loaded once; None where there is no library or it
    cannot be loaded, which leaves the rules it serves unknown."""
    if "module" in _cache:
        return _cache["module"]
    _cache["module"] = None
    folder = platform_folder()
    if folder is None:
        print("ankiquest rules: no library for", sys.platform, platform.machine())
        return None
    try:
        path = FOLDER / folder / BINDINGS
        spec = importlib.util.spec_from_file_location(__name__ + "_bindings", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as error:
        print("ankiquest rules:", error)
        return None
    _cache["module"] = module
    return module
