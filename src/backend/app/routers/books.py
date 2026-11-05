from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.artifacts import ModelArtifacts
from app.dependencies import get_artifacts
from app.schemas import Book, BookSummary
from app.search import search_books

MAX_QUERY_LENGTH = 100
DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 25

router = APIRouter(prefix="/books", tags=["books"])


# Declared before /{book_id:path} so "search" is not treated as a book ID.
@router.get("/search", response_model=list[BookSummary])
def search(
    artifacts: Annotated[ModelArtifacts, Depends(get_artifacts)],
    q: Annotated[str, Query(max_length=MAX_QUERY_LENGTH)],
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_LIMIT)] = DEFAULT_SEARCH_LIMIT,
) -> list[BookSummary]:
    return search_books(artifacts.books, q, limit)


@router.get("/{book_id:path}", response_model=Book)
def get_book(
    book_id: str, artifacts: Annotated[ModelArtifacts, Depends(get_artifacts)]
) -> Book:
    book = artifacts.book(book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown book_id: {book_id}")
    return book
