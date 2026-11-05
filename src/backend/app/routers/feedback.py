import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.artifacts import ModelArtifacts
from app.dependencies import get_artifacts, get_feedback_store
from app.feedback import FeedbackStore, FeedbackStoreError
from app.schemas import FeedbackRequest, FeedbackResponse

logger = logging.getLogger("tastebridge.feedback")

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse)
def post_feedback(
    vote: FeedbackRequest,
    artifacts: Annotated[ModelArtifacts, Depends(get_artifacts)],
    store: Annotated[FeedbackStore, Depends(get_feedback_store)],
) -> FeedbackResponse:
    if artifacts.book(vote.book_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Unknown book_id: {vote.book_id}"
        )
    if vote.model_version != artifacts.model_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Feedback model_version does not match the loaded model. "
            "Refresh recommendations and try again.",
        )
    if (
        vote.artifact_fingerprint is not None
        and vote.artifact_fingerprint != artifacts.artifact_fingerprint
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Feedback artifact_fingerprint does not match the loaded model. "
            "Refresh recommendations and try again.",
        )
    try:
        store.record(vote.book_id, vote.vote, artifacts.model_version)
    except FeedbackStoreError:
        logger.exception("Failed to store feedback vote")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback could not be saved right now. Please try again.",
        ) from None
    return FeedbackResponse()
