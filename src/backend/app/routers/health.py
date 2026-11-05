from typing import Annotated

from fastapi import APIRouter, Depends

from app.artifacts import ModelArtifacts
from app.dependencies import get_artifacts
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(artifacts: Annotated[ModelArtifacts, Depends(get_artifacts)]) -> HealthResponse:
    return HealthResponse(
        model_version=artifacts.model_version,
        artifact_fingerprint=artifacts.artifact_fingerprint,
        data_version=artifacts.data_version,
        num_books=len(artifacts.books),
    )
