import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.database import Base, Entity, Project, ProjectCollaborator, User
from backend.app.graphql_schema import Query


def test_project_page_searches_and_walks_a_stable_cursor() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_maker() as session:
            entity = Entity(id="entity-1", name="Scale workspace")
            admin = User(
                id="user-1",
                entity_id=entity.id,
                display_name="Scale Admin",
                email="scale@example.com",
                password_hash="unused",
                role="admin",
            )
            now = datetime(2026, 8, 27, 16, 0, tzinfo=timezone.utc)
            projects = [
                Project(
                    id=f"project-{index}",
                    entity_id=entity.id,
                    owner_id=admin.id,
                    title=title,
                    description=description,
                    source_text="",
                    graph={"title": title, "nodes": [], "edges": []},
                    created_at=now - timedelta(minutes=index),
                    updated_at=now - timedelta(minutes=index),
                )
                for index, (title, description) in enumerate([
                    ("Approval intake", "Review incoming requests"),
                    ("Incident response", "Operations runbook"),
                    ("Vendor onboarding", "Approval and procurement steps"),
                ])
            ]
            session.add_all([entity, admin, *projects])
            await session.flush()
            session.add_all([
                ProjectCollaborator(
                    project_id=project.id,
                    user_id=admin.id,
                    access_role="editor",
                )
                for project in projects
            ])
            await session.commit()
            info = SimpleNamespace(context=SimpleNamespace(session=session, user=admin))

            first_page = await Query().project_page(info, first=2)
            second_page = await Query().project_page(
                info,
                after=first_page.next_cursor,
                first=2,
            )
            search_page = await Query().project_page(info, search="approval", first=10)

            assert [str(project.id) for project in first_page.items] == [
                "project-0",
                "project-1",
            ]
            assert first_page.total_count == 3
            assert first_page.next_cursor
            assert [str(project.id) for project in second_page.items] == ["project-2"]
            assert second_page.next_cursor is None
            assert {str(project.id) for project in search_page.items} == {
                "project-0",
                "project-2",
            }
        await engine.dispose()

    asyncio.run(scenario())
