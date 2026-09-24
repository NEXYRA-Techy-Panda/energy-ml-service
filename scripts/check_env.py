"""Confirms the interpreter is the project .venv (Python 3.13) and the pinned stack imports.

Run: .venv\\Scripts\\python.exe scripts\\check_env.py   (Linux: .venv/bin/python scripts/check_env.py)
"""

import sys
from importlib.metadata import version

EXPECTED = ["fastapi", "uvicorn", "starlette", "pydantic", "pandas", "numpy", "scikit-learn", "scipy"]

print(f"python {sys.version.split()[0]} at {sys.executable}")
print(f"virtualenv: {sys.prefix != sys.base_prefix} (prefix {sys.prefix})")
ok = sys.version_info[:2] == (3, 13) and sys.prefix != sys.base_prefix

import fastapi  # noqa: E402,F401
import numpy  # noqa: E402,F401
import pandas  # noqa: E402,F401
import pydantic  # noqa: E402,F401
import scipy  # noqa: E402,F401
import sklearn  # noqa: E402,F401
import starlette  # noqa: E402,F401
import uvicorn  # noqa: E402,F401

for name in EXPECTED:
    print(f"{name}=={version(name)}")

print("imports OK" if ok else "UNEXPECTED interpreter (need .venv with Python 3.13)")
sys.exit(0 if ok else 1)
