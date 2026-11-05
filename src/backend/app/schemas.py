"""Pydantic models: the JSON contract described in SPEC.md section 4."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_SEEDS_PER_READER = 5
MAX_K = 20
BookId = Annotated[str, Field(min_length=1, max_length=64)]
ArtifactFingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Aggregation = Literal["least_misery", "average"]
# The frontend prototype spells this mode with a hyphen
AGGREGATION_ALIASES = {"least-misery": "least_misery"}
Vote = Literal["would_read", "not_for_us"]


class BookSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    book_id: BookId
    title: str
    author: str
    year: int | None = None
    cover_url: str | None = None


class Book(BookSummary):
    shelves: tuple[str, ...] = ()


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    model_version: str
    artifact_fingerprint: ArtifactFingerprint
    data_version: str | None
    num_books: int


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reader_a: list[BookId] = Field(min_length=1, max_length=MAX_SEEDS_PER_READER)
    reader_b: list[BookId] = Field(min_length=1, max_length=MAX_SEEDS_PER_READER)
    k: int = Field(default=5, ge=1, le=MAX_K)
    aggregation: Aggregation = "least_misery"

    @field_validator("reader_a", "reader_b")
    @classmethod
    def no_duplicates(cls, ids: list[str]) -> list[str]:
        if len(set(ids)) != len(ids):
            raise ValueError("each reader's books must be distinct")
        return ids

    @field_validator("aggregation", mode="before")
    @classmethod
    def accept_aliases(cls, value: object) -> object:
        return AGGREGATION_ALIASES.get(value, value) if isinstance(value, str) else value


class Reason(BaseModel):
    model_config = ConfigDict(frozen=True)

    seed_id: str
    seed_title: str
    same_author: bool
    shared_shelves: tuple[str, ...]
    text: str


class Reasons(BaseModel):
    reader_a: Reason
    reader_b: Reason


class TopShelves(BaseModel):
    reader_a: tuple[str, ...]
    reader_b: tuple[str, ...]


class Position(BaseModel):
    x: float
    y: float


class Recommendation(BaseModel):
    rank: int
    book: Book
    score: float
    fit_a: float
    fit_b: float
    reasons: Reasons
    position: Position


class GalaxyPoint(BaseModel):
    book_id: str
    title: str
    x: float
    y: float


class Galaxy(BaseModel):
    reader_a: list[GalaxyPoint]
    reader_b: list[GalaxyPoint]
    bridges: list[GalaxyPoint]


class RecommendResponse(BaseModel):
    model_version: str
    artifact_fingerprint: ArtifactFingerprint
    aggregation: Aggregation
    top_shelves: TopShelves
    recommendations: list[Recommendation]
    galaxy: Galaxy


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: BookId
    vote: Vote
    model_version: str = Field(min_length=1, max_length=128)
    artifact_fingerprint: ArtifactFingerprint | None = None


class FeedbackResponse(BaseModel):
    ok: bool = True
