"""Load and validate a model artifact folder (SPEC.md section 5).

The API fails fast at startup if the folder is incomplete or inconsistent,
so a bad hand-off from the modeling pipeline never serves wrong answers.
"""

import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pydantic import TypeAdapter, ValidationError

from app.schemas import Book
from app.search import BookSearchIndex

BOOKS_FILE = "books.json"
EMBEDDINGS_FILE = "item_embeddings.npy"
COORDS_FILE = "coords_2d.npy"
META_FILE = "meta.json"
ARTIFACT_FILES = (BOOKS_FILE, EMBEDDINGS_FILE, COORDS_FILE, META_FILE)

_books_adapter = TypeAdapter(list[Book])


class ArtifactError(RuntimeError):
    """The artifact folder is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class ModelArtifacts:
    books: tuple[Book, ...]
    embeddings: np.ndarray  # rows L2-normalised, read-only
    coords: np.ndarray  # shape (num_books, 2), read-only
    model_version: str
    artifact_fingerprint: str  # SHA256 identity of the four original file bytes
    data_version: str | None  # dataset snapshot the model was trained on, if recorded
    index: dict[str, int] = field(repr=False)
    search_index: BookSearchIndex = field(repr=False)

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

    # Parse and hash the same startup snapshot. Subsequent file changes cannot
    # change the identity reported for the arrays already held by this process.
    contents = {name: _read_artifact(root / name) for name in ARTIFACT_FILES}
    books = _load_books(root / BOOKS_FILE, contents[BOOKS_FILE])
    embeddings = _load_matrix(root / EMBEDDINGS_FILE, contents[EMBEDDINGS_FILE])
    coords = _load_matrix(root / COORDS_FILE, contents[COORDS_FILE])
    model_version, data_version = _load_versions(root / META_FILE, contents[META_FILE])

    _check_shapes(len(books), embeddings, coords)
    index = _build_index(books)

    return ModelArtifacts(
        books=tuple(books),
        embeddings=_read_only(_normalise_rows(embeddings)),
        coords=_read_only(coords),
        model_version=model_version,
        artifact_fingerprint=_artifact_fingerprint(contents),
        data_version=data_version,
        index=index,
        search_index=BookSearchIndex.from_books(books),
    )


def _load_books(path: Path, content: bytes) -> list[Book]:
    try:
        raw = json.loads(content.decode("utf-8"))
        return _books_adapter.validate_python(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        raise ArtifactError(f"Invalid {path.name}: {exc}") from exc


def _load_matrix(path: Path, content: bytes) -> np.ndarray:
    try:
        matrix = np.load(io.BytesIO(content), allow_pickle=False)
    except (ValueError, OSError, EOFError) as exc:
        raise ArtifactError(f"Invalid {path.name}: {exc}") from exc
    if matrix.ndim != 2 or not np.issubdtype(matrix.dtype, np.floating):
        raise ArtifactError(f"{path.name} must be a 2-D float array, got {matrix.shape}")
    if not np.all(np.isfinite(matrix)):
        raise ArtifactError(f"{path.name} contains NaN or infinite values")
    float32_max = np.finfo(np.float32).max
    if np.any(matrix > float32_max) or np.any(matrix < -float32_max):
        raise ArtifactError(f"{path.name} contains values outside the float32 range")
    with np.errstate(under="ignore"):
        converted = matrix.astype(np.float32, copy=False)
    if not np.all(np.isfinite(converted)):
        raise ArtifactError(f"{path.name} contains NaN or infinite values after float32 conversion")
    if np.any((matrix != 0) & (converted == 0)):
        raise ArtifactError(f"{path.name} contains non-zero values too small for float32")
    return converted


def _load_versions(path: Path, content: bytes) -> tuple[str, str | None]:
    """model_version (required) and data_version (optional) from meta.json."""
    try:
        meta = json.loads(content.decode("utf-8"))
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
    if embeddings.shape[1] == 0:
        raise ArtifactError(f"{EMBEDDINGS_FILE} must have at least 1 factor column")
    if coords.shape[1] != 2:
        raise ArtifactError(f"{COORDS_FILE} must have 2 columns, got {coords.shape[1]}")


def _build_index(books: list[Book]) -> dict[str, int]:
    index = {book.book_id: row for row, book in enumerate(books)}
    if len(index) != len(books):
        raise ArtifactError(f"{BOOKS_FILE} contains duplicate book_id values")
    return index


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    # Every finite float32 value can be squared safely in float64. Computing
    # norms there avoids overflow for large rows and underflow for small rows.
    norms = np.linalg.norm(matrix.astype(np.float64), axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)


def _read_only(matrix: np.ndarray) -> np.ndarray:
    matrix.flags.writeable = False
    return matrix


def _artifact_fingerprint(contents: dict[str, bytes]) -> str:
    """Match deploy/cloud-run's four-file model hash, retaining all 64 hex digits."""
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()


def _read_artifact(path: Path) -> bytes:
    try:
        return _require(path).read_bytes()
    except OSError as exc:
        raise ArtifactError(f"Could not read artifact file: {path.name}") from exc


def _require(path: Path) -> Path:
    if not path.is_file():
        raise ArtifactError(f"Missing artifact file: {path}")
    return path
