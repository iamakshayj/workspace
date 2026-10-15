from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_admin, get_current_user
from .config import Settings, get_settings
from .database import BackgroundJob, User, get_session
from .job_service import GENERATION_JOB, create_background_job
from .schemas import BackgroundJobResponse, GenerateFlowchartRequest, GeneratedFlowchart


router = APIRouter(prefix="/flowcharts", tags=["flowchart jobs"])


def serialize_job(job: BackgroundJob) -> BackgroundJobResponse:
    result = GeneratedFlowchart.model_validate(job.result) if job.result else None
    return BackgroundJobResponse(
        id=job.id,
        kind=job.kind,
        status=job.status,
        attempts=job.attempts or 0,
        max_attempts=job.max_attempts,
        result=result,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


@router.post(
    "/generation-jobs",
    response_model=BackgroundJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_generation_job(
    request: GenerateFlowchartRequest,
    user: User = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
) -> BackgroundJobResponse:
    if len(request.text) > settings.max_input_characters:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Input exceeds the {settings.max_input_characters:,}-character limit.",
        )
    job = await create_background_job(
        entity_id=user.entity_id,
        created_by_id=user.id,
        kind=GENERATION_JOB,
        payload={"text": request.text, "title": request.title},
        settings=settings,
    )
    return serialize_job(job)


@router.get("/generation-jobs/{job_id}", response_model=BackgroundJobResponse)
async def get_generation_job(
    job_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BackgroundJobResponse:
    job = await session.get(BackgroundJob, job_id)
    if (
        not job
        or job.kind != GENERATION_JOB
        or job.entity_id != user.entity_id
        or job.created_by_id != user.id
    ):
        raise HTTPException(status_code=404, detail="Generation job not found")
    return serialize_job(job)
