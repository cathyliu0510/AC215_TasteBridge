"""The backend artifact contract (SPEC.md section 5) that every pipeline train image must write."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from twotower import TwoTower
from twotower.export import (
    CONTRACT_FILES,
    M1_FILES,
    check_contract,
    main,
    model_version_for,
    publish,
    write_contract,
)


@pytest.fixture
def exported(tiny_model: TwoTower, tiny_data, tmp_path: Path) -> tuple[Path, TwoTower, pd.DataFrame]:
    """A saved tiny model plus its contract, from a catalogue in a non-alphabetical order
    and with one book nobody liked (so it has no vector)."""
    data, _ = tiny_data
    books = pd.read_parquet(data.books).iloc[::-1].reset_index(drop=True)  # catalogue order != sorted ids
    extra = books.iloc[[0]].assign(work_id="w99", title="unliked")
    books = pd.concat([books, extra], ignore_index=True)
    books_path = tmp_path / "books.parquet"
    books.to_parquet(books_path)
    model_dir = tiny_model.save(tmp_path / "run" / "model")
    write_contract(tiny_model, books_path, model_dir, data_version="gr-test", run_id="r1", wandb_run_id="abc123")
    return model_dir, tiny_model, books


def test_contract_files_rows_follow_the_catalogue(exported) -> None:
    model_dir, model, books = exported
    for name in (*CONTRACT_FILES, *M1_FILES):
        assert (model_dir / name).is_file(), name
    records = json.loads((model_dir / "books.json").read_text(encoding="utf-8"))
    ids = [r["book_id"] for r in records]
    expected = [w for w in books["work_id"].astype(str) if w in set(model.items)]
    assert ids == expected and ids != sorted(ids)  # catalogue order, like the B2 export
    assert "w99" not in ids  # no vector -> left out of every file together
    emb = np.load(model_dir / "item_embeddings.npy")
    vectors = model.item_vectors()
    row = {w: i for i, w in enumerate(model.items)}
    np.testing.assert_allclose(emb, vectors[[row[w] for w in ids]], rtol=1e-6)  # row i <-> books.json[i]
    assert emb.dtype == np.float32 and np.allclose(np.linalg.norm(emb, axis=1), 1, atol=1e-5)
    coords = np.load(model_dir / "coords_2d.npy")
    assert coords.shape == (len(ids), 2) and coords.dtype == np.float32 and np.abs(coords).max() <= 1 + 1e-6
    assert set(records[0]) == {"book_id", "title", "author", "year", "shelves", "cover_url"}


def test_meta_has_the_ms3_keys(exported) -> None:
    model_dir, _, _ = exported
    meta = check_contract(model_dir)
    assert meta["model_version"] == model_version_for("gr-test", "r1") == "m1-tt-gr-test-r1"
    assert meta["data_version"] == "gr-test" and meta["wandb_run_id"] == "abc123"
    assert meta["hyperparameters"]["dim"] == 16 and meta["counts"]["books"] == 20
    assert meta["map_method"] == "umap"  # the proposal's galaxy map, not the PCA fallback


def test_missing_umap_stops_the_export(tiny_model: TwoTower, tiny_data, tmp_path: Path, monkeypatch) -> None:
    """Without umap-learn the shared helper would quietly use PCA; M1's export refuses instead."""
    import sys

    data, _ = tiny_data
    monkeypatch.setitem(sys.modules, "umap", None)  # makes `import umap` raise ImportError
    with pytest.raises(RuntimeError, match="UMAP is required"):
        write_contract(tiny_model, data.books, tmp_path / "m", data_version="v", run_id="r", wandb_run_id=None)
    assert not (tmp_path / "m" / "meta.json").exists()


def test_saved_model_still_loads_next_to_the_contract(exported) -> None:
    """items.json keeps the network's own order, so load() is unaffected by the catalogue order."""
    model_dir, model, _ = exported
    loaded = TwoTower.load(model_dir, device="cpu")
    np.testing.assert_allclose(loaded.score(["w01", "w02"]), model.score(["w01", "w02"]), rtol=1e-6)


@pytest.mark.parametrize(
    "breakage, message",
    [
        (lambda d: (d / "coords_2d.npy").unlink(), "missing coords_2d.npy"),
        (lambda d: np.save(d / "coords_2d.npy", np.zeros((3, 2), np.float32)), "row counts differ"),
        (lambda d: np.save(d / "item_embeddings.npy", 2 * np.load(d / "item_embeddings.npy")), "not L2-normalised"),
        (
            lambda d: np.save(d / "item_embeddings.npy", np.load(d / "item_embeddings.npy").astype(np.float64)),
            "float32",
        ),
        (lambda d: _edit_meta(d, drop="wandb_run_id"), "lacks 'wandb_run_id'"),
        (lambda d: _edit_meta(d, model_version=""), "'model_version' must be a non-empty string"),
        (lambda d: _edit_meta(d, data_version=None), "'data_version' must be a non-empty string"),
    ],
)
def test_check_rejects_a_broken_contract(exported, breakage, message: str) -> None:
    model_dir, _, _ = exported
    breakage(model_dir)
    with pytest.raises(ValueError, match=message):
        check_contract(model_dir)
    assert main(["check", str(model_dir)]) == 1


def test_wandb_run_id_may_be_null_when_tracking_is_off(exported) -> None:
    model_dir, _, _ = exported
    _edit_meta(model_dir, wandb_run_id=None)
    assert check_contract(model_dir)["wandb_run_id"] is None


def test_publish_copies_everything_once(exported, tmp_path: Path) -> None:
    model_dir, model, _ = exported
    target = publish(model_dir, tmp_path / "models")
    assert target == tmp_path / "models" / "m1-tt-gr-test-r1"
    assert {p.name for p in target.iterdir()} == set(CONTRACT_FILES) | set(M1_FILES)
    assert check_contract(target)["model_version"] == "m1-tt-gr-test-r1"
    TwoTower.load(target, device="cpu")  # the published copy is a complete, loadable model
    with pytest.raises(FileExistsError):
        publish(model_dir, tmp_path / "models")  # versions are immutable


def test_publish_refuses_a_broken_contract(exported, tmp_path: Path) -> None:
    model_dir, _, _ = exported
    (model_dir / "books.json").unlink()
    with pytest.raises(ValueError, match="missing books.json"):
        publish(model_dir, tmp_path / "models")
    assert not (tmp_path / "models").exists()


def test_cli_write_then_check(tiny_model: TwoTower, tiny_data, tmp_path: Path, capsys) -> None:
    """`export write` adds the contract to a folder saved before export existed (e.g. older runs)."""
    data, _ = tiny_data
    model_dir = tiny_model.save(tmp_path / "old-run" / "model", {"run_id": "old-run"})
    assert main(["write", "--model-dir", str(model_dir), "--data-dir", str(data.root), "--data-version", "gr-x"]) == 0
    assert capsys.readouterr().out.strip() == "m1-tt-gr-x-old-run"
    assert main(["check", str(model_dir)]) == 0
    assert "OK m1-tt-gr-x-old-run: 20 books" in capsys.readouterr().out


def _edit_meta(model_dir: Path, drop: str | None = None, **changes: object) -> None:
    path = model_dir / "meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    if drop:
        meta.pop(drop)
    meta.update(changes)
    path.write_text(json.dumps(meta), encoding="utf-8")
