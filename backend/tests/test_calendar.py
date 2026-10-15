import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import strawberry
from graphql import GraphQLError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.config import get_settings
from backend.app.database import (
    BackgroundJob,
    Base,
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventExternalAttendee,
    Entity,
    Notification,
    User,
)
from backend.app.graphql_schema import CalendarEventInput, Mutation, Query
from backend.app.graphql_schema import CalendarAvailabilityInput


def test_recurring_meetings_materialize_timezone_safe_occurrences(monkeypatch) -> None:
    asyncio.run(exercise_recurring_meetings(monkeypatch))


async def exercise_recurring_meetings(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        entity = Entity(id="series-entity", name="Northwind")
        organizer = User(
            id="series-owner", entity_id=entity.id, email="owner@northwind.example",
            display_name="Owner", password_hash="test", role="admin",
        )
        attendee = User(
            id="series-member", entity_id=entity.id, email="member@northwind.example",
            display_name="Member", password_hash="test", role="basic",
        )
        session.add_all([entity, organizer, attendee])
        await session.commit()
        monkeypatch.setattr("backend.app.graphql_schema.communication_hub.publish", AsyncMock())
        # 09:00 America/Chicago before daylight saving time ends on November 1.
        starts_at = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
        organizer_info = SimpleNamespace(context=SimpleNamespace(session=session, user=organizer))

        first = await Mutation().create_calendar_event(
            organizer_info,
            CalendarEventInput(
                title="Weekly delivery review", event_type="meeting",
                starts_at=starts_at, ends_at=starts_at + timedelta(minutes=45),
                timezone="America/Chicago", attendee_ids=[strawberry.ID(attendee.id)],
                recurrence_frequency="weekly", recurrence_count=4,
            ),
        )

        stored = list(await session.scalars(
            select(CalendarEvent).order_by(CalendarEvent.occurrence_index)
        ))
        assert len(stored) == 4
        assert len({event.series_id for event in stored}) == 1
        assert first.series_id == stored[0].series_id
        assert first.recurrence_count == 4
        assert [event.occurrence_index for event in stored] == [0, 1, 2, 3]
        assert stored[0].starts_at.hour == 14
        assert stored[1].starts_at.hour == 15  # Still 09:00 locally after the DST transition.
        memberships = list(await session.scalars(select(CalendarEventAttendee)))
        assert len(memberships) == 8
        invitations = list(await session.scalars(
            select(Notification).where(Notification.kind == "meeting_invitation")
        ))
        assert len(invitations) == 1

        attendee_info = SimpleNamespace(context=SimpleNamespace(session=session, user=attendee))
        attendee_events = await Query().calendar_events(
            attendee_info, starts_at - timedelta(days=1), starts_at + timedelta(days=30),
        )
        assert len(attendee_events) == 4

        await Mutation().cancel_calendar_event(
            organizer_info, strawberry.ID(stored[1].id), "future",
        )
        await session.refresh(stored[0])
        for occurrence in stored[1:]:
            await session.refresh(occurrence)
        assert stored[0].status == "scheduled"
        assert {occurrence.status for occurrence in stored[1:]} == {"cancelled"}
    await engine.dispose()


def test_external_guests_are_stored_and_email_delivery_is_queued(monkeypatch) -> None:
    asyncio.run(exercise_external_guest_invitations(monkeypatch))


async def exercise_external_guest_invitations(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        entity = Entity(id="external-entity", name="Northwind")
        organizer = User(
            id="external-owner", entity_id=entity.id, email="owner@northwind.example",
            display_name="Owner", password_hash="test", role="admin",
        )
        member = User(
            id="external-member", entity_id=entity.id, email="member@northwind.example",
            display_name="Member", password_hash="test", role="basic",
        )
        session.add_all([entity, organizer, member])
        await session.commit()
        monkeypatch.setattr("backend.app.graphql_schema.communication_hub.publish", AsyncMock())
        notify = AsyncMock()
        monkeypatch.setattr("backend.app.graphql_schema.notify_background_job", notify)
        start = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
        info = SimpleNamespace(context=SimpleNamespace(
            session=session, user=organizer, settings=get_settings(),
        ))

        meeting = await Mutation().create_calendar_event(
            info,
            CalendarEventInput(
                title="Client review", event_type="meeting", starts_at=start,
                ends_at=start + timedelta(minutes=30), timezone="America/Chicago",
                meeting_url="https://meet.example.com/client-review",
                external_attendee_emails=["Client@Example.net"],
            ),
        )

        assert meeting.external_attendees[0].email == "client@example.net"
        assert meeting.external_attendees[0].delivery_status == "queued"
        attendee = await session.scalar(select(CalendarEventExternalAttendee))
        assert attendee.status == "active"
        job = await session.scalar(select(BackgroundJob))
        assert job.kind == "send_meeting_email"
        assert job.payload["recipient_email"] == "client@example.net"
        notify.assert_awaited_once_with(job.id)

        with pytest.raises(GraphQLError, match="selected from contacts"):
            await Mutation().create_calendar_event(
                info,
                CalendarEventInput(
                    title="Duplicate member", event_type="meeting", starts_at=start,
                    ends_at=start + timedelta(minutes=30),
                    external_attendee_emails=["member@northwind.example"],
                ),
            )
    await engine.dispose()


def test_personal_events_and_team_meetings_are_user_scoped(monkeypatch) -> None:
    asyncio.run(exercise_personal_events_and_team_meetings(monkeypatch))


async def exercise_personal_events_and_team_meetings(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        entity = Entity(id="entity-1", name="Northwind")
        organizer = User(
            id="user-1", entity_id=entity.id, email="owner@example.com",
            display_name="Owner", password_hash="test", role="admin",
        )
        attendee = User(
            id="user-2", entity_id=entity.id, email="member@example.com",
            display_name="Member", password_hash="test", role="basic",
        )
        outsider_entity = Entity(id="entity-2", name="Other")
        outsider = User(
            id="user-3", entity_id=outsider_entity.id, email="outside@example.com",
            display_name="Outside", password_hash="test", role="admin",
        )
        session.add_all([entity, organizer, attendee, outsider_entity, outsider])
        await session.commit()
        monkeypatch.setattr(
            "backend.app.graphql_schema.communication_hub.publish",
            AsyncMock(),
        )
        start = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
        organizer_info = SimpleNamespace(context=SimpleNamespace(session=session, user=organizer))

        personal = await Mutation().create_calendar_event(
            organizer_info,
            CalendarEventInput(
                title="Focus time", event_type="personal", starts_at=start,
                ends_at=start + timedelta(hours=1), timezone="America/Chicago",
            ),
        )
        meeting = await Mutation().create_calendar_event(
            organizer_info,
            CalendarEventInput(
                title="Design review", event_type="meeting", starts_at=start,
                ends_at=start + timedelta(hours=1), timezone="America/Chicago",
                attendee_ids=[strawberry.ID(attendee.id)],
            ),
        )

        organizer_events = await Query().calendar_events(
            organizer_info,
            start - timedelta(days=1),
            start + timedelta(days=2),
        )
        attendee_info = SimpleNamespace(context=SimpleNamespace(session=session, user=attendee))
        attendee_events = await Query().calendar_events(
            attendee_info,
            start - timedelta(days=1),
            start + timedelta(days=2),
        )

        assert {str(event.id) for event in organizer_events} == {str(personal.id), str(meeting.id)}
        assert [str(event.id) for event in attendee_events] == [str(meeting.id)]
        assert attendee_events[0].my_response == "pending"

        responded = await Mutation().respond_to_calendar_event(
            attendee_info, strawberry.ID(str(meeting.id)), "accepted"
        )
        assert responded.my_response == "accepted"
        membership = await session.scalar(
            select(CalendarEventAttendee).where(
                CalendarEventAttendee.event_id == str(meeting.id),
                CalendarEventAttendee.user_id == attendee.id,
            )
        )
        assert membership.response == "accepted"

        outsider_info = SimpleNamespace(context=SimpleNamespace(session=session, user=outsider))
        with pytest.raises(GraphQLError, match="not found"):
            await Query().calendar_event(outsider_info, strawberry.ID(str(meeting.id)))
    await engine.dispose()


def test_team_availability_is_private_ranked_and_tenant_scoped(monkeypatch) -> None:
    asyncio.run(exercise_team_availability(monkeypatch))


def test_calendar_reminders_are_personal_and_idempotent(monkeypatch) -> None:
    asyncio.run(exercise_calendar_reminders(monkeypatch))


async def exercise_calendar_reminders(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        entity = Entity(id="entity-reminders", name="Northwind")
        organizer = User(
            id="reminder-owner", entity_id=entity.id, email="owner@northwind.example",
            display_name="Owner", password_hash="test", role="admin",
        )
        attendee = User(
            id="reminder-member", entity_id=entity.id, email="member@northwind.example",
            display_name="Member", password_hash="test", role="basic",
        )
        session.add_all([entity, organizer, attendee])
        await session.commit()
        publish = AsyncMock()
        monkeypatch.setattr("backend.app.graphql_schema.communication_hub.publish", publish)
        starts_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        organizer_info = SimpleNamespace(context=SimpleNamespace(session=session, user=organizer))
        meeting = await Mutation().create_calendar_event(
            organizer_info,
            CalendarEventInput(
                title="Launch checkpoint", event_type="meeting", starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30), reminder_minutes=15,
                attendee_ids=[strawberry.ID(attendee.id)],
            ),
        )

        first = await Mutation().check_calendar_reminders(organizer_info)
        second = await Mutation().check_calendar_reminders(organizer_info)
        assert len(first) == 1
        assert first[0].kind == "calendar_reminder"
        assert str(first[0].calendar_event_id) == str(meeting.id)
        assert second == []

        attendee_info = SimpleNamespace(context=SimpleNamespace(session=session, user=attendee))
        disabled = await Mutation().set_calendar_event_reminder(
            attendee_info, strawberry.ID(str(meeting.id)), None,
        )
        assert disabled.reminder_minutes is None
        assert await Mutation().check_calendar_reminders(attendee_info) == []

        enabled = await Mutation().set_calendar_event_reminder(
            attendee_info, strawberry.ID(str(meeting.id)), 15,
        )
        assert enabled.reminder_minutes == 15
        attendee_due = await Mutation().check_calendar_reminders(attendee_info)
        assert len(attendee_due) == 1
        assert attendee_due[0].title == "Launch checkpoint starts in 15 minutes"
        reminder_rows = list(await session.scalars(
            select(Notification).where(Notification.kind == "calendar_reminder")
        ))
        assert {row.user_id for row in reminder_rows} == {organizer.id, attendee.id}
        assert publish.await_count >= 2
    await engine.dispose()


async def exercise_team_availability(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        entity = Entity(id="entity-availability", name="Northwind")
        organizer = User(
            id="availability-owner", entity_id=entity.id, email="owner@northwind.example",
            display_name="Owner", password_hash="test", role="admin",
        )
        attendee = User(
            id="availability-member", entity_id=entity.id, email="member@northwind.example",
            display_name="Member", password_hash="test", role="basic",
        )
        other_entity = Entity(id="entity-other", name="Other")
        outsider = User(
            id="availability-outsider", entity_id=other_entity.id, email="outside@example.com",
            display_name="Outsider", password_hash="test", role="basic",
        )
        session.add_all([entity, organizer, attendee, other_entity, outsider])
        await session.commit()
        monkeypatch.setattr("backend.app.graphql_schema.communication_hub.publish", AsyncMock())
        day_start = datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)  # 09:00 America/Chicago
        attendee_info = SimpleNamespace(context=SimpleNamespace(session=session, user=attendee))
        await Mutation().create_calendar_event(
            attendee_info,
            CalendarEventInput(
                title="Private interview preparation", event_type="personal",
                starts_at=day_start, ends_at=day_start + timedelta(hours=1),
                timezone="America/Chicago",
            ),
        )
        organizer_info = SimpleNamespace(context=SimpleNamespace(session=session, user=organizer))
        await Mutation().create_calendar_event(
            organizer_info,
            CalendarEventInput(
                title="Confidential review", event_type="personal",
                starts_at=day_start + timedelta(hours=1),
                ends_at=day_start + timedelta(hours=1, minutes=30),
                timezone="America/Chicago",
            ),
        )

        availability = await Query().calendar_availability(
            organizer_info,
            CalendarAvailabilityInput(
                user_ids=[strawberry.ID(organizer.id), strawberry.ID(attendee.id)],
                starts_after=day_start,
                starts_before=day_start + timedelta(hours=4),
                timezone="America/Chicago",
                duration_minutes=30,
                workday_starts_at="09:00",
                workday_ends_at="13:00",
            ),
        )

        assert {str(entry.user.id) for entry in availability.users} == {organizer.id, attendee.id}
        assert all(len(entry.busy) == 1 for entry in availability.users)
        assert availability.suggestions[0].starts_at == day_start + timedelta(hours=1, minutes=30)
        assert availability.suggestions[0].attendance_count == 2
        assert availability.suggestions[0].score == 100
        assert not hasattr(availability.users[0].busy[0], "title")

        with pytest.raises(GraphQLError, match="workspace"):
            await Query().calendar_availability(
                organizer_info,
                CalendarAvailabilityInput(
                    user_ids=[strawberry.ID(organizer.id), strawberry.ID(outsider.id)],
                    starts_after=day_start,
                    starts_before=day_start + timedelta(hours=4),
                ),
            )
    await engine.dispose()
