import re
from urllib.parse import quote

import numpy as np
from fastapi.testclient import TestClient

from app import search as catalogue_search
from app.config import Settings
from app.main import create_app
from tests.conftest import make_books, write_artifacts


def test_health_reports_loaded_model(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert re.fullmatch(r"[0-9a-f]{64}", body.pop("artifact_fingerprint"))
    assert body == {
        "status": "ok",
        "model_version": "sample-shelf-toy-v1",
        "data_version": "hand-curated-sample-52",
        "num_books": 52,
    }


def test_docs_page_is_served(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200


def test_get_book_returns_full_details(client: TestClient) -> None:
    response = client.get("/books/w_1001")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Mistborn: The Final Empire"
    assert body["author"] == "Brandon Sanderson"
    assert "heist" in body["shelves"]
    assert body["cover_url"] is None


def test_get_unknown_book_returns_404(client: TestClient) -> None:
    response = client.get("/books/w_9999")

    assert response.status_code == 404
    assert "w_9999" in response.json()["detail"]


def test_search_puts_title_prefix_matches_first(client: TestClient) -> None:
    response = client.get("/books/search", params={"q": "sh"})

    titles = [book["title"] for book in response.json()]
    assert response.status_code == 200
    assert titles == [
        "Sharp Objects",
        "Shutter Island",
        "The Fellowship of the Ring",
        "The Shadow of the Wind",
    ]


def test_search_matches_author_case_insensitively(client: TestClient) -> None:
    response = client.get("/books/search", params={"q": "GILLIAN"})

    titles = {book["title"] for book in response.json()}
    assert titles == {"Gone Girl", "Sharp Objects", "Dark Places"}


def test_search_results_omit_shelves(client: TestClient) -> None:
    body = client.get("/books/search", params={"q": "mistborn"}).json()

    assert body == [
        {
            "book_id": "w_1001",
            "title": "Mistborn: The Final Empire",
            "author": "Brandon Sanderson",
            "year": None,
            "cover_url": None,
        }
    ]


def test_search_respects_limit(client: TestClient) -> None:
    body = client.get("/books/search", params={"q": "e", "limit": 3}).json()

    assert len(body) == 3


def test_search_empty_or_unmatched_query_returns_empty_list(client: TestClient) -> None:
    assert client.get("/books/search", params={"q": ""}).json() == []
    assert client.get("/books/search", params={"q": "   "}).json() == []
    assert client.get("/books/search", params={"q": "zzzz"}).json() == []


def test_search_rejects_bad_parameters(client: TestClient) -> None:
    assert client.get("/books/search").status_code == 422
    assert client.get("/books/search", params={"q": "a" * 101}).status_code == 422
    assert client.get("/books/search", params={"q": "a", "limit": 0}).status_code == 422
    assert client.get("/books/search", params={"q": "a", "limit": 26}).status_code == 422


def test_search_fills_limit_with_title_prefix_matches_first(client: TestClient) -> None:
    titles = [b["title"] for b in client.get("/books/search", params={"q": "the", "limit": 3}).json()]

    assert len(titles) == 3
    assert all(title.lower().startswith("the") for title in titles)


def test_book_search_and_detail_preserve_opaque_ids_and_display_text(tmp_path) -> None:
    books = make_books(3)
    books[0].update(
        book_id="opaque/A?", title="Café—Tales", author="China Miéville"
    )
    root = write_artifacts(tmp_path / "m", books, np.ones((3, 4)), np.zeros((3, 2)))
    settings = Settings(
        artifact_dir=str(root), feedback_path=tmp_path / "feedback.jsonl", cors_origins=("*",)
    )

    with TestClient(create_app(settings)) as client:
        for query in ("cafe tales", "Café: Tales", "Mieville", "Miéville"):
            response = client.get("/books/search", params={"q": query})
            assert response.status_code == 200
            [summary] = response.json()
            assert summary["book_id"] == "opaque/A?"
            assert summary["title"] == "Café—Tales"
            assert summary["author"] == "China Miéville"

        response = client.get(f"/books/{quote(summary['book_id'], safe='')}")
        assert response.status_code == 200
        assert response.json()["book_id"] == "opaque/A?"
        assert response.json()["title"] == "Café—Tales"
        assert client.get("/books/unknown%2Fid").status_code == 404

        response = client.post(
            "/recommend", json={"reader_a": [summary["book_id"]], "reader_b": ["b1"]}
        )
        assert response.status_code == 200
        assert response.json()["galaxy"]["reader_a"][0]["book_id"] == "opaque/A?"


def test_search_route_uses_startup_keys_and_only_normalises_the_current_query(
    client: TestClient, monkeypatch
) -> None:
    normalise = catalogue_search._search_text
    calls = []

    def observe_normalisation(value: str) -> str:
        calls.append(value)
        return normalise(value)

    monkeypatch.setattr(catalogue_search, "_search_text", observe_normalisation)

    for query in ("GILLIAN", "Mistborn", "GILLIAN"):
        response = client.get("/books/search", params={"q": query})
        assert response.status_code == 200
        assert response.json()

    assert calls == ["GILLIAN", "Mistborn", "GILLIAN"]
