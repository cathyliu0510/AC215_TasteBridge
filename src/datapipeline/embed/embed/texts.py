"""Build the one text per book that gets embedded.

Normally preprocess (quality.py) has already cleaned `description` and set
`has_description`. If that column is absent, the same 40-character rule is
applied here; tests/test_rule_parity.py keeps the two copies in sync.
"""

from __future__ import annotations

import html
import re

import numpy as np
import pandas as pd

MIN_DESCRIPTION_CHARS = 40  # must equal preprocess/quality.py
MAX_FALLBACK_SHELVES = 8

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def is_missing(value: object) -> bool:
    """True for None, NaN and pandas NA (what parquet returns for empty values)."""
    if value is None:
        return True
    if isinstance(value, (list, tuple, dict, np.ndarray)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def clean_description(text: object) -> str | None:
    """Same rule as quality.clean_description: tags, then entities, then whitespace."""
    if is_missing(text):
        return None
    cleaned = _TAG.sub(" ", str(text))
    cleaned = html.unescape(cleaned)
    cleaned = _WS.sub(" ", cleaned).strip()
    return cleaned or None


def fallback_has_description(text: object) -> bool:
    cleaned = clean_description(text)
    return cleaned is not None and len(cleaned) >= MIN_DESCRIPTION_CHARS


def as_list(value: object) -> list[str]:
    """Shelves as a plain list of strings (parquet gives numpy arrays)."""
    if is_missing(value):
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if not is_missing(item)]


def _text_or_none(value: object) -> str | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def build_text(
    title: object, author: object, description: object, shelves: object, has_description: bool
) -> tuple[str, str]:
    """Return (text, text_source)."""
    title_text = _text_or_none(title)
    author_text = _text_or_none(author)
    head = f"{title_text} by {author_text}." if author_text else f"{title_text}."
    description_text = _text_or_none(description)
    if has_description and description_text:
        return f"{head} {description_text}", "description"
    names = as_list(shelves)[:MAX_FALLBACK_SHELVES]
    if names:
        return f"{head} Shelves: {', '.join(names)}", "title_shelves"
    return head, "title_shelves"


def build_texts(books: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Texts and text_sources for every row, in row order."""
    if "has_description" in books.columns:
        flags = [False if is_missing(flag) else bool(flag) for flag in books["has_description"]]
        descriptions = list(books["description"])
    else:
        descriptions = [clean_description(d) for d in books["description"]]
        flags = [d is not None and len(d) >= MIN_DESCRIPTION_CHARS for d in descriptions]
    pairs = [
        build_text(title, author, description, shelves, flag)
        for title, author, description, shelves, flag in zip(
            books["title"], books["author"], descriptions, books["shelves"], flags
        )
    ]
    return [text for text, _ in pairs], [source for _, source in pairs]
