from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import hash_password
from .config import Settings, get_settings
from .database import Entity, User, get_session
from .schemas import (
    InternalAdminResponse,
    InternalEntityCreate,
    InternalEntityResponse,
    InternalEntityUpdate,
)


router = APIRouter(prefix="/internal/entities", tags=["internal entities"])


def require_internal_key(
    supplied_key: str | None = Header(default=None, alias="X-FlowForge-Internal-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not supplied_key or not compare_digest(supplied_key, settings.internal_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid internal API key is required",
        )


def serialize_admin(user: User) -> InternalAdminResponse:
    return InternalAdminResponse(
        id=user.id,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
    )


async def serialize_entity(entity: Entity, session: AsyncSession) -> InternalEntityResponse:
    admins = await session.scalars(
        select(User)
        .where(User.entity_id == entity.id, User.role == "admin")
        .order_by(User.created_at.asc())
    )
    return InternalEntityResponse(
        id=entity.id,
        name=entity.name,
        admins=[serialize_admin(admin) for admin in admins],
        max_users=entity.max_users,
        max_projects=entity.max_projects,
        max_storage_bytes=entity.max_storage_bytes,
        max_monthly_generations=entity.max_monthly_generations,
        max_pending_generations=entity.max_pending_generations,
        data_region=entity.data_region,
        data_residency_locked=entity.data_residency_locked,
        created_at=entity.created_at,
    )


@router.post(
    "",
    response_model=InternalEntityResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_key)],
)
async def create_entity(
    payload: InternalEntityCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> InternalEntityResponse:
    if payload.data_region != settings.deployment_region:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"This deployment serves {settings.deployment_region}; provision the entity "
                    f"on a {payload.data_region} deployment to keep data in that region"),
        )
    emails = [admin.email for admin in payload.admins]
    existing_email = await session.scalar(select(User.email).where(User.email.in_(emails)).limit(1))
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account already uses {existing_email}",
        )

    entity = Entity(
        name=payload.name,
        max_users=payload.max_users,
        max_projects=payload.max_projects,
        max_storage_bytes=payload.max_storage_bytes,
        max_monthly_generations=payload.max_monthly_generations,
        max_pending_generations=payload.max_pending_generations,
        data_region=payload.data_region,
        data_residency_locked=payload.data_residency_locked,
    )
    session.add(entity)
    await session.flush()
    admins = [
        User(
            entity_id=entity.id,
            role="admin",
            display_name=admin.display_name,
            email=admin.email,
            password_hash=hash_password(admin.password),
        )
        for admin in payload.admins
    ]
    session.add_all(admins)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more admin email addresses are already in use",
        ) from error
    await session.refresh(entity)
    for admin in admins:
        await session.refresh(admin)
    return InternalEntityResponse(
        id=entity.id,
        name=entity.name,
        admins=[serialize_admin(admin) for admin in admins],
        max_users=entity.max_users,
        max_projects=entity.max_projects,
        max_storage_bytes=entity.max_storage_bytes,
        max_monthly_generations=entity.max_monthly_generations,
        max_pending_generations=entity.max_pending_generations,
        data_region=entity.data_region,
        data_residency_locked=entity.data_residency_locked,
        created_at=entity.created_at,
    )


@router.get(
    "",
    response_model=list[InternalEntityResponse],
    dependencies=[Depends(require_internal_key)],
)
async def list_entities(
    session: AsyncSession = Depends(get_session),
) -> list[InternalEntityResponse]:
    entities = await session.scalars(select(Entity).order_by(Entity.created_at.desc()).limit(200))
    return [await serialize_entity(entity, session) for entity in entities]


@router.patch(
    "/{entity_id}",
    response_model=InternalEntityResponse,
    dependencies=[Depends(require_internal_key)],
)
async def update_entity(
    entity_id: str,
    payload: InternalEntityUpdate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> InternalEntityResponse:
    entity = await session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    changes = payload.model_dump(exclude_none=True)
    requested_region = changes.get("data_region")
    requested_lock = changes.get("data_residency_locked")
    if requested_region and requested_region != entity.data_region:
        if entity.data_residency_locked:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Data residency is locked for this entity")
        if requested_region != settings.deployment_region:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Move the entity to a {requested_region} deployment before changing its residency region",
            )
    if entity.data_residency_locked and requested_lock is False:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A data residency lock cannot be removed")
    for field, value in changes.items():
        setattr(entity, field, value)
    await session.commit()
    await session.refresh(entity)
    return await serialize_entity(entity, session)
