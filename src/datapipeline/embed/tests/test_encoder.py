import numpy as np
import pytest

from embed.encoder import EmbeddingError, check_embeddings


def _unit(n, d=4):
    rows = np.ones((n, d), dtype=np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def test_check_embeddings_ok():
    check_embeddings(_unit(3), 3)


def test_wrong_row_count():
    with pytest.raises(EmbeddingError, match="expected 4 rows, got 3"):
        check_embeddings(_unit(3), 4)


def test_not_2d():
    with pytest.raises(EmbeddingError, match="2-D"):
        check_embeddings(np.ones(4, dtype=np.float32), 4)


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite(bad):
    emb = _unit(3)
    emb[1, 2] = bad
    with pytest.raises(EmbeddingError, match=r"non-finite values in rows \[1\]"):
        check_embeddings(emb, 3)


def test_zero_vector():
    emb = _unit(3)
    emb[2] = 0.0
    with pytest.raises(EmbeddingError, match=r"zero-length vectors in rows \[2\]"):
        check_embeddings(emb, 3)


def test_hash_encoder_satisfies_contract(encoder):
    emb = encoder.encode(["a", "b"])
    check_embeddings(emb, 2)
    assert encoder.encode([]).shape == (0, encoder.dim)
