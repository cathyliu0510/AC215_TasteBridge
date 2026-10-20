"""Reference baselines and the interface any model must offer the evaluator.

A model is fitted on training users only and then scores every catalogue
work for one reader's favorites. Scores are scaled to [0, 1] per reader so
that average and least-misery aggregation compare like with like.

These are reference implementations so the harness can be checked end to
end. The team's own baselines (B0-B2) and the hybrid (M1) plug in by
implementing `Recommender`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np
import pandas as pd
from scipy import sparse

from evaluation.data import likes


class Recommender(Protocol):
    name: str
    items: tuple[str, ...]  # catalogue order; scores align with it

    def fit(self, interactions: pd.DataFrame) -> "Recommender": ...

    def score(self, favorites: Sequence[str]) -> np.ndarray: ...


def _scale(scores: np.ndarray) -> np.ndarray:
    top = scores.max(initial=0.0)
    return scores / top if top > 0 else np.zeros_like(scores)


class Popularity:
    """B0: number of training users who liked each work. Ignores the reader."""

    name = "popularity"

    def __init__(self) -> None:
        self.items: tuple[str, ...] = ()
        self._scores = np.zeros(0)

    def fit(self, interactions: pd.DataFrame) -> "Popularity":
        counts = likes(interactions).groupby("work_id").size().sort_index()
        self.items = tuple(counts.index)
        self._scores = _scale(counts.to_numpy(dtype=float))
        return self

    def score(self, favorites: Sequence[str]) -> np.ndarray:
        return self._scores.copy()


class ItemKNN:
    """B1: item-item cosine similarity on the binary user-by-work like matrix.

    A reader's score for a work is the summed similarity to their favorites,
    keeping only each favorite's `n_neighbors` most similar works.
    """

    name = "item_knn"

    def __init__(self, n_neighbors: int = 100) -> None:
        if n_neighbors < 1:
            raise ValueError("n_neighbors must be at least 1")
        self.n_neighbors = n_neighbors
        self.items: tuple[str, ...] = ()
        self._row: dict[str, int] = {}
        self._similarity = np.zeros((0, 0), dtype=np.float32)

    def fit(self, interactions: pd.DataFrame) -> "ItemKNN":
        liked = likes(interactions)
        self.items = tuple(sorted(liked["work_id"].unique()))
        self._row = {work: i for i, work in enumerate(self.items)}
        users = {user: i for i, user in enumerate(sorted(liked["user_id"].unique()))}
        matrix = sparse.csr_matrix(
            (
                np.ones(len(liked), dtype=np.float32),
                (liked["user_id"].map(users).to_numpy(), liked["work_id"].map(self._row).to_numpy()),
            ),
            shape=(len(users), len(self.items)),
        )
        co = (matrix.T @ matrix).toarray().astype(np.float32)
        norms = np.sqrt(np.diag(co))
        with np.errstate(divide="ignore", invalid="ignore"):
            sim = co / np.outer(norms, norms)
        sim = np.nan_to_num(sim, nan=0.0, posinf=0.0)
        np.fill_diagonal(sim, 0.0)
        if self.n_neighbors < len(self.items) - 1:
            # Zero everything below each row's n_neighbors-th largest value.
            cutoff = np.partition(sim, -self.n_neighbors, axis=1)[:, -self.n_neighbors]
            sim[sim < cutoff[:, None]] = 0.0
        self._similarity = sim
        return self

    def score(self, favorites: Sequence[str]) -> np.ndarray:
        rows = [self._row[w] for w in favorites if w in self._row]
        if not rows:
            return np.zeros(len(self.items))
        return _scale(self._similarity[rows].sum(axis=0).astype(float))


# B2 lives in als.py (Cathy); imported here so every model is registered in one place.
from evaluation.als import ALS  # noqa: E402

MODELS = {"popularity": Popularity, "item_knn": ItemKNN, "als": ALS}
