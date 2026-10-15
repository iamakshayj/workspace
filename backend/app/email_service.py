import asyncio
import logging
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from html import escape

from .config import Settings


logger = logging.getLogger("flowforge.email")


@dataclass(frozen=True)
class InvitationEmail:
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class MeetingInvitationEmail:
    subject: str
    text: str
    html: str


def build_invitation_email(
    *,
    recipient_name: str,
    entity_name: str,
    inviter_name: str,
    role: str,
    setup_url: str,
    expires_at: datetime,
) -> InvitationEmail:
    role_label = "Admin" if role == "admin" else "Basic user"
    expiry = expires_at.strftime("%B %d, %Y")
    subject = f"Join {entity_name} on FlowForge"
    text = (
        f"Hi {recipient_name},\n\n"
        f"{inviter_name} invited you to {entity_name} on FlowForge as a {role_label}.\n"
        f"Set your password and activate your account by {expiry}:\n{setup_url}\n\n"
        "If you were not expecting this invitation, you can ignore this email."
    )
    safe_recipient_name = escape(recipient_name)
    safe_entity_name = escape(entity_name)
    safe_inviter_name = escape(inviter_name)
    safe_setup_url = escape(setup_url, quote=True)
    html = f"""<!doctype html>
<html><body style="font-family:Arial,sans-serif;color:#172033;line-height:1.5">
  <h2>Join {safe_entity_name} on FlowForge</h2>
  <p>Hi {safe_recipient_name},</p>
  <p>{safe_inviter_name} invited you as a <strong>{role_label}</strong>.</p>
  <p><a href="{safe_setup_url}" style="background:#5b4be7;color:white;padding:12px 18px;border-radius:8px;text-decoration:none">Set up your account</a></p>
  <p>This secure link expires on {expiry}. If you were not expecting this invitation, you can ignore this email.</p>
</body></html>"""
    return InvitationEmail(subject=subject, text=text, html=html)


def build_meeting_invitation_email(
    *,
    recipient_email: str,
    organizer_name: str,
    title: str,
    starts_at: str,
    ends_at: str,
    timezone_name: str,
    action: str,
    description: str = "",
    location: str = "",
    meeting_url: str = "",
    recurrence: str = "",
) -> MeetingInvitationEmail:
    action_label = {
        "invitation": "Meeting invitation",
        "updated": "Meeting updated",
        "cancelled": "Meeting cancelled",
    }.get(action, "Meeting invitation")
    subject = f"{action_label}: {title}"
    details = [f"When: {starts_at} to {ends_at} ({timezone_name})"]
    if recurrence:
        details.append(f"Repeats: {recurrence}")
    if location:
        details.append(f"Where: {location}")
    if meeting_url:
        details.append(f"Join: {meeting_url}")
    if description:
        details.append(f"Details: {description}")
    text = (
        f"Hi {recipient_email},\n\n"
        f"{organizer_name} has {action_label.lower()} for {title}.\n"
        + "\n".join(details)
        + "\n\nThis invitation does not grant access to the organizer's workspace."
    )
    safe_title = escape(title)
    safe_organizer = escape(organizer_name)
    safe_starts_at = escape(starts_at)
    safe_ends_at = escape(ends_at)
    safe_timezone = escape(timezone_name)
    safe_description = escape(description)
    safe_location = escape(location)
    safe_meeting_url = escape(meeting_url, quote=True)
    safe_recurrence = escape(recurrence)
    join_html = (
        f'<p><a href="{safe_meeting_url}" style="background:#5b4be7;color:white;padding:12px 18px;'
        'border-radius:8px;text-decoration:none">Join meeting</a></p>'
        if meeting_url else ""
    )
    html = f"""<!doctype html>
<html><body style="font-family:Arial,sans-serif;color:#172033;line-height:1.5">
  <p style="color:#6555df;font-weight:700">{action_label}</p>
  <h2>{safe_title}</h2>
  <p>Organized by {safe_organizer}</p>
  <p><strong>When:</strong> {safe_starts_at} to {safe_ends_at} ({safe_timezone})</p>
  {f'<p><strong>Repeats:</strong> {safe_recurrence}</p>' if recurrence else ''}
  {f'<p><strong>Where:</strong> {safe_location}</p>' if location else ''}
  {f'<p>{safe_description}</p>' if description else ''}
  {join_html}
  <p style="color:#667085;font-size:12px">This email invitation does not grant workspace access.</p>
</body></html>"""
    return MeetingInvitationEmail(subject=subject, text=text, html=html)


class EmailService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_invitation(
        self,
        *,
        recipient_email: str,
        recipient_name: str,
        entity_name: str,
        inviter_name: str,
        role: str,
        setup_url: str,
        expires_at: datetime,
    ) -> str:
        message = build_invitation_email(
            recipient_name=recipient_name,
            entity_name=entity_name,
            inviter_name=inviter_name,
            role=role,
            setup_url=setup_url,
            expires_at=expires_at,
        )
        if self.settings.email_delivery_mode.lower() != "smtp":
            logger.warning(
                "Invitation email captured by development delivery",
                extra={"event": "email.invitation.captured"},
            )
            return "logged"

        if not self.settings.smtp_host:
            raise RuntimeError("FLOWFORGE_SMTP_HOST is required when email delivery mode is smtp")
        await asyncio.to_thread(self._send_smtp, recipient_email, message)
        return "sent"

    async def send_meeting_invitation(self, **values: str) -> str:
        recipient_email = values["recipient_email"]
        message = build_meeting_invitation_email(**values)
        if self.settings.email_delivery_mode.lower() != "smtp":
            logger.warning(
                "Meeting invitation email captured by development delivery",
                extra={"event": "email.meeting.captured"},
            )
            return "logged"
        if not self.settings.smtp_host:
            raise RuntimeError("FLOWFORGE_SMTP_HOST is required when email delivery mode is smtp")
        await asyncio.to_thread(self._send_smtp, recipient_email, message)
        return "sent"

    def _send_smtp(self, recipient_email: str, invitation: InvitationEmail) -> None:
        message = EmailMessage()
        message["Subject"] = invitation.subject
        message["From"] = self.settings.smtp_from_email
        message["To"] = recipient_email
        message.set_content(invitation.text)
        message.add_alternative(invitation.html, subtype="html")

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as client:
            if self.settings.smtp_use_tls:
                client.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                client.login(self.settings.smtp_username, self.settings.smtp_password)
            client.send_message(message)
