"""B2: implicit-feedback ALS (Hu, Koren & Volinsky 2008), the baseline the app serves.

Owner: Cathy Liu. Plugs into the evaluator through the `Recommender` interface
(models.py) and is exported for the backend by export.py.

Model
-----
Every reader u and work i get a vector of `factors` numbers (x_u, y_i). For each
(u, i) pair the preference p_ui is 1 if u liked i (rating >= 4) and 0 otherwise;
liked pairs get a higher confidence c_ui = 1 + alpha. ALS minimises

    sum_{u,i} c_ui (p_ui - x_u . y_i)^2  +  reg * (sum ||x_u||^2 + sum ||y_i||^2)

by alternating two exact least-squares solves: fix the work vectors and solve
every reader vector, then fix the reader vectors and solve every work vector.
Each solve uses the standard trick Y'C_uY = Y'Y + alpha * Y_u'Y_u, so the cost
depends only on the works that reader liked, not on the whole catalogue.

Scoring = exactly what the backend serves (backend/app/recommender.py)
----------------------------------------------------------------------
    taste  = mean of the reader's favorite work vectors (unit length), re-normalised
    score  = cosine(taste, every work vector)

The scores are deliberately NOT rescaled to [0, 1] like B0/B1: least-misery takes
min(fit_a, fit_b) on these raw cosines in the API, so the offline numbers describe
the exact lists users will see.

Plain numpy (no `implicit` package): that library needs compiled code that may not
build inside Docker on Apple-Silicon Macs, and ~60 lines of numpy are easy to audit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy import sparse

from evaluation.data import likes


@dataclass(frozen=True)
class ALSParams:
    """Key hyperparameters (recorded in config.json and the artifact meta.json)."""

    # Chosen on the TUNE split of the full Goodreads data (gr-317756d1a1ad), 18 settings,
    # see docs/ms2/models/README.md: Min-Recall@10 rises with factors (16 -> 128) and
    # peaks at regularisation ~50; 128 factors matches 256 (0.0424 vs 0.0427) at a
    # third of the training time.
    factors: int = 128         # vector length per reader / work
    regularization: float = 50.0
    alpha: float = 20.0        # extra confidence on liked pairs
    iterations: int = 15
    seed: int = 42

    def as_dict(self) -> dict:
        return asdict(self)


def _solve_side(
    fixed: np.ndarray, matrix: sparse.csr_matrix, alpha: float, reg: float
) -> np.ndarray:
    """Solve every row of the free side given the fixed side (one ALS half-step).

    For row u with liked columns I_u:
        (F'F + alpha * F_I'F_I + reg * I) x_u = (1 + alpha) * sum_{i in I_u} f_i
    """
    k = fixed.shape[1]
    gram = fixed.T @ fixed + reg * np.eye(k)      # shared by every row
    out = np.zeros((matrix.shape[0], k))
    indptr, indices = matrix.indptr, matrix.indices
    for row in range(matrix.shape[0]):
        cols = indices[indptr[row]:indptr[row + 1]]
        if cols.size == 0:
            continue                               # no likes: vector stays 0
        f = fixed[cols]
        a = gram + alpha * (f.T @ f)
        b = (1.0 + alpha) * f.sum(axis=0)
        out[row] = np.linalg.solve(a, b)
    return out


class ALS:
    """B2: implicit ALS with the backend's mean-of-seeds cosine scoring."""

    name = "als"

    def __init__(self, params: ALSParams | None = None) -> None:
        self.params = params or ALSParams()
        if self.params.factors < 1 or self.params.iterations < 1:
            raise ValueError("factors and iterations must be at least 1")
        self.items: tuple[str, ...] = ()
        self._row: dict[str, int] = {}
        self.item_vectors = np.zeros((0, self.params.factors), dtype=np.float32)  # unit rows

    def fit(self, interactions: pd.DataFrame) -> "ALS":
        p = self.params
        liked = likes(interactions)
        self.items = tuple(sorted(liked["work_id"].unique()))
        self._row = {work: i for i, work in enumerate(self.items)}
        users = {user: i for i, user in enumerate(sorted(liked["user_id"].unique()))}
        user_item = sparse.csr_matrix(
            (
                np.ones(len(liked), dtype=np.float32),
                (liked["user_id"].map(users).to_numpy(), liked["work_id"].map(self._row).to_numpy()),
            ),
            shape=(len(users), len(self.items)),
        )
        user_item.sum_duplicates()
        user_item.data[:] = 1.0
        item_user = user_item.T.tocsr()

        # Small random start (fixed seed -> the same vectors every run).
        rng = np.random.default_rng(p.seed)
        item_f = rng.normal(scale=0.01, size=(len(self.items), p.factors))
        user_f = np.zeros((len(users), p.factors))
        for _ in range(p.iterations):
            user_f = _solve_side(item_f, user_item, p.alpha, p.regularization)
            item_f = _solve_side(user_f, item_user, p.alpha, p.regularization)

        norms = np.linalg.norm(item_f, axis=1, keepdims=True)
        unit = np.divide(item_f, norms, out=np.zeros_like(item_f), where=norms > 0)
        self.item_vectors = unit.astype(np.float32)
        return self

    def taste_vector(self, favorites: Sequence[str]) -> np.ndarray | None:
        """Backend rule: mean of the favorites' unit vectors, scaled to length 1."""
        rows = [self._row[w] for w in favorites if w in self._row]
        if not rows:
            return None
        mean = self.item_vectors[rows].mean(axis=0)
        norm = np.linalg.norm(mean)
        return mean / norm if norm > 0 else mean

    def score(self, favorites: Sequence[str]) -> np.ndarray:
        taste = self.taste_vector(favorites)
        if taste is None:
            return np.zeros(len(self.items))
        return (self.item_vectors @ taste).astype(float)  # cosine, in [-1, 1]
