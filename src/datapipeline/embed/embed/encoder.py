"""Turn texts into unit-length float32 vectors."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np


class EmbeddingError(Exception):
    """The encoder produced unusable vectors; the run stops with exit code 1."""


class Encoder(Protocol):
    model_name: str
    revision: str
    dim: int

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class SentenceTransformerEncoder:
    """Pinned sentence-transformers model on CPU, L2-normalized output."""

    def __init__(self, model_name: str, revision: str, batch_size: int = 64) -> None:
        from sentence_transformers import SentenceTransformer  # heavy import, loaded on use

        self.model_name = model_name
        self.revision = revision
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, revision=revision, device="cpu")
        self.dim = int(self._encode(["dimension probe"]).shape[1])

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return self._encode(texts)


def check_embeddings(embeddings: np.ndarray, n_rows: int) -> None:
    """Raise EmbeddingError unless embeddings is a finite (n_rows, d) array of non-zero rows."""
    embeddings = np.asarray(embeddings)
    if embeddings.ndim != 2:
        raise EmbeddingError(f"expected a 2-D array, got shape {embeddings.shape}")
    if embeddings.shape[0] != n_rows:
        raise EmbeddingError(f"expected {n_rows} rows, got {embeddings.shape[0]}")
    finite = np.isfinite(embeddings).all(axis=1)
    if not finite.all():
        bad = np.where(~finite)[0][:10].tolist()
        raise EmbeddingError(f"non-finite values in rows {bad}")
    zero = np.where(np.linalg.norm(embeddings, axis=1) < 1e-6)[0][:10].tolist()
    if zero:
        raise EmbeddingError(f"zero-length vectors in rows {zero}")
