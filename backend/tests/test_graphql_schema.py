import pytest
import strawberry
from datetime import datetime, timezone
from graphql import GraphQLError

from backend.app.database import Project
from backend.app.graphql_schema import (
    CalendarEventInput,
    FlowNodeInput,
    FlowchartGraphInput,
    ProjectInput,
    decode_project_cursor,
    encode_project_cursor,
    normalized_channel_name,
    normalized_calendar_event,
    normalized_job_title,
    schema,
    validate_project_input,
)


def test_graphql_schema_exposes_typed_project_operations() -> None:
    schema_document = schema.as_str()

    assert "projects: [ProjectSummary!]!" in schema_document
    assert "project(id: ID!): Project!" in schema_document
    assert "createProject(input: ProjectInput!): Project!" in schema_document
    assert "updateProject(id: ID!, input: ProjectInput!, expectedRevision: Int!): Project!" in schema_document
    assert "deleteProject(id: ID!): Boolean!" in schema_document
    assert "nodes: [FlowNode!]!" in schema_document
    assert "edges: [FlowEdge!]!" in schema_document
    assert "nodeIds: [ID!]!" in schema_document
    assert "shape: String!" in schema_document
    assert "symbol: String" in schema_document
    assert "width: Float!" in schema_document
    assert "height: Float!" in schema_document
    assert "backupOwner: String" in schema_document
    assert "controlId: String" in schema_document
    assert "evidenceRequirement: String" in schema_document
    assert "riskLevel: String!" in schema_document
    assert "slaMinutes: Int" in schema_document
    assert "description: String!" in schema_document
    assert "profile: ProjectProfile!" in schema_document
    assert "status: String!" in schema_document
    assert "owner: ProjectMember" in schema_document
    assert "collaborators: [ProjectMember!]!" in schema_document
    assert "collaboratorIds: [ID!]!" in schema_document
    assert "deliverableCount: Int!" in schema_document
    assert "completedDeliverableCount: Int!" in schema_document
    assert "taskCount: Int!" in schema_document
    assert "completedTaskCount: Int!" in schema_document
    assert "planProgress: Int!" in schema_document
    assert "visibility: String!" in schema_document
    assert "approvalStatus: String!" in schema_document
    assert "currentUserAccess: String!" in schema_document
    assert "revisionNumber: Int!" in schema_document
    assert "documentRevision: Int!" in schema_document
    assert 'projectPage(search: String! = "", after: String = null, first: Int! = 24): ProjectPage!' in schema_document
    assert "nextCursor: String" in schema_document
    assert "totalCount: Int!" in schema_document
    assert "projectGovernance(projectId: ID!): ProjectGovernance!" in schema_document
    assert "updateProjectGovernance(" in schema_document
    assert "requestProjectApproval(" in schema_document
    assert "decideProjectApproval(" in schema_document
    assert "restoreProjectRevision(" in schema_document
    assert "workspace: Workspace!" in schema_document
    assert "workspaceMembers: [WorkspaceMember!]!" in schema_document
    assert "workspaceInvitations: [WorkspaceInvitation!]!" in schema_document
    assert "inviteWorkspaceMember(input: InviteMemberInput!): WorkspaceInvitation!" in schema_document
    assert "updateWorkspaceMemberRole(userId: ID!, role: String!): WorkspaceMember!" in schema_document
    assert "updateWorkspaceName" not in schema_document
    assert "communicationContacts: [CommunicationContact!]!" in schema_document
    assert "communicationChannels: [CommunicationChannel!]!" in schema_document
    assert "calendarEvents(startsAfter: DateTime!, startsBefore: DateTime!): [CalendarEvent!]!" in schema_document
    assert "calendarEvent(eventId: ID!): CalendarEvent!" in schema_document
    assert "reminderMinutes: Int" in schema_document
    assert "calendarAvailability(input: CalendarAvailabilityInput!): CalendarAvailability!" in schema_document
    assert "busy: [CalendarBusyBlock!]!" in schema_document
    assert "channelMessages(channelId: ID!, limit: Int! = 100): [ChannelMessage!]!" in schema_document
    assert "directMessages(contactId: ID!, limit: Int! = 100): [DirectMessage!]!" in schema_document
    assert "notifications(limit: Int! = 50): [Notification!]!" in schema_document
    assert "workItemId: ID" in schema_document
    assert "communicationChannelId: ID" in schema_document
    assert "communicationMessageId: ID" in schema_document
    assert "sendDirectMessage(recipientId: ID!, body: String!, parentId: ID = null, attachments: [MessageAttachmentInput!] = null): DirectMessage!" in schema_document
    assert "createCommunicationChannel(" in schema_document
    assert "createCalendarEvent(input: CalendarEventInput!): CalendarEvent!" in schema_document
    assert "updateCalendarEvent(eventId: ID!, input: CalendarEventInput!): CalendarEvent!" in schema_document
    assert "respondToCalendarEvent(eventId: ID!, response: String!): CalendarEvent!" in schema_document
    assert "setCalendarEventReminder(eventId: ID!, reminderMinutes: Int): CalendarEvent!" in schema_document
    assert "checkCalendarReminders: [Notification!]!" in schema_document
    assert 'cancelCalendarEvent(eventId: ID!, scope: String! = "event"): CalendarEvent!' in schema_document
    assert "recurrenceFrequency: String" in schema_document
    assert "recurrenceCount: Int" in schema_document
    assert "sendChannelMessage(channelId: ID!, body: String!, parentId: ID = null, attachments: [MessageAttachmentInput!] = null): ChannelMessage!" in schema_document
    assert "messageSearch(term: String!, limit: Int! = 50): [MessageSearchResult!]!" in schema_document
    assert "updateChatMessage(messageKind: String!, messageId: ID!, body: String!): Boolean!" in schema_document
    assert "toggleChatMessageReaction(messageKind: String!, messageId: ID!, emoji: String!): Boolean!" in schema_document
    assert "toggleChatMessagePin(messageKind: String!, messageId: ID!): Boolean!" in schema_document
    assert "toggleChatMessageBookmark(messageKind: String!, messageId: ID!): Boolean!" in schema_document
    assert "updateCommunicationChannelMembers(" in schema_document
    assert "markChannelRead(channelId: ID!): Boolean!" in schema_document
    assert "markDirectConversationRead(contactId: ID!): Boolean!" in schema_document
    assert "markNotificationRead(notificationId: ID!): Boolean!" in schema_document


def test_graphql_mutations_reuse_strict_graph_validation() -> None:
    payload = ProjectInput(
        title="Invalid graph",
        source_text="invalid",
        graph=FlowchartGraphInput(
            title="Invalid graph",
            nodes=[
                FlowNodeInput(
                    id=strawberry.ID("start"),
                    label="Start",
                    type="unsupported-node-type",
                    x=0,
                    y=0,
                )
            ],
            edges=[],
            questions=[],
            warnings=[],
        ),
    )

    with pytest.raises(GraphQLError, match="Invalid project graph"):
        validate_project_input(payload)


def test_project_metadata_is_normalized_with_graph_validation() -> None:
    payload = ProjectInput(
        title="Customer approvals",
        description="  Documents approval ownership.  ",
        status="DRAFT",
        owner_id=strawberry.ID("user-1"),
        collaborator_ids=[strawberry.ID("user-1"), strawberry.ID("user-2")],
        profile={
            "key": " ops  ", "priority": "HIGH", "health": "AT_RISK",
            "progress": 42, "tags": ["Controls", " controls ", "Launch"],
            "template": "compliance",
        },
        source_text="Start with a customer request.",
        graph=FlowchartGraphInput(
            title="Customer approvals",
            nodes=[
                FlowNodeInput(
                    id=strawberry.ID("start"),
                    label="Start",
                    type="start",
                    x=0,
                    y=0,
                )
            ],
            edges=[],
            questions=[],
            warnings=[],
        ),
    )

    validated = validate_project_input(payload)

    assert validated.description == "Documents approval ownership."
    assert validated.status == "draft"
    assert validated.owner_id == "user-1"
    assert validated.collaborator_ids == ["user-1", "user-2"]
    assert validated.profile.key == "OPS"
    assert validated.profile.priority == "high"
    assert validated.profile.health == "at_risk"
    assert validated.profile.progress == 42
    assert validated.profile.tags == ["Controls", "Launch"]
    assert validated.profile.template == "compliance"


def test_invitation_job_titles_are_normalized_and_bounded() -> None:
    assert normalized_job_title("  Operations Lead  ") == "Operations Lead"
    assert normalized_job_title("  ") is None

    with pytest.raises(GraphQLError, match="at most 120 characters"):
        normalized_job_title("x" * 121)


def test_communication_channel_names_are_normalized_and_bounded() -> None:
    assert normalized_channel_name("  Product   launch  ") == "Product launch"

    with pytest.raises(GraphQLError, match="between 2 and 80 characters"):
        normalized_channel_name("x")
    with pytest.raises(GraphQLError, match="between 2 and 80 characters"):
        normalized_channel_name("x" * 81)


def test_calendar_events_validate_schedule_type_and_meeting_link() -> None:
    start = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
    normalized = normalized_calendar_event(CalendarEventInput(
        title="  Weekly   planning  ",
        event_type="meeting",
        starts_at=start,
        ends_at=start.replace(hour=15),
        timezone="America/Chicago",
        meeting_url="https://meet.example.com/team",
        attendee_ids=[strawberry.ID("user-2")],
    ))

    assert normalized["title"] == "Weekly planning"
    assert normalized["attendee_ids"] == {"user-2"}
    assert normalized["reminder_minutes"] == 15
    assert normalized["recurrence_frequency"] == "none"

    with pytest.raises(GraphQLError, match="end after they start"):
        normalized_calendar_event(CalendarEventInput(
            title="Invalid", event_type="personal", starts_at=start, ends_at=start,
        ))
    with pytest.raises(GraphQLError, match="valid HTTP or HTTPS URL"):
        normalized_calendar_event(CalendarEventInput(
            title="Unsafe link", event_type="meeting", starts_at=start,
            ends_at=start.replace(hour=15), meeting_url="javascript:alert(1)",
        ))
    with pytest.raises(GraphQLError, match="Reminder must be off"):
        normalized_calendar_event(CalendarEventInput(
            title="Too early", event_type="personal", starts_at=start,
            ends_at=start.replace(hour=15), reminder_minutes=7,
        ))
    with pytest.raises(GraphQLError, match="must end after a number"):
        normalized_calendar_event(CalendarEventInput(
            title="Unbounded series", event_type="personal", starts_at=start,
            ends_at=start.replace(hour=15), recurrence_frequency="weekly",
        ))
    with pytest.raises(GraphQLError, match="between 2 and 100"):
        normalized_calendar_event(CalendarEventInput(
            title="Oversized series", event_type="personal", starts_at=start,
            ends_at=start.replace(hour=15), recurrence_frequency="daily",
            recurrence_count=101,
        ))


def test_project_cursor_round_trips_a_stable_timestamp_and_id() -> None:
    updated_at = datetime(2026, 8, 27, 15, 30, tzinfo=timezone.utc)
    project = Project(
        id="project-1",
        title="Scale test",
        source_text="",
        graph={"title": "Scale test", "nodes": [], "edges": []},
        updated_at=updated_at,
    )

    decoded_at, decoded_id = decode_project_cursor(encode_project_cursor(project))

    assert decoded_at == updated_at
    assert decoded_id == project.id


def test_project_cursor_rejects_malformed_client_input() -> None:
    with pytest.raises(GraphQLError, match="Project cursor is invalid") as error:
        decode_project_cursor("not-a-project-cursor")

    assert error.value.extensions["code"] == "BAD_USER_INPUT"
