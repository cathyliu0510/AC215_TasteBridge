"""The embed fallback rule must match preprocess/quality.py exactly."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from embed import texts

QUALITY = Path(__file__).resolve().parents[2] / "preprocess" / "quality.py"

SAMPLES = [
    None, pd.NA, "", "   ", "<br><br>", "A novel.", "x" * 39, "x" * 40,
    "Book 2 of &lt;Gentleman Bastard&gt;",
    "<b>Locke Lamora</b> is a thief.<br>A very good one, in a city of canals.",
]


@pytest.mark.skipif(not QUALITY.is_file(), reason="preprocess/quality.py not in this checkout")
def test_fallback_rule_matches_quality_module():
    spec = importlib.util.spec_from_file_location("quality_under_test", QUALITY)
    quality = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(quality)
    assert texts.MIN_DESCRIPTION_CHARS == quality.MIN_DESCRIPTION_CHARS
    for sample in SAMPLES:
        assert texts.clean_description(sample) == quality.clean_description(sample)
        assert texts.fallback_has_description(sample) == (quality.check_description(sample)[1] is None)
