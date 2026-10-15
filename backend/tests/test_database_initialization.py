import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app import database


def test_database_initialization_backfills_owner_access_role(tmp_path, monkeypatch) -> None:
    async def exercise() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workspace.db'}")
        monkeypatch.setattr(database, "engine", engine)

        await database.init_database()
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            entity = database.Entity(id="entity", name="Workspace")
            owner = database.User(
                id="owner",
                entity_id=entity.id,
                email="owner@example.com",
                display_name="Owner",
                password_hash="unused",
                role="basic",
            )
            project = database.Project(
                id="project",
                entity_id=entity.id,
                owner_id=owner.id,
                title="Deployment",
                graph={"nodes": [], "edges": []},
            )
            session.add_all([entity, owner, project])
            await session.commit()

        await database.init_database()

        async with session_factory() as session:
            collaborator = await session.scalar(
                select(database.ProjectCollaborator).where(
                    database.ProjectCollaborator.project_id == "project",
                    database.ProjectCollaborator.user_id == "owner",
                )
            )
            assert collaborator is not None
            assert collaborator.access_role == "viewer"

        await engine.dispose()

    asyncio.run(exercise())
