"""Input contract and the end-to-end runner."""

import json
from pathlib import Path

import pandas as pd
import pytest

from evaluation import run as run_module
from evaluation import synthetic
from evaluation.data import DataContractError, clean_books, clean_interactions, data_version, read_table


def test_interactions_must_have_contract_columns() -> None:
    with pytest.raises(DataContractError, match="rating"):
        clean_interactions(pd.DataFrame({"user_id": ["u"], "work_id": ["w"]}))


def test_ratings_outside_0_to_5_are_rejected() -> None:
    with pytest.raises(DataContractError):
        clean_interactions(pd.DataFrame({"user_id": ["u"], "work_id": ["w"], "rating": [6]}))


def test_duplicate_user_work_rows_keep_the_best_rating() -> None:
    frame = pd.DataFrame({"user_id": ["u", "u"], "work_id": ["w", "w"], "rating": [2, 5]})
    cleaned = clean_interactions(frame)
    assert cleaned["rating"].tolist() == [5]


def test_ids_become_strings() -> None:
    cleaned = clean_interactions(pd.DataFrame({"user_id": [1], "work_id": [2], "rating": [4]}))
    assert cleaned.loc[0, "user_id"] == "1" and cleaned.loc[0, "work_id"] == "2"


def test_genres_accept_pipe_strings_lists_and_missing() -> None:
    books = clean_books(pd.DataFrame({"work_id": ["a", "b", "c"], "genres": ["x|y| x", ["z"], None]}))
    assert books["genres"].tolist() == [("x", "y"), ("z",), ()]


def test_duplicate_books_are_rejected() -> None:
    with pytest.raises(DataContractError):
        clean_books(pd.DataFrame({"work_id": ["a", "a"], "genres": ["x", "y"]}))


def test_unsupported_and_missing_files(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_text("hi")
    with pytest.raises(DataContractError):
        read_table(tmp_path / "data.txt")
    with pytest.raises(DataContractError):
        read_table(tmp_path / "nope.csv")


def test_data_version_reads_sibling_dvc_md5(tmp_path: Path) -> None:
    data = tmp_path / "interactions.parquet"
    data.write_bytes(b"abc")
    (tmp_path / "interactions.parquet.dvc").write_text("outs:\n- md5: 1234abcd\n  path: interactions.parquet\n")
    version = data_version(data)
    assert version["dvc_md5"] == "1234abcd"
    assert len(version["sha256"]) == 64


@pytest.fixture(scope="module")
def small_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("results")
    inputs = out / "inputs"
    interactions, books = synthetic.write(inputs, n_users=400, n_works=200, seed=5)
    args = run_module.parse_args([
        "--interactions", str(interactions), "--books", str(books), "--out", str(out),
        "--run-id", "test", "--n-pairs", "40", "--favorite-counts", "1,5", "--seed", "5",
    ])
    return run_module.run(args)


def test_run_writes_every_output(small_run: Path) -> None:
    for name in ("config.json", "summary.csv", "summary.md", "per_pair.csv", "sample_recommendations.json", "run.log"):
        assert (small_run / name).is_file(), name
    config = json.loads((small_run / "config.json").read_text())
    assert config["data"]["interactions"]["sha256"]
    assert config["counts"]["users"] == {"train": 320, "tune": 40, "test": 40}


def test_run_covers_every_model_aggregation_and_favorite_count(small_run: Path) -> None:
    summary = pd.read_csv(small_run / "summary.csv")
    combos = set(zip(summary["model"], summary["aggregation"], summary["n_favorites"]))
    assert len(combos) == 3 * 3 * 2  # popularity, item_knn, als x 3 aggregations x 2 favorite counts
    assert set(summary["pair_kind"]) == {"all", "similar", "different"}


def test_evaluated_readers_were_never_training_users(small_run: Path) -> None:
    per_pair = pd.read_csv(small_run / "per_pair.csv", dtype=str)
    config = json.loads((small_run / "config.json").read_text())
    from evaluation.split import split_users
    interactions = pd.read_csv(config["data"]["interactions"]["path"], dtype=str)
    split = split_users(interactions["user_id"], seed=5)
    evaluated = set(per_pair["reader_a"]) | set(per_pair["reader_b"])
    assert evaluated <= split.test
    assert not evaluated & split.train


def test_metrics_are_valid_probabilities(small_run: Path) -> None:
    per_pair = pd.read_csv(small_run / "per_pair.csv")
    for column in ("recall_a", "recall_b", "min_recall", "mean_ndcg"):
        assert per_pair[column].between(0, 1).all(), column
    assert (per_pair["min_recall"] <= per_pair[["recall_a", "recall_b"]].min(axis=1) + 1e-12).all()


def test_sample_recommendations_never_include_favorites(small_run: Path) -> None:
    examples = json.loads((small_run / "sample_recommendations.json").read_text())
    assert examples
    for example in examples:
        favorites = set(example["input"]["reader_a_favorites"]) | set(example["input"]["reader_b_favorites"])
        assert not favorites & {item["title"] for item in example["output"]}


def test_item_knn_beats_popularity_on_structured_synthetic_data(tmp_path: Path) -> None:
    """Sanity check of the whole harness: a model that uses the readers must win."""
    args = run_module.parse_args(["--synthetic", "--out", str(tmp_path), "--run-id", "s", "--n-pairs", "200"])
    summary = pd.read_csv(run_module.run(args) / "summary.csv")
    headline = summary[(summary["pair_kind"] == "all") & (summary["aggregation"] == "average")]
    by_model = headline.set_index("model")["min_recall"]
    assert by_model["item_knn"] > by_model["popularity"]


def test_cli_rejects_bad_arguments() -> None:
    for argv in ([], ["--synthetic", "--models", "nope"], ["--synthetic", "--favorite-counts", "6"]):
        with pytest.raises(SystemExit):
            run_module.parse_args(argv)
