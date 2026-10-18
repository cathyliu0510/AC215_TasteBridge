"""Uses the real model. Run with: uv run pytest -m slow"""

import numpy as np
import pytest

from embed.config import DEFAULT_MODEL, DEFAULT_MODEL_REVISION
from embed.encoder import SentenceTransformerEncoder, check_embeddings
from embed.texts import build_texts


@pytest.mark.slow
def test_real_model_ranks_heist_first(books_df):
    enc = SentenceTransformerEncoder(DEFAULT_MODEL, DEFAULT_MODEL_REVISION, batch_size=8)
    assert enc.dim == 384
    texts, _ = build_texts(books_df)
    emb = enc.encode(texts)
    check_embeddings(emb, len(texts))
    assert emb.dtype == np.float32
    assert np.allclose(np.linalg.norm(emb, axis=1), 1.0, atol=1e-4)
    query = enc.encode(["a heist with a crew of con artists"])[0]
    assert books_df["work_id"].iloc[int(np.argmax(emb @ query))] == "syn-001"
    assert enc.encode([]).shape == (0, 384)
