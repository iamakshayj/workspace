from datetime import datetime, timezone

from backend.app.email_service import build_invitation_email, build_meeting_invitation_email


def test_invitation_email_contains_entity_role_and_setup_instructions() -> None:
    message = build_invitation_email(
        recipient_name="Taylor Morgan",
        entity_name="Northwind Operations",
        inviter_name="Avery Admin",
        role="basic",
        setup_url="http://127.0.0.1:3000/accept-invite?token=secure-token",
        expires_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )

    assert message.subject == "Join Northwind Operations on FlowForge"
    assert "Avery Admin" in message.text
    assert "Basic user" in message.text
    assert "secure-token" in message.text
    assert "Set up your account" in message.html


def test_external_meeting_email_contains_joining_details_and_no_workspace_access() -> None:
    message = build_meeting_invitation_email(
        recipient_email="client@example.net",
        organizer_name="Avery Admin",
        title="Client review",
        starts_at="2026-09-03T15:00:00+00:00",
        ends_at="2026-09-03T15:30:00+00:00",
        timezone_name="America/Chicago",
        action="invitation",
        description="Review the launch plan.",
        location="Online",
        meeting_url="https://meet.example.com/client-review",
    )

    assert message.subject == "Meeting invitation: Client review"
    assert "https://meet.example.com/client-review" in message.text
    assert "does not grant access" in message.text
    assert "Join meeting" in message.html
