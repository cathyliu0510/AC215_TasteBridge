import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.artifacts import ArtifactError, load_artifacts
from app.config import Settings
from app.main import create_app
from tests.conftest import make_books, write_artifacts


def test_loads_valid_folder_and_normalises_embeddings(tmp_path) -> None:
    root = write_artifacts(
        tmp_path / "m", make_books(3), np.array([[3.0, 4.0], [1, 0], [0, 2]]), np.zeros((3, 2))
    )

    artifacts = load_artifacts(str(root))

    assert artifacts.model_version == "test-v1"
    assert artifacts.row_of("b1") == 1
    assert artifacts.book("missing") is None
    np.testing.assert_allclose(np.linalg.norm(artifacts.embeddings, axis=1), 1.0, rtol=1e-6)
    assert not artifacts.embeddings.flags.writeable


def test_reads_data_version_from_meta(tmp_path) -> None:
    meta = {"model_version": "b2-als-gr-1", "data_version": "gr-1"}
    root = write_artifacts(tmp_path / "m", make_books(1), np.ones((1, 4)), np.zeros((1, 2)), meta=meta)

    assert load_artifacts(str(root)).data_version == "gr-1"


def test_data_version_is_none_when_meta_omits_it(tmp_path) -> None:
    root = write_artifacts(tmp_path / "m", make_books(1), np.ones((1, 4)), np.zeros((1, 2)))

    assert load_artifacts(str(root)).data_version is None


@pytest.mark.parametrize("bad", ["", 42, ["gr-1"]])
def test_rejects_data_version_that_is_not_a_non_empty_string(tmp_path, bad: object) -> None:
    meta = {"model_version": "m", "data_version": bad}
    root = write_artifacts(tmp_path / "m", make_books(1), np.ones((1, 4)), np.zeros((1, 2)), meta=meta)

    with pytest.raises(ArtifactError, match="data_version"):
        load_artifacts(str(root))


def test_fails_fast_when_row_counts_differ(tmp_path) -> None:
    root = write_artifacts(tmp_path / "m", make_books(3), np.ones((2, 4)), np.zeros((3, 2)))

    with pytest.raises(ArtifactError, match="Row counts differ"):
        load_artifacts(str(root))


@pytest.mark.parametrize("missing", ["books.json", "item_embeddings.npy", "coords_2d.npy", "meta.json"])
def test_fails_when_a_file_is_missing(tmp_path, missing: str) -> None:
    root = write_artifacts(tmp_path / "m", make_books(2), np.ones((2, 4)), np.zeros((2, 2)))
    (root / missing).unlink()

    with pytest.raises(ArtifactError, match="Missing artifact file"):
        load_artifacts(str(root))


def test_rejects_duplicate_book_ids(tmp_path) -> None:
    books = make_books(2)
    books[1]["book_id"] = books[0]["book_id"]
    root = write_artifacts(tmp_path / "m", books, np.ones((2, 4)), np.zeros((2, 2)))

    with pytest.raises(ArtifactError, match="duplicate"):
        load_artifacts(str(root))


def test_rejects_books_missing_required_fields(tmp_path) -> None:
    root = write_artifacts(tmp_path / "m", [{"book_id": "x"}], np.ones((1, 4)), np.zeros((1, 2)))

    with pytest.raises(ArtifactError, match="Invalid books.json"):
        load_artifacts(str(root))


def test_rejects_meta_without_model_version(tmp_path) -> None:
    root = write_artifacts(
        tmp_path / "m", make_books(1), np.ones((1, 4)), np.zeros((1, 2)), meta={"x": 1}
    )

    with pytest.raises(ArtifactError, match="model_version"):
        load_artifacts(str(root))


def test_rejects_coords_without_two_columns(tmp_path) -> None:
    root = write_artifacts(tmp_path / "m", make_books(2), np.ones((2, 4)), np.zeros((2, 3)))

    with pytest.raises(ArtifactError, match="2 columns"):
        load_artifacts(str(root))


def test_rejects_non_finite_embeddings(tmp_path) -> None:
    embeddings = np.ones((2, 4))
    embeddings[0, 0] = np.nan
    root = write_artifacts(tmp_path / "m", make_books(2), embeddings, np.zeros((2, 2)))

    with pytest.raises(ArtifactError, match="NaN"):
        load_artifacts(str(root))


def test_rejects_missing_directory_and_gcs_paths(tmp_path) -> None:
    with pytest.raises(ArtifactError, match="not found"):
        load_artifacts(str(tmp_path / "nowhere"))
    with pytest.raises(ArtifactError, match="GCS"):
        load_artifacts("gs://bucket/model")


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("books.json", "{not json", "Invalid books.json"),
        ("meta.json", "{not json", "Invalid meta.json"),
        ("meta.json", "[]", "model_version"),
        ("item_embeddings.npy", "not a numpy file", "Invalid item_embeddings.npy"),
    ],
)
def test_rejects_corrupt_files(tmp_path, filename: str, content: str, message: str) -> None:
    root = write_artifacts(tmp_path / "m", make_books(2), np.ones((2, 4)), np.zeros((2, 2)))
    (root / filename).write_text(content, encoding="utf-8")

    with pytest.raises(ArtifactError, match=message):
        load_artifacts(str(root))


def test_rejects_empty_catalogue(tmp_path) -> None:
    root = write_artifacts(tmp_path / "m", [], np.ones((0, 4)), np.zeros((0, 2)))

    with pytest.raises(ArtifactError, match="empty"):
        load_artifacts(str(root))


def test_rejects_truncated_npy_and_non_utf8_json(tmp_path) -> None:
    root = write_artifacts(tmp_path / "m", make_books(2), np.ones((2, 4)), np.zeros((2, 2)))
    npy = root / "coords_2d.npy"
    npy.write_bytes(npy.read_bytes()[:-8])
    with pytest.raises(ArtifactError, match="coords_2d.npy"):
        load_artifacts(str(root))

    root = write_artifacts(tmp_path / "n", make_books(2), np.ones((2, 4)), np.zeros((2, 2)))
    (root / "books.json").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ArtifactError, match="books.json"):
        load_artifacts(str(root))


@pytest.mark.parametrize(
    ("filename", "values", "message"),
    [
        ("item_embeddings.npy", np.empty((2, 0)), "at least 1 factor"),
        ("item_embeddings.npy", np.full((2, 4), 1e100), "float32 range"),
        ("coords_2d.npy", np.full((2, 2), -1e100), "float32 range"),
        ("item_embeddings.npy", np.full((2, 4), 1e-100), "too small for float32"),
        ("coords_2d.npy", np.full((2, 2), 1e-100), "too small for float32"),
    ],
)
def test_invalid_model_prevents_api_startup(tmp_path, filename, values, message) -> None:
    root = write_artifacts(tmp_path / "m", make_books(2), np.ones((2, 4)), np.zeros((2, 2)))
    np.save(root / filename, values)
    settings = Settings(
        artifact_dir=str(root), feedback_path=tmp_path / "feedback.jsonl", cors_origins=("*",)
    )

    with pytest.raises(ArtifactError, match=message):
        with TestClient(create_app(settings)):
            pytest.fail("An invalid model must never start serving requests")


def test_normalises_extreme_finite_float32_rows_without_losing_direction(tmp_path) -> None:
    maximum = np.finfo(np.float32).max
    smallest = np.nextafter(np.float32(0), np.float32(1))
    embeddings = np.array(
        [[1e30, -1e30], [maximum, maximum], [smallest, -smallest], [0, 0]],
        dtype=np.float32,
    )
    root = write_artifacts(tmp_path / "m", make_books(4), embeddings, np.zeros((4, 2)))

    artifacts = load_artifacts(str(root))

    expected = np.array([[1, -1], [1, 1], [1, -1]], dtype=np.float64) / np.sqrt(2)
    assert artifacts.embeddings.dtype == np.float32
    assert np.all(np.isfinite(artifacts.embeddings))
    np.testing.assert_allclose(artifacts.embeddings[:3], expected, rtol=1e-6)
    np.testing.assert_array_equal(artifacts.embeddings[3], [0, 0])
