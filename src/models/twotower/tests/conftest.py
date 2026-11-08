"""Tiny, fully synthetic fixtures (lecture 13 s.24-27): seconds on a CPU, no real data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from twotower import TwoTower, TwoTowerParams
from twotower.data import DataPaths

N_ITEMS = 20
N_USERS = 30
CONTENT_DIM = 384


def write_content(root: Path, work_ids: list[str], books: pd.DataFrame, seed: int = 0) -> DataPaths:
    """Lay out <root>/processed and <root>/embeddings exactly like the MS2 pipeline does."""
    rng = np.random.default_rng(seed)
    data = DataPaths(root)
    data.processed.mkdir(parents=True, exist_ok=True)
    data.embeddings.mkdir(parents=True, exist_ok=True)
    emb = rng.normal(size=(len(work_ids), CONTENT_DIM)).astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    np.save(data.desc_embeddings, emb)
    pd.DataFrame({"work_id": work_ids, "row": np.arange(len(work_ids))}).to_parquet(data.desc_rows)
    books.to_parquet(data.books)
    return data


@pytest.fixture
def tiny_data(tmp_path: Path) -> tuple[DataPaths, pd.DataFrame]:
    """20 items (3 genres) and 30 readers with 6-10 ratings each, mostly likes."""
    rng = np.random.default_rng(0)
    work_ids = [f"w{i:02d}" for i in range(N_ITEMS)]
    genre = np.array(["fantasy", "mystery", "both"])[np.arange(N_ITEMS) % 3]
    books = pd.DataFrame(
        {"work_id": work_ids, "title": work_ids, "author": "a", "genre": genre, "genres": [[g] for g in genre]}
    )
    data = write_content(tmp_path / "data", work_ids, books)
    rows = []
    for u in range(N_USERS):
        for w in rng.choice(N_ITEMS, size=int(rng.integers(6, 11)), replace=False):
            rows.append((f"u{u:02d}", work_ids[w], int(rng.choice([2, 4, 4, 5, 5]))))
    inter = pd.DataFrame(rows, columns=["user_id", "work_id", "rating"])
    inter.to_parquet(data.interactions)
    return data, inter


@pytest.fixture
def tiny_params() -> TwoTowerParams:
    return TwoTowerParams(
        dim=16, layers=1, heads=2, ffn=32, batch_size=8, epochs=3, eval_every=1, patience=100, device="cpu", seed=0
    )


@pytest.fixture
def tiny_model(tiny_data: tuple[DataPaths, pd.DataFrame], tiny_params: TwoTowerParams) -> TwoTower:
    """An untrained but fully built model, in eval mode, with randomised W_o (so the
    Transformer actually changes the output; the real init is zero)."""
    data, inter = tiny_data
    torch.manual_seed(0)
    model = TwoTower(tiny_params, content_paths=data.content_paths()).prepare(inter)
    net = model._require_net()
    torch.nn.init.normal_(net.reader.out.weight, std=0.5)
    model._cache()
    return model
