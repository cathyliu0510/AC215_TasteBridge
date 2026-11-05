from dataclasses import FrozenInstanceError

import pytest

from app.schemas import Book
from app.search import BookSearchIndex, search_books


@pytest.mark.parametrize("query", ["Mieville", "Miéville", "MIE\u0301VILLE"])
@pytest.mark.parametrize("author", ["China Mieville", "China Miéville"])
def test_author_search_matches_accents_in_both_directions(query: str, author: str) -> None:
    book = Book(book_id="accent", title="The City & the City", author=author)

    assert search_books([book], query, 10) == [book]
    assert book.author == author


@pytest.mark.parametrize("query", ["cafe tales", "Café—Tales", "CAFE:  TALES"])
def test_title_search_normalises_accents_punctuation_and_whitespace(query: str) -> None:
    prefix = Book(book_id="first", title="Café: Tales", author="An Author")
    substring = Book(book_id="second", title="More Café—Tales", author="An Author")

    results = search_books([substring, prefix], query, 10)

    assert results == [prefix, substring]
    assert results[0].title == "Café: Tales"


@pytest.mark.parametrize("query", ["---", "’ : ", "\u0301"])
def test_search_returns_no_books_for_normalised_empty_query(query: str) -> None:
    book = Book(book_id="b", title="A Book", author="An Author")

    assert search_books([book], query, 10) == []


@pytest.mark.parametrize(
    ("query", "limit"),
    [
        ("cafe tales", 1),
        ("CAFE: TALES", 3),
        ("Café—Tales", 25),
        ("Miéville", 25),
        ("MIE\u0301VILLE", 1),
        ("china", 1),
        ("unmatched", 10),
        ("---", 10),
        ("", 10),
        ("   ", 25),
    ],
)
def test_precomputed_index_preserves_pure_search_results(query: str, limit: int) -> None:
    books = [
        Book(book_id="a", title="More Café—Tales", author="China Miéville"),
        Book(book_id="b", title="Café: Tales", author="Another Author"),
        Book(book_id="c", title="Café Tales: Again", author="China Mieville"),
        Book(book_id="d", title="Unrelated", author="Café Tales"),
        Book(book_id="e", title="Chinatown", author="Another Author"),
    ]

    found = BookSearchIndex.from_books(books).search(query, limit)

    assert found == search_books(books, query, limit)
    assert all(any(book is original for original in books) for book in found)


def test_search_index_is_immutable_and_keeps_a_catalogue_snapshot() -> None:
    original = Book(book_id="a", title="Café—Tales", author="China Miéville")
    books = [original]
    index = BookSearchIndex.from_books(books)
    books[0] = Book(book_id="b", title="Another Book", author="Another Author")

    assert index.search("cafe tales", 10) == [original]
    assert index.search("another", 10) == []
    with pytest.raises(FrozenInstanceError):
        index._entries = ()
