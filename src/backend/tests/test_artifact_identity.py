import hashlib
import json
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.artifacts import load_artifacts
from app.config import Settings
from app.main import create_app
from tests.conftest import make_books, write_artifacts

FILES = ("books.json", "coords_2d.npy", "item_embeddings.npy", "meta.json")


def test_fingerprint_matches_deployment_four_file_hash_formula(tmp_path) -> None:
    root = write_artifacts(tmp_path / "m", make_books(3), np.ones((3, 4)), np.zeros((3, 2)))
    file_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in FILES}
    expected = hashlib.sha256(json.dumps(file_hashes, sort_keys=True).encode("utf-8")).hexdigest()

    assert load_artifacts(str(root)).artifact_fingerprint == expected


@pytest.mark.parametrize("changed_file", FILES)
def test_same_model_label_with_different_file_bytes_has_different_identity(
    tmp_path, changed_file: str
) -> None:
    root = write_artifacts(tmp_path / "m", make_books(3), np.ones((3, 4)), np.zeros((3, 2)))
    before = load_artifacts(str(root))
    path = root / changed_file
    if changed_file.endswith(".npy"):
        matrix = np.load(path, allow_pickle=False)
        matrix[0, 0] += 1
        np.save(path, matrix)
    else:
        path.write_bytes(path.read_bytes() + b"\n")

    after = load_artifacts(str(root))

    assert before.model_version == after.model_version
    assert before.artifact_fingerprint != after.artifact_fingerprint


def test_fingerprint_depends_on_contents_not_artifact_location(tmp_path) -> None:
    first = write_artifacts(tmp_path / "a", make_books(3), np.ones((3, 4)), np.zeros((3, 2)))
    second = write_artifacts(tmp_path / "b", make_books(3), np.ones((3, 4)), np.zeros((3, 2)))

    assert load_artifacts(str(first)).artifact_fingerprint == load_artifacts(str(second)).artifact_fingerprint


def test_health_and_recommendation_report_the_loaded_snapshot_after_files_change(tmp_path) -> None:
    root = write_artifacts(tmp_path / "m", make_books(3), np.ones((3, 4)), np.zeros((3, 2)))
    settings = Settings(
        artifact_dir=str(root), feedback_path=tmp_path / "feedback.jsonl", cors_origins=("*",)
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/health").json()
        assert re.fullmatch(r"[0-9a-f]{64}", health["artifact_fingerprint"])
        assert set(health) == {
            "status", "model_version", "artifact_fingerprint", "data_version", "num_books"
        }
        metadata = root / "meta.json"
        metadata.write_bytes(metadata.read_bytes() + b"\n")

        response = client.post("/recommend", json={"reader_a": ["b0"], "reader_b": ["b1"]})

        assert response.status_code == 200
        assert response.json()["artifact_fingerprint"] == health["artifact_fingerprint"]
        assert response.json()["model_version"] == health["model_version"]
        assert set(response.json()) == {
            "model_version", "artifact_fingerprint", "aggregation", "top_shelves",
            "recommendations", "galaxy"
        }
        assert client.get("/health").json()["artifact_fingerprint"] == health["artifact_fingerprint"]
        assert load_artifacts(str(root)).artifact_fingerprint != health["artifact_fingerprint"]


def test_model_load_builds_search_keys_for_the_same_fingerprinted_catalogue(tmp_path) -> None:
    books = make_books(2)
    books[0].update(title="Café—Tales", author="China Miéville")
    root = write_artifacts(tmp_path / "m", books, np.ones((2, 4)), np.zeros((2, 2)))
    loaded = load_artifacts(str(root))
    original_fingerprint = loaded.artifact_fingerprint

    [found] = loaded.search_index.search("cafe tales", 10)
    assert found is loaded.books[0]
    assert found.title == "Café—Tales"
    assert loaded.search_index.search("Mieville", 10) == [found]

    books[0].update(title="Different Title", author="Different Author")
    (root / "books.json").write_text(json.dumps(books), encoding="utf-8")
    replacement = load_artifacts(str(root))

    assert loaded.artifact_fingerprint == original_fingerprint
    assert loaded.search_index.search("cafe tales", 10) == [found]
    assert replacement.artifact_fingerprint != original_fingerprint
    assert replacement.search_index.search("cafe tales", 10) == []
    assert replacement.search_index.search("Different Title", 10) == [replacement.books[0]]
