import json
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_ARTIFACT_DIR, Settings
from app.main import create_app

FANTASY_FIVE = ["w_1001", "w_1002", "w_1003", "w_1004", "w_1005"]
MYSTERY_FIVE = ["w_2001", "w_2002", "w_2003", "w_2004", "w_2005"]


@pytest.fixture
def feedback_path(tmp_path: Path) -> Path:
    return tmp_path / "feedback" / "feedback.jsonl"


@pytest.fixture
def client_factory(feedback_path: Path) -> Callable[[], TestClient]:
    """Builds an unstarted client; entering it with `with` runs app startup."""
    settings = Settings(
        artifact_dir=str(DEFAULT_ARTIFACT_DIR),
        feedback_path=feedback_path,
        cors_origins=("*",),
    )
    return lambda: TestClient(create_app(settings))


@pytest.fixture
def client(client_factory: Callable[[], TestClient]) -> Iterator[TestClient]:
    with client_factory() as test_client:
        yield test_client


def write_artifacts(
    root: Path,
    books: list[dict],
    embeddings: np.ndarray,
    coords: np.ndarray,
    meta: dict | None = None,
) -> Path:
    """Write a complete artifact folder for loader tests."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "books.json").write_text(json.dumps(books), encoding="utf-8")
    np.save(root / "item_embeddings.npy", embeddings)
    np.save(root / "coords_2d.npy", coords)
    (root / "meta.json").write_text(
        json.dumps(meta if meta is not None else {"model_version": "test-v1"}), encoding="utf-8"
    )
    return root


def make_books(count: int) -> list[dict]:
    return [
        {"book_id": f"b{i}", "title": f"Book {i}", "author": f"Author {i}", "shelves": []}
        for i in range(count)
    ]
