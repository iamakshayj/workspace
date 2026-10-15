import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.database import (
    Base,
    DataGovernancePolicy,
    Entity,
    FeatureEntitlement,
    LegalHold,
    OrganizationUnit,
    OrganizationUnitMember,
    PolicyRule,
    Project,
    User,
)
from backend.app.policy_engine import (
    PolicyContext,
    entitlement_enabled,
    evaluate_dlp,
    evaluate_policy,
    is_held,
)


def run(scenario):
    asyncio.run(scenario())


async def fixture_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, maker


def test_policy_engine_combines_project_roles_groups_fields_and_explicit_denies() -> None:
    async def scenario() -> None:
        engine, maker = await fixture_session()
        async with maker() as session:
            entity = Entity(id="entity", name="Enterprise")
            admin = User(id="admin", entity_id="entity", email="admin@example.com", display_name="Admin", password_hash="x", role="admin")
            member = User(id="member", entity_id="entity", email="member@example.com", display_name="Member", password_hash="x", role="basic")
            group = OrganizationUnit(id="security", entity_id="entity", name="Security", unit_type="group")
            project = Project(id="project", entity_id="entity", owner_id="admin", title="Restricted", source_text="", graph={"nodes": [], "edges": []}, visibility="restricted")
            session.add_all([entity, admin, member, group, project, OrganizationUnitMember(unit_id="security", user_id="member")])
            session.add(PolicyRule(
                id="allow-group", entity_id="entity", name="Security reviewers", effect="allow",
                actions=["read"], subject_type="group", subject_id="security", resource_type="project",
                resource_id="project", created_by_id="admin", priority=100,
            ))
            session.add(PolicyRule(
                id="deny-secret", entity_id="entity", name="Hide finance fields", effect="deny",
                actions=["read"], subject_type="role", subject_id="basic", resource_type="project",
                resource_id="project", fields=["budget"], created_by_id="admin", priority=200,
            ))
            await session.commit()

            allowed = await evaluate_policy(session, member, PolicyContext(
                action="read", resource_type="project", resource_id="project", project_id="project", fields={"title"},
            ))
            assert allowed.allowed is True
            assert allowed.reason == "explicit_allow"

            denied = await evaluate_policy(session, member, PolicyContext(
                action="read", resource_type="project", resource_id="project", project_id="project", fields={"budget"},
            ))
            assert denied.allowed is False
            assert denied.reason == "explicit_deny"
            assert denied.denied_fields == ["budget"]
        await engine.dispose()

    run(scenario)


def test_dlp_decisions_return_metadata_only_and_block_configured_egress() -> None:
    async def scenario() -> None:
        engine, maker = await fixture_session()
        async with maker() as session:
            entity = Entity(id="entity", name="Enterprise")
            admin = User(id="admin", entity_id="entity", email="admin@example.com", display_name="Admin", password_hash="x", role="admin")
            session.add_all([entity, admin, DataGovernancePolicy(
                id="dlp", entity_id="entity", name="Secrets", kind="dlp", applies_to=["assistant"],
                classification="restricted", enforcement="block",
                configuration={"detectors": ["credential"], "blocked_actions": ["ai.send"], "obligations": ["security_review"]},
                created_by_id="admin",
            )])
            await session.commit()
            secret_value = "api_key=supersecretvalue"
            decision = await evaluate_dlp(session, admin, content=secret_value, source_type="assistant", action="ai.send")
            assert decision.allowed is False
            assert decision.classification == "restricted"
            assert decision.findings == [{"type": "credential", "count": 1, "policy_id": "dlp"}]
            assert secret_value not in str(decision.as_dict())
            assert decision.obligations == ["security_review"]
        await engine.dispose()

    run(scenario)


def test_legal_holds_and_entitlement_windows_are_server_evaluated() -> None:
    async def scenario() -> None:
        engine, maker = await fixture_session()
        async with maker() as session:
            entity = Entity(id="entity", name="Enterprise")
            admin = User(id="admin", entity_id="entity", email="admin@example.com", display_name="Admin", password_hash="x", role="admin")
            session.add_all([
                entity, admin,
                LegalHold(id="hold", entity_id="entity", name="Matter 1", scope_type="project", scope_id="project", reason="Litigation", created_by_id="admin"),
                FeatureEntitlement(id="feature", entity_id="entity", feature="semantic_search", enabled=False, updated_by_id="admin"),
            ])
            await session.commit()
            assert await is_held(session, "entity", "project", "project") is True
            assert await is_held(session, "entity", "document", "doc") is False
            assert await entitlement_enabled(session, "entity", "semantic_search") is False
            assert await entitlement_enabled(session, "entity", "default_feature") is True
        await engine.dispose()

    run(scenario)
