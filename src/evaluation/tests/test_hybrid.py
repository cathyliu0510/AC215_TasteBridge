"""Tests for M1: ALS fold-in, the hybrid blend, and the tune-then-test runner. Invented data only."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from evaluation import run as run_module
from evaluation import synthetic, tune_hybrid
from evaluation.aggregate import recommend_pair
from evaluation.als import ALS, ALSParams
from evaluation.hybrid import ALSFoldIn, Hybrid, HybridParams, build_models, rescale
from evaluation.models import MODELS, ItemKNN
from evaluation.split import split_users

FAST = ALSParams(factors=8, regularization=1.0, alpha=10.0, iterations=5, seed=0)
FAST_FLAGS = ["--als-factors", "8", "--als-reg", "1", "--als-alpha", "10", "--als-iterations", "5"]


def _groups() -> pd.DataFrame:
    """Readers 0-19 like a0-a5, readers 20-39 like b0-b5; everyone also likes 'hit'."""
    rows = []
    for u in range(40):
        group = "a" if u < 20 else "b"
        works = [f"{group}{i}" for i in range(6)] + ["hit"]
        rows += [{"user_id": f"u{u}", "work_id": w, "rating": 5} for w in works]
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def fitted() -> tuple[ItemKNN, ALS]:
    data = _groups()
    return ItemKNN(100).fit(data), ALS(FAST).fit(data)


# ---------------------------------------------------------------- ALS fold-in

def test_als_keeps_raw_factors_matching_its_unit_vectors(fitted) -> None:
    _, als = fitted
    norms = np.linalg.norm(als.item_factors, axis=1, keepdims=True)
    assert np.allclose(als.item_factors / norms, als.item_vectors, atol=1e-5)
    assert not np.allclose(norms, 1.0)  # lengths carry information the unit rows drop


def test_fold_in_is_the_exact_weighted_least_squares_solution(fitted) -> None:
    """x minimises sum_i c_i (p_i - y_i.x)^2 + reg |x|^2, the ALS objective for one reader."""
    _, als = fitted
    model = ALSFoldIn.from_als(als)
    favorites = ["a0", "a1", "a2"]
    y = als.item_factors
    p = np.array([1.0 if w in favorites else 0.0 for w in als.items])
    c = 1.0 + FAST.alpha * p
    expected = np.linalg.solve(y.T @ (c[:, None] * y) + FAST.regularization * np.eye(FAST.factors), y.T @ (c * p))
    assert np.allclose(model.user_vector(favorites), expected, atol=1e-8)
    assert np.allclose(model.score(favorites), y @ expected, atol=1e-8)


def test_fold_in_learns_the_taste_group(fitted) -> None:
    _, als = fitted
    scores = dict(zip(als.items, ALSFoldIn.from_als(als).score(["a0", "a1"])))
    assert min(scores[w] for w in ("a2", "a3", "a4")) > max(scores[w] for w in ("b0", "b1", "b2"))


def test_fold_in_ignores_unknown_favorites_and_fits_on_its_own() -> None:
    model = ALSFoldIn(FAST).fit(_groups())
    assert not model.score(["not-a-work"]).any()
    assert model.items == ALS(FAST).fit(_groups()).items


def test_fold_in_needs_a_fitted_als() -> None:
    with pytest.raises(ValueError):
        ALSFoldIn.from_als(ALS(FAST))


# ---------------------------------------------------------------- rescale

def test_rescale_ignores_favorites_for_the_range() -> None:
    scores = np.array([10.0, 2.0, 4.0, 3.0])
    out = rescale(scores, ("fav", "x", "y", "z"), ["fav"])
    assert out[1:].min() == 0.0 and out[1:].max() == 1.0  # candidates span the full range
    assert out[0] > 1.0  # the favorite sits above, and is removed later


def test_rescale_handles_flat_and_empty_inputs() -> None:
    assert not rescale(np.array([3.0, 3.0]), ("a", "b"), []).any()
    assert not rescale(np.array([5.0]), ("a",), ["a"]).any()
    assert rescale(np.array([]), (), []).size == 0


# ---------------------------------------------------------------- hybrid

def test_weight_one_gives_exactly_item_knn_lists(fitted) -> None:
    knn, als = fitted
    hybrid = Hybrid.from_fitted(knn, als, HybridParams(weight=1.0, knn_neighbors=100))
    for agg in ("average", "least_misery", "merged_seeds"):
        assert recommend_pair(hybrid, ["a0"], ["b0"], 5, agg) == recommend_pair(knn, ["a0"], ["b0"], 5, agg)


def test_weight_zero_ranks_like_als_for_one_reader(fitted) -> None:
    knn, als = fitted
    hybrid = Hybrid.from_fitted(knn, als, HybridParams(weight=0.0, knn_neighbors=100))
    fold_in = ALSFoldIn.from_als(als)
    favorites = ["a0", "a1"]
    candidates = [i for i, w in enumerate(als.items) if w not in favorites]
    order_h = np.argsort(-hybrid.score(favorites)[candidates], kind="stable")
    order_f = np.argsort(-fold_in.score(favorites)[candidates], kind="stable")
    assert list(order_h) == list(order_f)


def test_blend_is_the_weighted_sum_of_components_in_unit_range(fitted) -> None:
    knn, als = fitted
    hybrid = Hybrid.from_fitted(knn, als, HybridParams(weight=0.3, knn_neighbors=100))
    k, a = hybrid.components(["a0", "b0"])
    assert np.allclose(hybrid.score(["a0", "b0"]), 0.3 * k + 0.7 * a)
    candidates = [i for i, w in enumerate(als.items) if w not in ("a0", "b0")]
    assert k[candidates].min() >= 0 and k[candidates].max() <= 1
    assert a[candidates].min() == 0 and a[candidates].max() == pytest.approx(1)


def test_cosine_scoring_uses_b2s_served_rule(fitted) -> None:
    knn, als = fitted
    hybrid = Hybrid.from_fitted(knn, als, HybridParams(weight=0.0, knn_neighbors=100, als_scoring="cosine"))
    assert np.allclose(hybrid._als_scores(["a0"]), als.score(["a0"]))


def test_hybrid_fit_matches_from_fitted() -> None:
    params = HybridParams(weight=0.4, knn_neighbors=100)
    own = Hybrid(params, FAST).fit(_groups())
    shared = Hybrid.from_fitted(ItemKNN(100).fit(_groups()), ALS(FAST).fit(_groups()), params)
    assert np.allclose(own.score(["a0", "a3"]), shared.score(["a0", "a3"]))


def test_hybrid_never_recommends_favorites(fitted) -> None:
    knn, als = fitted
    hybrid = Hybrid.from_fitted(knn, als, HybridParams(weight=0.5, knn_neighbors=100))
    for agg in ("average", "least_misery", "merged_seeds"):
        top = recommend_pair(hybrid, ["a0", "a1"], ["b0"], 20, agg)
        assert not {"a0", "a1", "b0"} & set(top)


@pytest.mark.parametrize("bad", [
    {"weight": -0.1}, {"weight": 1.5}, {"knn_neighbors": 0}, {"als_scoring": "dot"},
])
def test_bad_params_are_rejected(bad) -> None:
    with pytest.raises(ValueError):
        HybridParams(**bad)


def test_mismatched_components_are_rejected(fitted) -> None:
    knn, als = fitted
    with pytest.raises(ValueError):
        Hybrid.from_fitted(knn, als, HybridParams(knn_neighbors=50))  # knn was fitted with 100
    other = ItemKNN(100).fit(pd.DataFrame({"user_id": ["u"], "work_id": ["z"], "rating": [5]}))
    with pytest.raises(ValueError):
        Hybrid.from_fitted(other, als, HybridParams(knn_neighbors=100))


def test_unfitted_hybrid_cannot_score() -> None:
    with pytest.raises(RuntimeError):
        Hybrid().score(["a0"])


def test_registered_and_build_models_shares_one_als_fit(monkeypatch) -> None:
    assert MODELS["hybrid"] is Hybrid and MODELS["als_foldin"] is ALSFoldIn
    fits = []
    original = ALS.fit
    monkeypatch.setattr(ALS, "fit", lambda self, data: fits.append(1) or original(self, data))
    models = build_models(["item_knn", "als", "als_foldin", "hybrid"], _groups(), 100, FAST,
                          HybridParams(weight=0.5, knn_neighbors=100))
    assert len(fits) == 1
    assert models["hybrid"].knn is models["item_knn"]
    assert models["als_foldin"].als is models["als"]


# ---------------------------------------------------------------- runner and tuner

def test_run_accepts_hybrid_flags_and_records_them(tmp_path: Path) -> None:
    args = run_module.parse_args(["--synthetic", "--out", str(tmp_path), "--run-id", "r", "--n-pairs", "20",
                                  "--models", "item_knn,hybrid", "--hybrid-weight", "0.7",
                                  "--hybrid-knn-neighbors", "50", "--hybrid-als-scoring", "cosine", *FAST_FLAGS])
    config = json.loads((run_module.run(args) / "config.json").read_text())
    assert config["hybrid"] == {"weight": 0.7, "knn_neighbors": 50, "als_scoring": "cosine"}


@pytest.mark.parametrize("argv", [["--hybrid-weight", "2"], ["--hybrid-als-scoring", "dot"],
                                  ["--hybrid-params", "/no/such/best.json"]])
def test_run_rejects_bad_hybrid_settings(argv) -> None:
    with pytest.raises(SystemExit):
        run_module.parse_args(["--synthetic", *argv])


@pytest.fixture(scope="module")
def tuned(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tuned")
    interactions, books = synthetic.write(out / "inputs", n_users=500, n_works=200, seed=9)
    argv = ["--interactions", str(interactions), "--books", str(books), "--out", str(out), "--run-id", "t",
            "--weights", "0,0.5,1", "--neighbors", "50,100", "--n-pairs", "40", "--seed", "9", *FAST_FLAGS]
    tune_hybrid.tune(tune_hybrid.parse_args(argv))
    return out


def test_tuner_writes_a_full_grid_and_a_choice_from_it(tuned: Path) -> None:
    grid = pd.read_csv(tuned / "t-tune" / "tuning.csv")
    assert len(grid) == 3 * 2 * 2  # weights x neighbours x ALS scorings
    best = json.loads((tuned / "t-tune" / "best.json").read_text())
    assert best["tune"]["min_recall"] == pytest.approx(grid["min_recall"].max(), abs=1e-6)  # csv keeps 6 dp
    assert best["hybrid"]["weight"] in (0.0, 0.5, 1.0)
    table_rows = [l for l in (tuned / "t-tune" / "tuning.md").read_text().splitlines() if l.startswith("| 0.") or l.startswith("| 1.")]
    assert sum(row.count("**") for row in table_rows) == 2  # exactly one bold (chosen) cell


def test_tuned_choice_is_never_below_item_knn_on_the_tune_split(tuned: Path) -> None:
    best = json.loads((tuned / "t-tune" / "best.json").read_text())
    knn = best["tune"]["references"]["B1 item-kNN (100 neighbours)"]
    grid = pd.read_csv(tuned / "t-tune" / "tuning.csv")
    same = grid[(grid["weight"] == 1.0) & (grid["knn_neighbors"] == 100)]["min_recall"]
    assert np.allclose(same, knn)  # w = 1 is exactly B1
    assert best["tune"]["min_recall"] >= knn


def test_tune_pairs_match_run_on_the_tune_split(tuned: Path) -> None:
    """The tuner's score for the chosen setting equals evaluation.run --split tune with it."""
    best_path = tuned / "t-tune" / "best.json"
    best = json.loads(best_path.read_text())
    args = run_module.parse_args([
        "--interactions", str(tuned / "inputs" / "interactions.csv"), "--books", str(tuned / "inputs" / "books.csv"),
        "--out", str(tuned), "--run-id", "check", "--split", "tune", "--models", "hybrid",
        "--aggregations", "average", "--hybrid-params", str(best_path), "--n-pairs", "40", "--seed", "9",
        *FAST_FLAGS])
    summary = pd.read_csv(run_module.run(args) / "summary.csv")
    row = summary[(summary["model"] == "hybrid") & (summary["pair_kind"] == "all")]
    assert row["min_recall"].iloc[0] == pytest.approx(best["tune"]["min_recall"], abs=1e-6)


def test_tuner_then_evaluates_test_readers_only_once(tuned: Path) -> None:
    config = json.loads((tuned / "t-test" / "config.json").read_text())
    best = json.loads((tuned / "t-tune" / "best.json").read_text())
    assert config["arguments"]["split"] == "test"
    assert config["hybrid"] == best["hybrid"]
    per_pair = pd.read_csv(tuned / "t-test" / "per_pair.csv", dtype=str)
    interactions = pd.read_csv(tuned / "inputs" / "interactions.csv", dtype=str)
    split = split_users(interactions["user_id"], seed=9)
    assert set(per_pair["reader_a"]) | set(per_pair["reader_b"]) <= split.test
    assert set(per_pair["model"]) == {"popularity", "item_knn", "als", "als_foldin", "hybrid"}


def test_skip_test_leaves_the_test_split_untouched(tmp_path: Path) -> None:
    argv = ["--synthetic", "--out", str(tmp_path), "--run-id", "s", "--weights", "0.5", "--neighbors", "100",
            "--als-scorings", "fold_in", "--n-pairs", "10", "--skip-test", *FAST_FLAGS]
    tune_hybrid.tune(tune_hybrid.parse_args(argv))
    assert (tmp_path / "s-tune" / "best.json").is_file()
    assert not (tmp_path / "s-test").exists()


@pytest.mark.parametrize("argv", [[], ["--synthetic", "--weights", "1.5"], ["--synthetic", "--neighbors", "0"],
                                  ["--synthetic", "--als-scorings", "dot"], ["--synthetic", "--weights", "x"]])
def test_tuner_rejects_bad_arguments(argv) -> None:
    with pytest.raises(SystemExit):
        tune_hybrid.parse_args(argv)
