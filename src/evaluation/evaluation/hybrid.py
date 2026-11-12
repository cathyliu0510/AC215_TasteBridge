"""M1: a hybrid of item-kNN (B1) and ALS (B2), plus a better ALS scoring rule.

Owner: Anhad Ahluwalia. Plugs into the evaluator through the `Recommender`
interface (models.py), like B0-B2.

Why
---
On the Goodreads test pairs, item-kNN scores 0.071 Min-Recall@10 and tuned ALS
0.043 (docs/ms2/models/README.md). The models README traces much of the ALS gap
to its scoring rule: work vectors are scaled to length 1 and compared by cosine,
which throws away vector length, the part of ALS that encodes popularity.

Two changes
-----------
1. ALS fold-in (`ALSFoldIn`, registered as "als_foldin").
   A new reader's favorites are treated exactly like a training reader's likes:
   their vector x is the ALS least-squares solution given the fixed work factors Y,

       x = (Y'Y + alpha * Y_F'Y_F + reg * I)^-1  (1 + alpha) * sum_{f in F} y_f

   and every work scores y_i . x on the raw (un-normalised) factors. This is the
   same half-step ALS uses during training (als._solve_side), so no new
   hyperparameters. It is a 128 x 128 solve per reader: fast enough to serve.

2. Hybrid (`Hybrid`, registered as "hybrid").
   Both components are put on a [0, 1] scale per reader, then blended:

       s(i) = w * kNN(i) + (1 - w) * ALS(i)

   kNN(i) is B1's own score, unchanged (already divided by the reader's maximum).
   ALS(i) is min-max rescaled over the works the reader did not pick, since ALS
   scores can be negative. Because the kNN part is untouched, w = 1 gives exactly
   B1's lists, so a weight tuned on the tune split (with B1's neighbour count in
   the grid) can never score below B1 there. tune_hybrid.py chooses w, the kNN
   neighbour count and the ALS scoring rule on the tune split only, then reports
   the test split once.

The two readers' scores are then combined by average or least misery exactly as
for every other model (aggregate.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from evaluation.als import ALS, ALSParams

# ItemKNN is imported inside functions: models.py imports this module to register
# the hybrid, so a top-level import here would be circular.

ALS_SCORINGS = ("fold_in", "cosine")


class ALSFoldIn:
    """B2 with fold-in scoring: solve the reader's ALS vector, rank by raw dot product."""

    name = "als_foldin"

    def __init__(self, params: ALSParams | None = None) -> None:
        self.als = ALS(params)
        self._gram = np.zeros((0, 0))

    @classmethod
    def from_als(cls, als: ALS) -> "ALSFoldIn":
        """Reuse an already fitted ALS (no second training run)."""
        model = cls(als.params)
        model.als = als
        model._prepare()
        return model

    @property
    def items(self) -> tuple[str, ...]:
        return self.als.items

    @property
    def params(self) -> ALSParams:
        return self.als.params

    def fit(self, interactions: pd.DataFrame) -> "ALSFoldIn":
        self.als.fit(interactions)
        self._prepare()
        return self

    def _prepare(self) -> None:
        factors = self.als.item_factors
        if len(self.als.items) == 0 or factors.shape[0] != len(self.als.items):
            raise ValueError("ALS model has no raw item factors; fit it first")
        k = factors.shape[1]
        # Y'Y + reg * I is the same for every reader: compute it once.
        self._gram = factors.T @ factors + self.params.regularization * np.eye(k)

    def user_vector(self, favorites: Sequence[str]) -> np.ndarray | None:
        rows = [self.als._row[w] for w in favorites if w in self.als._row]
        if not rows:
            return None
        picked = self.als.item_factors[rows]
        alpha = self.params.alpha
        lhs = self._gram + alpha * (picked.T @ picked)
        rhs = (1.0 + alpha) * picked.sum(axis=0)
        return np.linalg.solve(lhs, rhs)

    def score(self, favorites: Sequence[str]) -> np.ndarray:
        x = self.user_vector(favorites)
        if x is None:
            return np.zeros(len(self.items))
        return (self.als.item_factors @ x).astype(float)


def rescale(scores: np.ndarray, items: Sequence[str], favorites: Sequence[str]) -> np.ndarray:
    """Min-max scale to [0, 1] over the works the reader did not pick.

    Favorites are excluded from the min and max because they are never
    recommended and their own scores are usually the highest; including them
    would squash every candidate towards 0. Favorites end up at >= 1 and are
    removed later by recommend_pair.
    """
    if len(scores) == 0:
        return scores.astype(float)
    picked = set(favorites)
    candidates = np.array([work not in picked for work in items], dtype=bool)
    if not candidates.any():
        return np.zeros_like(scores, dtype=float)
    low, high = scores[candidates].min(), scores[candidates].max()
    if high <= low:
        return np.zeros_like(scores, dtype=float)
    return np.clip((scores - low) / (high - low), 0.0, None)


@dataclass(frozen=True)
class HybridParams:
    """M1 settings. Defaults are placeholders: tune_hybrid.py sets them on the tune split."""

    weight: float = 0.5          # share of item-kNN; 1 - weight goes to ALS
    knn_neighbors: int = 100     # B1 neighbours per favorite
    als_scoring: str = "fold_in"  # "fold_in" (raw factors) or "cosine" (B2's served rule)

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight must be between 0 and 1: {self.weight}")
        if self.knn_neighbors < 1:
            raise ValueError("knn_neighbors must be at least 1")
        if self.als_scoring not in ALS_SCORINGS:
            raise ValueError(f"als_scoring must be one of {ALS_SCORINGS}: {self.als_scoring}")

    def as_dict(self) -> dict:
        return asdict(self)


class Hybrid:
    """M1: w * item-kNN + (1 - w) * ALS, each rescaled to [0, 1] per reader."""

    name = "hybrid"

    def __init__(self, params: HybridParams | None = None, als_params: ALSParams | None = None) -> None:
        self.params = params or HybridParams()
        self.als_params = als_params or ALSParams()
        self.knn = None  # fitted ItemKNN
        self.als: ALSFoldIn | None = None

    @classmethod
    def from_fitted(cls, knn: ItemKNN, als: ALS | ALSFoldIn, params: HybridParams) -> "Hybrid":
        """Share already fitted components (tuning tries many weights on one fit)."""
        if knn.n_neighbors != params.knn_neighbors:
            raise ValueError("knn neighbour count does not match params.knn_neighbors")
        fold_in = als if isinstance(als, ALSFoldIn) else ALSFoldIn.from_als(als)
        if tuple(knn.items) != tuple(fold_in.items):
            raise ValueError("item-kNN and ALS were fitted on different catalogues")
        model = cls(params, fold_in.params)
        model.knn, model.als = knn, fold_in
        return model

    @property
    def items(self) -> tuple[str, ...]:
        return self.knn.items if self.knn is not None else ()

    def fit(self, interactions: pd.DataFrame) -> "Hybrid":
        from evaluation.models import ItemKNN

        knn = ItemKNN(self.params.knn_neighbors).fit(interactions)
        als = ALSFoldIn(self.als_params).fit(interactions)
        fitted = Hybrid.from_fitted(knn, als, self.params)
        self.knn, self.als = fitted.knn, fitted.als
        return self

    def _als_scores(self, favorites: Sequence[str]) -> np.ndarray:
        if self.params.als_scoring == "cosine":
            return self.als.als.score(favorites)
        return self.als.score(favorites)

    def components(self, favorites: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
        """(item-kNN, ALS) scores for one reader, both in [0, 1].

        item-kNN keeps B1's own scaling; ALS is min-max rescaled (see module docstring).
        """
        if self.knn is None or self.als is None:
            raise RuntimeError("fit the hybrid before scoring")
        knn = self.knn.score(favorites)
        als = rescale(self._als_scores(favorites), self.items, favorites)
        return knn, als

    def score(self, favorites: Sequence[str]) -> np.ndarray:
        if self.knn is None or self.als is None:
            raise RuntimeError("fit the hybrid before scoring")
        w = self.params.weight
        if w == 1.0:  # exactly B1; skip the ALS solve
            return self.knn.score(favorites)
        if w == 0.0:
            return rescale(self._als_scores(favorites), self.items, favorites)
        knn, als = self.components(favorites)
        return w * knn + (1.0 - w) * als


def build_models(
    names: Sequence[str],
    interactions: pd.DataFrame,
    knn_neighbors: int,
    als_params: ALSParams,
    hybrid_params: HybridParams,
    log=None,
) -> dict:
    """Fit every requested model, training ALS at most once and each kNN size once."""
    import time

    from evaluation.models import MODELS, ItemKNN

    fitted_knn: dict[int, ItemKNN] = {}
    fitted_als: ALS | None = None

    def knn_of(n: int) -> ItemKNN:
        if n not in fitted_knn:
            fitted_knn[n] = ItemKNN(n).fit(interactions)
        return fitted_knn[n]

    def als_model() -> ALS:
        nonlocal fitted_als
        if fitted_als is None:
            fitted_als = ALS(als_params).fit(interactions)
        return fitted_als

    models = {}
    for name in names:
        tic = time.perf_counter()
        if name == "item_knn":
            model = knn_of(knn_neighbors)
        elif name == "als":
            model = als_model()
        elif name == "als_foldin":
            model = ALSFoldIn.from_als(als_model())
        elif name == "hybrid":
            model = Hybrid.from_fitted(knn_of(hybrid_params.knn_neighbors), als_model(), hybrid_params)
        else:
            model = MODELS[name]().fit(interactions)
        models[name] = model
        if log is not None:
            log.info("Ready %s in %.2fs", name, time.perf_counter() - tic)
    return models
