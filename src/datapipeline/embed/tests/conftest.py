import hashlib

import numpy as np
import pytest

from scripts.make_synthetic_books import synthetic_books


class HashEncoder:
    """Deterministic fake encoder: same text -> same unit vector. No model download."""

    model_name = "test/hash-encoder"
    revision = "test"
    dim = 16

    def encode(self, texts):
        rows = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little")
            vector = np.random.default_rng(seed).standard_normal(self.dim)
            rows.append(vector / np.linalg.norm(vector))
        return np.asarray(rows, dtype=np.float32).reshape(len(rows), self.dim)


@pytest.fixture
def books_df():
    return synthetic_books()


@pytest.fixture
def books_path(tmp_path, books_df):
    processed = tmp_path / "processed"
    processed.mkdir()
    path = processed / "books.parquet"
    books_df.to_parquet(path, index=False)
    (processed / "manifest.json").write_text('{"data_version": "synthetic-test"}', encoding="utf-8")
    return path


@pytest.fixture
def encoder():
    return HashEncoder()
