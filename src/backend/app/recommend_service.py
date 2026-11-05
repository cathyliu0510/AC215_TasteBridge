"""Builds the /recommend response from a request and the loaded artifacts."""

from collections.abc import Sequence

from app.artifacts import ModelArtifacts
from app.explanations import build_reason, closest_seed_row, top_shelves
from app.recommender import ScoredBook, rank_bridges
from app.schemas import (
    Galaxy,
    GalaxyPoint,
    Position,
    Reason,
    Reasons,
    Recommendation,
    RecommendRequest,
    RecommendResponse,
    TopShelves,
)


class UnknownBooksError(LookupError):
    def __init__(self, unknown_ids: list[str]) -> None:
        super().__init__(f"Unknown book_id values: {unknown_ids}")
        self.unknown_ids = unknown_ids


def recommend(artifacts: ModelArtifacts, request: RecommendRequest) -> RecommendResponse:
    _ensure_known(artifacts, [*request.reader_a, *request.reader_b])
    rows_a = [artifacts.index[book_id] for book_id in request.reader_a]
    rows_b = [artifacts.index[book_id] for book_id in request.reader_b]

    scored = rank_bridges(
        artifacts.embeddings, rows_a, rows_b, request.k, request.aggregation
    )
    recommendations = [
        _to_recommendation(artifacts, rank, item, rows_a, rows_b)
        for rank, item in enumerate(scored, start=1)
    ]
    galaxy = Galaxy(
        reader_a=[_galaxy_point(artifacts, row) for row in rows_a],
        reader_b=[_galaxy_point(artifacts, row) for row in rows_b],
        bridges=[_galaxy_point(artifacts, item.row) for item in scored],
    )
    return RecommendResponse(
        model_version=artifacts.model_version,
        artifact_fingerprint=artifacts.artifact_fingerprint,
        aggregation=request.aggregation,
        top_shelves=TopShelves(
            reader_a=top_shelves([artifacts.books[row] for row in rows_a]),
            reader_b=top_shelves([artifacts.books[row] for row in rows_b]),
        ),
        recommendations=recommendations,
        galaxy=galaxy,
    )


def _ensure_known(artifacts: ModelArtifacts, book_ids: Sequence[str]) -> None:
    """Raise listing every unknown ID at once, so the caller can fix them all."""
    unknown = [
        book_id for book_id in dict.fromkeys(book_ids) if artifacts.row_of(book_id) is None
    ]
    if unknown:
        raise UnknownBooksError(unknown)


def _to_recommendation(
    artifacts: ModelArtifacts,
    rank: int,
    item: ScoredBook,
    rows_a: Sequence[int],
    rows_b: Sequence[int],
) -> Recommendation:
    book = artifacts.books[item.row]
    x, y = artifacts.coords[item.row]
    return Recommendation(
        rank=rank,
        book=book,
        score=round(item.score, 4),
        fit_a=round(item.fit_a, 4),
        fit_b=round(item.fit_b, 4),
        reasons=Reasons(
            reader_a=_reason_for(artifacts, item.row, rows_a),
            reader_b=_reason_for(artifacts, item.row, rows_b),
        ),
        position=Position(x=float(x), y=float(y)),
    )


def _reason_for(artifacts: ModelArtifacts, target_row: int, seed_rows: Sequence[int]) -> Reason:
    closest = closest_seed_row(artifacts.embeddings, target_row, seed_rows)
    return build_reason(
        recommended=artifacts.books[target_row],
        closest_seed=artifacts.books[closest],
        reader_seeds=[artifacts.books[row] for row in seed_rows],
    )


def _galaxy_point(artifacts: ModelArtifacts, row: int) -> GalaxyPoint:
    book = artifacts.books[row]
    x, y = artifacts.coords[row]
    return GalaxyPoint(book_id=book.book_id, title=book.title, x=float(x), y=float(y))
