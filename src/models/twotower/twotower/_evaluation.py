"""Make the team evaluator (src/evaluation) importable.

It is not an installable package. In the container PYTHONPATH already points at it; in a
plain checkout this adds <repo>/src/evaluation to sys.path, found relative to this file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def ensure_evaluation() -> None:
    if importlib.util.find_spec("evaluation") is not None:
        return
    candidate = Path(__file__).resolve().parents[3] / "evaluation"  # src/models/twotower/twotower -> src
    if (candidate / "evaluation" / "__init__.py").exists():
        sys.path.insert(0, str(candidate))
        return
    raise ImportError(
        f"cannot import the team evaluator: set PYTHONPATH to <repo>/src/evaluation (looked for {candidate})"
    )
