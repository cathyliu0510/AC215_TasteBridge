"""Catalogue search for the 'Pick your five' screen (SPEC.md 4.2)."""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.schemas import Book


@dataclass(frozen=True)
class BookSearchIndex:
    """Immutable catalogue keys computed once, without retaining user queries."""

    _entries: tuple[tuple[Book, str, str], ...] = field(repr=False)

    @classmethod
    def from_books(cls, books: Sequence[Book]) -> "BookSearchIndex":
        return cls(
            tuple((book, _search_text(book.title), _search_text(book.author)) for book in books)
        )

    def search(self, query: str, limit: int) -> list[Book]:
        needle = _search_text(query)
        if not needle:
            return []

        title_prefix: list[Book] = []
        other_matches: list[Book] = []
        for book, title, author in self._entries:
            if title.startswith(needle):
                title_prefix.append(book)
            elif needle in title or needle in author:
                other_matches.append(book)
            if len(title_prefix) >= limit:
                break
        return (title_prefix + other_matches)[:limit]


def search_books(books: Sequence[Book], query: str, limit: int) -> list[Book]:
    """Match titles/authors across accents and punctuation, with title prefixes first."""
    needle = _search_text(query)
    if not needle:
        return []

    title_prefix: list[Book] = []
    other_matches: list[Book] = []
    for book in books:
        title = _search_text(book.title)
        if title.startswith(needle):
            title_prefix.append(book)
        elif needle in title or needle in _search_text(book.author):
            other_matches.append(book)
        if len(title_prefix) >= limit:
            break
    return (title_prefix + other_matches)[:limit]


def _search_text(value: str) -> str:
    """Create a search key without changing the catalogue's display strings."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    characters = (
        " " if unicodedata.category(char).startswith("P") else char
        for char in decomposed
        if not unicodedata.category(char).startswith("M")
    )
    return " ".join("".join(characters).split())
