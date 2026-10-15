import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .communications import communication_hub, serialize_notification
from .database import CalendarEvent, CalendarEventAttendee, Notification
from .identity import as_utc


REMINDER_MINUTES = {None, 0, 5, 10, 15, 30, 60, 120, 1440}


def reminder_title(event: CalendarEvent, minutes: int) -> str:
    if minutes == 0:
        return f"{event.title} starts now"
    if minutes == 60:
        return f"{event.title} starts in 1 hour"
    if minutes == 120:
        return f"{event.title} starts in 2 hours"
    if minutes == 1440:
        return f"{event.title} starts in 1 day"
    return f"{event.title} starts in {minutes} minutes"


def reminder_body(event: CalendarEvent) -> str:
    try:
        event_zone = ZoneInfo(event.timezone or "UTC")
    except ZoneInfoNotFoundError:
        event_zone = timezone.utc
    local_start = as_utc(event.starts_at).astimezone(event_zone)
    return (
        local_start.strftime("%A, %b %d · All day")
        if event.all_day
        else local_start.strftime("%A, %b %d · %I:%M %p %Z")
    )


async def dispatch_due_calendar_reminders(
    session: AsyncSession,
    *,
    user_id: str | None = None,
    publish: bool = False,
    now: datetime | None = None,
    limit: int = 2_000,
) -> list[Notification]:
    current_time = as_utc(now or datetime.now(timezone.utc))
    filters = [
        CalendarEventAttendee.reminder_minutes.is_not(None),
        CalendarEventAttendee.reminder_sent_at.is_(None),
        CalendarEventAttendee.response != "declined",
        CalendarEvent.status == "scheduled",
        CalendarEvent.starts_at >= current_time - timedelta(minutes=5),
        CalendarEvent.starts_at <= current_time + timedelta(days=1),
    ]
    if user_id:
        filters.append(CalendarEventAttendee.user_id == user_id)
    rows = (await session.execute(
        select(CalendarEventAttendee, CalendarEvent)
        .join(CalendarEvent, CalendarEvent.id == CalendarEventAttendee.event_id)
        .where(*filters)
        .order_by(CalendarEvent.starts_at, CalendarEventAttendee.user_id)
        .limit(max(1, min(limit, 10_000)))
        .with_for_update(skip_locked=True)
    )).all()
    notifications: list[Notification] = []
    for membership, event in rows:
        starts_at = as_utc(event.starts_at)
        if starts_at - timedelta(minutes=membership.reminder_minutes) > current_time:
            continue
        membership.reminder_sent_at = current_time
        notification = Notification(
            entity_id=event.entity_id,
            user_id=membership.user_id,
            actor_id=None,
            kind="calendar_reminder",
            title=reminder_title(event, membership.reminder_minutes),
            body=reminder_body(event),
            calendar_event_id=event.id,
        )
        session.add(notification)
        notifications.append(notification)
    if not notifications:
        return []
    await session.commit()
    for notification in notifications:
        await session.refresh(notification)
    if publish:
        await asyncio.gather(*(
            communication_hub.publish(notification.user_id, {
                "type": "notification",
                "notification": serialize_notification(notification, None),
            })
            for notification in notifications
        ))
    return notifications
