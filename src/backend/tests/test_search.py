import pytest

from app.schemas import Book
from app.search import search_books


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
