"""Pytest bootstrap: put hermes/ and repo root on sys.path so legacy
`from charlotte.X` and new `from hermes.charlotte.X` imports both resolve.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_ROOT / "hermes")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
