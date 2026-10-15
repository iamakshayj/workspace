import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, Entity, Project, ProjectCollaborator, User
from backend.app.project_routes import get_project, update_project
from backend.app.schemas import ProjectWrite


def test_rest_project_save_requires_and_advances_a_document_revision() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_maker() as session:
            entity = Entity(id="entity-1", name="Revision workspace")
            admin = User(
                id="user-1",
                entity_id=entity.id,
                display_name="Revision Admin",
                email="revision@example.com",
                password_hash="unused",
                role="admin",
            )
            project = Project(
                id="project-1",
                entity_id=entity.id,
                owner_id=admin.id,
                title="Original",
                source_text="Start",
                graph={"title": "Original", "nodes": [], "edges": []},
                revision=3,
            )
            session.add_all([entity, admin, project])
            await session.flush()
            session.add(ProjectCollaborator(
                project_id=project.id,
                user_id=admin.id,
                access_role="editor",
            ))
            await session.commit()
            payload = ProjectWrite.model_validate({
                "title": "Updated",
                "owner_id": admin.id,
                "collaborator_ids": [admin.id],
                "source_text": "Start then finish",
                "graph": {
                    "title": "Updated",
                    "nodes": [{
                        "id": "start",
                        "label": "Start",
                        "type": "start",
                        "x": 0,
                        "y": 0,
                    }],
                    "edges": [],
                    "questions": [],
                    "warnings": [],
                },
            })

            with pytest.raises(HTTPException) as missing:
                await update_project(project.id, payload, None, admin, session)
            assert missing.value.status_code == 428

            with pytest.raises(HTTPException) as stale:
                await update_project(project.id, payload, 2, admin, session)
            assert stale.value.status_code == 409
            assert stale.value.detail["current_revision"] == 3

            result = await update_project(project.id, payload, 3, admin, session)
            assert result.document_revision == 4
            assert result.title == "Updated"
        await engine.dispose()

    asyncio.run(scenario())


def test_private_project_read_requires_real_object_access() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_maker() as session:
            entity = Entity(id="entity-private", name="Private workspace")
            owner = User(id="owner", entity_id=entity.id, display_name="Owner", email="owner@example.com", password_hash="x", role="basic")
            outsider = User(id="outsider", entity_id=entity.id, display_name="Outsider", email="outsider@example.com", password_hash="x", role="basic")
            project = Project(id="private-project", entity_id=entity.id, owner_id=owner.id, visibility="private", title="Restricted", graph={"title": "Restricted", "nodes": [], "edges": [], "questions": [], "warnings": []})
            session.add_all([entity, owner, outsider, project])
            await session.commit()
            with pytest.raises(HTTPException) as denied:
                await get_project(project.id, outsider, session)
            assert denied.value.status_code == 404
            visible = await get_project(project.id, owner, session)
            assert visible.id == project.id
        await engine.dispose()

    asyncio.run(scenario())
