from fastapi.testclient import TestClient


def test_health_reports_loaded_model(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
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
