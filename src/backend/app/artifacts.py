"""Load and validate a model artifact folder (SPEC.md section 5).

The API fails fast at startup if the folder is incomplete or inconsistent,
so a bad hand-off from the modeling pipeline never serves wrong answers.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pydantic import TypeAdapter, ValidationError

from app.schemas import Book

BOOKS_FILE = "books.json"
EMBEDDINGS_FILE = "item_embeddings.npy"
COORDS_FILE = "coords_2d.npy"
META_FILE = "meta.json"

_books_adapter = TypeAdapter(list[Book])


class ArtifactError(RuntimeError):
    """The artifact folder is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class ModelArtifacts:
    books: tuple[Book, ...]
    embeddings: np.ndarray  # rows L2-normalised, read-only
    coords: np.ndarray  # shape (num_books, 2), read-only
    model_version: str
    data_version: str | None  # dataset snapshot the model was trained on, if recorded
    index: dict[str, int] = field(repr=False)

    def row_of(self, book_id: str) -> int | None:
        return self.index.get(book_id)

    def book(self, book_id: str) -> Book | None:
        row = self.row_of(book_id)
        return None if row is None else self.books[row]


def load_artifacts(artifact_dir: str) -> ModelArtifacts:
    if artifact_dir.startswith("gs://"):
        raise ArtifactError(
            f"GCS artifact paths are not supported yet (MS3 scope): {artifact_dir}"
        )
    root = Path(artifact_dir)
    if not root.is_dir():
        raise ArtifactError(f"Artifact directory not found: {root}")

    books = _load_books(root / BOOKS_FILE)
    embeddings = _load_matrix(root / EMBEDDINGS_FILE)
    coords = _load_matrix(root / COORDS_FILE)
    model_version, data_version = _load_versions(root / META_FILE)

    _check_shapes(len(books), embeddings, coords)
    index = _build_index(books)

    return ModelArtifacts(
        books=tuple(books),
        embeddings=_read_only(_normalise_rows(embeddings)),
        coords=_read_only(coords),
        model_version=model_version,
        data_version=data_version,
        index=index,
    )


def _load_books(path: Path) -> list[Book]:
    try:
        raw = json.loads(_require(path).read_text(encoding="utf-8"))
        return _books_adapter.validate_python(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        raise ArtifactError(f"Invalid {path.name}: {exc}") from exc


def _load_matrix(path: Path) -> np.ndarray:
    try:
        matrix = np.load(_require(path), allow_pickle=False)
    except (ValueError, OSError, EOFError) as exc:
        raise ArtifactError(f"Invalid {path.name}: {exc}") from exc
    if matrix.ndim != 2 or not np.issubdtype(matrix.dtype, np.floating):
        raise ArtifactError(f"{path.name} must be a 2-D float array, got {matrix.shape}")
    if not np.all(np.isfinite(matrix)):
        raise ArtifactError(f"{path.name} contains NaN or infinite values")
    return matrix.astype(np.float32, copy=False)


def _load_versions(path: Path) -> tuple[str, str | None]:
    """model_version (required) and data_version (optional) from meta.json."""
    try:
        meta = json.loads(_require(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ArtifactError(f"Invalid {path.name}: {exc}") from exc
    if not isinstance(meta, dict):
        meta = {}

    model_version = meta.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        raise ArtifactError(f"{path.name} must contain a non-empty 'model_version'")

    data_version = meta.get("data_version")
    if data_version is not None and (not isinstance(data_version, str) or not data_version):
        raise ArtifactError(f"{path.name} 'data_version' must be a non-empty string if present")
    return model_version, data_version


def _check_shapes(num_books: int, embeddings: np.ndarray, coords: np.ndarray) -> None:
    if num_books == 0:
        raise ArtifactError(f"{BOOKS_FILE} is empty")
    if embeddings.shape[0] != num_books or coords.shape[0] != num_books:
        raise ArtifactError(
            "Row counts differ: "
            f"{BOOKS_FILE}={num_books}, {EMBEDDINGS_FILE}={embeddings.shape[0]}, "
            f"{COORDS_FILE}={coords.shape[0]}"
        )
    if coords.shape[1] != 2:
        raise ArtifactError(f"{COORDS_FILE} must have 2 columns, got {coords.shape[1]}")


def _build_index(books: list[Book]) -> dict[str, int]:
    index = {book.book_id: row for row, book in enumerate(books)}
    if len(index) != len(books):
        raise ArtifactError(f"{BOOKS_FILE} contains duplicate book_id values")
    return index


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)


def _read_only(matrix: np.ndarray) -> np.ndarray:
    matrix.flags.writeable = False
    return matrix


def _require(path: Path) -> Path:
    if not path.is_file():
        raise ArtifactError(f"Missing artifact file: {path}")
    return path
