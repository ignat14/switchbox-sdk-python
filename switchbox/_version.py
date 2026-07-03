"""Single source of the package version (FABLE_IMPROVEMENTS 2.7).

Derived from the installed distribution metadata (pyproject.toml's `version`)
so `__version__`, the User-Agent, and PyPI can never drift — previously
__init__.py said 0.5.0, pyproject said 0.6.0 and the User-Agent hardcoded a
third copy. Lives in its own leaf module because both __init__.py and sync.py
need it (importing from the package root inside sync would be circular).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("switchbox-flags")
except PackageNotFoundError:  # running from a raw source tree, not installed
    __version__ = "0.0.0"
