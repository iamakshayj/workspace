# Workspace user guide

Workspace is a collaborative work and process-management product. It combines agile planning with editable workflows, a live project sheet, ownership, controls, delivery evidence, process analytics, and governed exports.

## Contents

1. [Getting started](#getting-started)
2. [Home dashboard and workflows](#home-dashboard-and-workflows)
3. [Work management](#work-management)
4. [Creating a workflow](#creating-a-workflow)
5. [Editing the canvas](#editing-the-canvas)
6. [Documenting a step](#documenting-a-step)
7. [Project details and governance](#project-details-and-governance)
8. [Workflow collaboration, plans, tasks, and notes](#workflow-collaboration-plans-tasks-and-notes)
9. [Process intelligence](#process-intelligence)
10. [Exports and generated documents](#exports-and-generated-documents)
11. [Accounts, roles, and workspace administration](#accounts-roles-and-workspace-administration)
12. [Appearance and notifications](#appearance-and-notifications)
13. [Operations control plane](#operations-control-plane)
14. [Knowledge workspace](#knowledge-workspace)
15. [Troubleshooting](#troubleshooting)

## Getting started

Open Workspace at [http://127.0.0.1:3000](http://127.0.0.1:3000) for local development, or use the URL supplied by your organization.

1. Sign in with an account created by your workspace administrator.
2. The **Home** page is your personal operating dashboard for assigned work, today’s calendar, notifications, and flowchart health.
3. Select **Work** for daily execution, sprint planning, releases, roadmaps, and reports.
4. Select **Workflows** to browse or search the process maps you can access.
5. Administrators and editors can select **Create workflow** to begin a new one.

The persistent top navigation provides **Home**, **Work**, **Calendar**, **Workflows**, **Knowledge**, and **Operations** from authenticated pages, including the workflow editor. Guests do not see the workspace-wide Operations control plane. The current section is highlighted. On narrow screens, destinations remain visible in a dedicated scrollable row beneath the brand and page actions.

There is no public sign-up page. New users receive an invitation and set their password through its account-setup link.

## Home dashboard and workflows

Home is a focused high-level view of the workspace. It contains four detailed previews:

- Open stories and tasks assigned to you, with priority, status, and due dates
- Today’s meetings and personal calendar items
- Unread mentions, assignments, and team activity
- Recent flowcharts and portfolio delivery progress

Select any preview row or its contextual **View all** link to open the full Work, Calendar, notification, or flowchart context. Creation and planning controls stay on those dedicated pages so Home remains easy to scan. Dashboard sections degrade independently, so a temporarily unavailable service does not block the other workspace areas.

Select **Workflows** in the top navigation to open the dedicated process-map catalog.

- Use **Search workflows** to filter by title or description.
- Each card shows the owner, collaborators, diagram size, delivery progress, and last update.
- Select a card to open its editor.
- Select **Create workflow** to open a blank editor when your role permits it.
- Select **Workflows** from the top navigation to return to the catalog, or **Home** to return to your dashboard.

Inside a saved workflow, use the view control in the editor toolbar:

- **Diagram** focuses on the visual process map.
- **Sheet** provides a spreadsheet-style hierarchy of steps, deliverables, and tasks. Edit names, owners, status, priority, dates, and step links inline.
- **Split** keeps the diagram and project sheet visible together. Both views use the same real-time records, so a change in either view is immediately reflected everywhere else.

## Work management

Select **Work** in the main navigation or flowchart editor. Work is the daily operating surface; linking an item to a flowchart is optional.

### Create and manage work

Select **Create work** in the Work page toolbar and choose a configured work type. The starter set includes epics, stories, subtasks, tasks, defects, milestones, requests, deliverables, and approvals. Add the fields needed for planning:

- Summary, description, and acceptance criteria
- Priority, status, assignee, and reporter
- Story points and time estimate
- Start and due dates
- Labels, parent epic/story/task, sprint, and release
- Optional flowchart and flowchart-step context

Open a card to change its status, priority, assignee, sprint, release, estimate, or dates. The detail panel also contains comments, `@username` mentions, dependencies, and activity history. Assignees and mentioned contacts receive in-app notifications.

Select **Stories** to see hierarchical work such as Epic → Story → Subtask. Each row shows status, weighted progress, owner, QA child count, and its linked flowchart step. Use the child action to break down work; the new child automatically inherits its parent’s sprint, release, flowchart, and node context.

All fields that select workspace people use the same searchable picker. Open the field and search by name, email, username, role, or job title. Multi-person fields keep the picker open while you select several people; choose **Done** when finished. To keep large workspaces responsive, the picker shows at most 50 matching people at once and asks you to narrow broader results.

### Connect a flowchart node to delivery work

Select a node in a saved flowchart and open **Delivery planning** in the inspector.

- Create an epic, story, or task directly from the node, or link an existing work item as its primary delivery identity.
- An epic node can contain child stories, tasks, bugs, and their subtasks. Select **Add story** to build its scope without leaving the diagram.
- Choose a sprint when the node represents an iteration or needs sprint context.
- Choose a sub-flowchart when the node expands into a more detailed process map.
- The canvas badge shows the linked work key, delivery type, completion percentage, and sub-flowchart indicator.
- Select **View story hierarchy in Work** to open the Stories view already filtered to that flowchart node.
- From a linked Work item, select its flowchart context to return to the exact node.

Progress rolls up from the epic's child work and uses each workflow stage's progress weight, so testing and review are visible before final completion. A sprint-only node uses sprint progress. New child work inherits the node's sprint context. Newly added diagram nodes must be saved before delivery work can be linked.

### Board and backlog

- **Board** starts with Backlog, Ready, In progress, Ready for QA, In QA, Review / approval, Blocked, and Done. Drag a card between columns to update it.
- QA is explicit: sprint and report views distinguish items waiting for or undergoing testing from verified delivery.
- A column can have a work-in-progress (WIP) limit. The board shows the count against the limit and highlights overloaded stages.
- **Backlog** gives product and delivery leads a compact prioritized list. Administrators can pull work into a planned or active sprint from this view.
- Use search, **My work**, and the active-sprint quick view to reduce noise.

### Customize a workflow

Administrators can select **Customize** in the Work toolbar to configure the board for any team.

- Start with Product & software, General delivery, Marketing campaign, or Service operations.
- Rename and reorder stages; set their color, purpose, progress weight, and optional WIP limit.
- Categorize a stage as queue, active, QA, review, blocked, or done. These categories drive reporting and completion logic even when labels differ.
- Add, rename, and icon-label work types. Configure allowed parent types and the default child type to model the team’s own hierarchy.
- Stages and work types used by existing items cannot be removed until those items are moved or reclassified.

### Sprints

Administrators can create a sprint with a goal, date range, and point capacity. Only one sprint can be active at a time. Sprint cards compare item count, committed points, QA queue, weighted progress, and capacity; start and complete the sprint from the card.

### Roadmap and releases

Administrators can create releases with a business description, start date, and target date. Assign strategic epics, milestones, stories, or tasks to a release, then use **Roadmap** to track scope and completion. Releases move from planned to in progress to released.

### Reports

**Reports** shows completion, QA queue, work in progress, overdue work, delivered points, configurable status distribution, sprint velocity, team workload, and planning-health signals. Use these signals in daily stand-ups, sprint reviews, delivery reviews, and quarterly planning.

## Creating a workflow

### Generate from text

1. Create a workflow.
2. Select **AI** in the editor toolbar.
3. Describe the process in clear chronological language.
4. Select **Generate workflow** or press `Command/Ctrl + Enter`.
5. Review the generated nodes, branches, questions, and warnings.
6. Edit the result and select **Save project**.

Example prompt:

```text
A customer submits a refund request. Support checks whether the order is eligible.
If eligible, Finance approves the refund and the payment system issues it.
If it is not eligible, Support sends the rejection reason to the customer.
```

Text generation uses the configured self-hosted model server. It does not require an OpenAI API key. If the toolbar reports **AI unavailable**, use manual editing or ask the deployment administrator to start the model service.

### Build manually

1. Select **＋ Add**.
2. Choose an object from **Basics**, **BPMN**, or **Enterprise**.
3. Drag it into place.
4. Select it to edit its properties.
5. Drag from any of its four connection handles to another node.

Available objects include process steps, decisions, documents, free text, shapes, subprocesses, swimlanes, BPMN events and gateways, databases, servers, APIs, queues, users, and application systems.

## Editing the canvas

### Nodes

- Drag a node to reposition it.
- Select a node and use its resize handles, or enter an exact width and height in the inspector.
- Change its type, color, label, description, and layer in the inspector.
- Select **Duplicate step** to make an editable copy.
- Press `Delete` or use **Delete step** to remove it.

### Connections

- Connections can start and end on the top, right, bottom, or left side of a node.
- A side supports multiple connections.
- Select a connection to add a branch label such as `Approved` or `No`.
- Enable **Bidirectional** to show arrows at both ends.
- Delete a selected connection with `Delete` or **Delete connection**.

### Layers and layout tools

- Assign nodes to a named **Layer** in the inspector.
- Use the toolbar layer selector to display all layers or one layer.
- Hold `Command/Ctrl` while selecting nodes, or drag a selection area, to select multiple nodes.
- Use **Align left** or **Distribute** for a cleaner layout.
- Movement snaps to a grid for consistent spacing.
- Use swimlanes and subprocesses to communicate responsibility and process boundaries.

### Undo and clear

- Select **↶ Undo** or press `Command/Ctrl + Z` to reverse recent canvas changes.
- **Clear canvas** is available only to administrators.
- Clearing requires confirmation and can be undone immediately afterward.

## Documenting a step

Select a node to open its inspector. FlowForge can store the following operating information directly on the step:

### Ownership and dependencies

- Primary owner
- Backup owner
- System or application
- External vendor
- Description
- Layer and optional parent/container

### Controls and risk

- Control ID
- Policy reference
- Evidence requirement
- Segregation-of-duties rule
- Risk level: none, low, medium, high, or critical
- Data classification: public, internal, confidential, or restricted
- Whether the step is required

### Service management

- SLA in minutes
- Review date
- Attachments

Required steps, controls, and SLAs are used by process intelligence to identify skipped controls and late execution.

## Project details and governance

Select **Project details** in the editor toolbar to manage the flowchart as a governed project.

- **Description** explains the process purpose and scope.
- **Status** tracks draft, active, or archived work.
- **Owner** identifies the accountable person.
- **Collaborators** identify project participants.
- **Visibility** controls workspace-wide or restricted access.
- Project access roles include owner, editor, commenter, viewer, and approver.
- Revisions create immutable snapshots of saved process documents.
- Approval requests bind a decision to a specific revision.
- Revision restoration creates a new controlled revision without deleting history.
- Audit history records creation, saves, access changes, approvals, and restorations.

If another editor saves first, FlowForge preserves your local canvas and asks you to reload the latest revision instead of silently overwriting it.

## Workflow collaboration, plans, tasks, and notes

Saved flowcharts support live collaboration for users in the same workspace. Use **Delivery planning** on a node for durable agile work that must appear in boards, sprints, roadmaps, and reports. The collaboration panel remains useful for lightweight diagram notes and short-lived coordination.

- Active collaborators appear in the toolbar with profile avatars.
- Live cursors show where other collaborators are working.
- Canvas changes synchronize through the project collaboration room.

Select **Collaborate** to open the action-oriented collaboration panel:

### Plan

- Create deliverables with an owner, target date, status, description, and linked step.
- View calendar milestones and an agenda.
- Track completion using deliverable and task progress.

### Tasks

- Assign work to a workspace contact.
- Set priority, status, due date, details, linked deliverable, and linked diagram step.
- Assignees receive an in-app notification.

### Notes

- Add context to the entire flowchart or a specific node.
- Type `@username` to mention a contact.
- Mentioned users receive a notification.
- Resolve notes when the discussion or issue is complete.

Communication lives under **Messages** in the top-right header. Select **People** for a private one-to-one conversation or **Channels & groups** for shared communication. Use **+** to create either a workspace channel, available to every contact in the entity, or a private group with selected members. Group owners and workspace admins can manage membership from the conversation header. These conversations are intentionally separate from flowchart notes and tasks.

### Advanced messaging

- Select **Reply** on a message to preserve its thread context. Replies show the source message directly above the response.
- Select **React** to add or remove a quick reaction. Reactions, edits, deletions, pins, and replies update other open sessions in realtime.
- Authors can edit or soft-delete their own messages. A deletion preserves the thread timeline without exposing the previous body or attachment links.
- **Pin** highlights a message for everyone in that conversation. **Save** creates a bookmark visible only to your account. Use **Pinned** and **Saved** above the conversation to filter either collection.
- Search inside an open conversation, or select **Search messages** from the inbox to search every conversation you are permitted to access.
- In a channel or private group, type `@` and choose a teammate. A mention creates one actionable notification linked to that channel; ordinary messages remain only in Messages.
- Select **＋ Link** to attach up to five governed HTTP(S) references. Managed binary uploads and previews are a later file-management phase.
- Select **Create task** on a message to open the Work form with its content and source reference already populated.
- Direct messages show **Sent** and **Seen** state. Active conversations also show temporary typing presence.

## Personal calendar and meetings

Select **Calendar** from the workspace navigation to open your account-specific schedule.

- Select **＋ Schedule meeting** in the Calendar toolbar to choose attendees, find shared availability, or create a meeting manually. Select **Personal time** from the same window to create a private event.
- Switch between **Agenda**, **Daily**, **Weekly**, and **Monthly** views. The previous/next controls move by the selected period and **Today** returns to the current date.
- In the monthly or weekly view, select a date to open its closable day-agenda panel.
- A meeting can include one contact for a one-to-one or multiple contacts for a team meeting.
- Under **External guests**, enter an email address and select **Add guest**. External guests receive meeting invitations, updates, and cancellations by email without receiving workspace access.
- Add a web meeting link when inviting external guests so they have a way to join. Workspace-only in-app calls remain protected.
- Add a location, web meeting link, and agenda when useful.
- Choose a reminder from **At start time**, 5, 10, 15, or 30 minutes, 1 or 2 hours, 1 day, or **No reminder**. New events default to 15 minutes before.
- Use **Repeat** to create a daily, weekday, weekly, monthly, or custom repeating schedule. Choose either **After** a number of occurrences or **On** an end date, then review the repeat summary before saving.
- Invited contacts receive an actionable notification and can accept, respond tentatively, or decline.
- Use **Meetings** and **Private time** to filter the calendar without exposing private events to anyone else.
- Organizers can edit or cancel an event. Attendees receive realtime updates and cancellation notices.

### Recurring meetings

Recurring schedules work like an alarm: the repeat rule and the notification reminder are separate. **Repeat** decides which future calendar occurrences exist; **Reminder** decides when your personal notification appears for each occurrence.

1. Start a meeting or personal event and set its first date and time.
2. Under **Repeat**, choose every day, every weekday, every week, every month, or **Custom**. Custom schedules can repeat every 1–30 days, weekdays, weeks, or months.
3. End the series after 2–100 occurrences or on a date within one year. The form shows a plain-language summary before you save.
4. Open any occurrence to see its position in the series. Editing changes only that occurrence. When cancelling, choose **Only this meeting**, **This and future meetings**, or **Every meeting in the series**.

Calendar occurrences are stored in the event timezone so their local clock time remains stable across daylight-saving changes. A series sends one invitation notification instead of flooding attendees for every future occurrence; each occurrence still has its own RSVP, availability block, reminder, and call room.

### Schedule a group meeting

Select **＋ Schedule meeting** in the Calendar toolbar. Availability guidance and meeting creation are combined in one organized flow.

1. Search for individual workspace contacts, or use **Add everyone** for a large group. The organizer remains selected and a single check supports up to 100 people.
2. Choose the starting date, search range, meeting duration, working-hour window, and whether weekends are allowed.
3. Select **Suggest open times**. The calendar comparison shows each participant as open or busy in 30-minute cells. It never reveals event titles, descriptions, locations, event types, or other attendee names.
4. Review the suggested times. Slots where everyone is available appear first; when no exact opening exists, the assistant separates and ranks the closest alternatives by the number of people who can attend and identifies the contacts with conflicts.
5. Optionally select **Copy options** to share the top five choices, or select **Schedule this time** to transfer the time and guest list into the standard meeting form. Add the title, location, meeting link, and agenda before sending invitations.

Select **Set a time manually** when you already know the time, or **Personal time** for a private calendar block. Both choices reuse the same scheduling entry point without exposing availability details.

Declined and cancelled events do not block availability. Pending, tentative, accepted, personal, and all-day events are treated as busy to avoid accidental double-booking.

### Calendar reminders

Reminders are personal: each workspace attendee can open an event and change **Event reminder** without changing anyone else’s preference. When the reminder is due, it appears once in the notification bell and links directly to the event. It does not create a duplicate chat alert. Declined and cancelled events do not send reminders.

The background worker checks reminders every 30 seconds, including when nobody has the app open. An open browser also checks immediately and once per minute, so a stored reminder appears promptly after reconnecting. The server marks each reminder as delivered before broadcasting it, so multiple tabs do not create duplicate alerts. Changing an event’s start time or your reminder preference safely schedules a new alert.

The Calendar page is separate from flowchart delivery calendars: it coordinates people and meetings, while a flowchart’s **Plan** calendar tracks deliverable and task dates.

### Audio and video calls

- Open a direct message, group, or channel and select the phone or camera button to start a call.
- Open a scheduled meeting and select **Join video call** to use the in-app meeting room.
- Recipients see one incoming-call card with accept and decline controls. Accepting opens the same room.
- The lobby lets each participant choose video or audio-only before joining. The browser does not request camera or microphone access until **Join now** is selected.
- When the browser exposes multiple devices, choose a microphone and camera in the lobby before joining.
- Calls open as a non-modal mini window in the bottom-right corner, so Work, Calendar, Flowcharts, and the current page remain accessible.
- Use **Collapse** to reduce the call to a compact live bar, **Restore** to reopen the mini window, or **Expand** for the full participant view.
- During a call, participants can mute the microphone, turn the camera off, share or stop sharing their screen, see who is connected, or leave from either the mini or expanded view.
- An optional external meeting link can remain on a calendar event alongside the in-app room.

Call signaling uses the authenticated workspace WebSocket. Audio and video use browser WebRTC and are sent directly between participants. For production calls across corporate networks or NAT, configure `REACT_APP_WEBRTC_ICE_SERVERS` with a self-hosted coturn deployment or another TURN service. Peer-to-peer rooms are best for small teams; larger all-hands calls should use an SFU media service while retaining the same panel and authorization contract.

## Process intelligence

Select **Observe** in a saved flowchart to compare the designed process with execution evidence.

### Import an event log

1. Open **Observe → Import**.
2. Select **Choose CSV** or download the sample file.
3. Review the detected activities.
4. Map each activity to a diagram step. Exact activity/step names are mapped automatically.
5. Leave irrelevant activities unmapped if necessary.
6. Select **Import and analyze**.

The CSV requires these columns:

| Column | Required | Description |
| --- | --- | --- |
| `case_id` | Yes | Identifier shared by every event in one process instance |
| `activity` | Yes | Name of the executed activity |
| `timestamp` | Yes | ISO date/time or another browser-readable date/time |
| `status` | No | Result such as completed, failed, rejected, or cancelled |
| `owner` | No | Person or team that executed the event |
| `cost` | No | Non-negative numeric execution cost |

Example:

```csv
case_id,activity,timestamp,status,owner,cost
CASE-001,Request received,2026-08-29T14:00:00Z,completed,Operations,2.50
CASE-001,Manager approval,2026-08-29T15:10:00Z,completed,Finance,7.00
CASE-002,Request received,2026-08-29T16:00:00Z,completed,Operations,2.50
CASE-002,Payment issued,2026-08-29T18:30:00Z,failed,Finance,4.00
```

### Read the results

The overview shows:

- Imported cases and events
- Percentage of observed transitions that conform to the diagram
- Average case cycle time
- Per-node execution volume and average wait
- Failure and SLA-breach counts
- Total recorded cost
- Branch volume as thicker labeled connections

Drift alerts identify:

- Unexpected transitions
- Required or controlled steps that were skipped
- Activities that were not mapped
- Failed executions
- SLA breaches

Select **Show step** to locate the related node. Editors can select **Resolve** after investigating an alert. The import and resolution are retained in audit and evidence records.

### Search process impact

Open **Observe → Impact** and search for a system, vendor, control, policy, owner, or data classification. Results show every accessible flowchart step that depends on the matching value.

Use impact search before changing a shared system, vendor, policy, control, or team responsibility.

## Exports and generated documents

Select **Export** in a saved flowchart.

- **PNG image** captures the current canvas.
- **SVG diagram** creates a scalable server-rendered diagram.
- **JSON backup** exports portable project and graph data.
- **Evidence package** creates a ZIP containing the graph, revisions, approvals, access, audit events, plan records, process imports, insights, and clean attachment metadata.
- **Operating documents** creates a ZIP containing:
  - `SOP.md`
  - `RACI.csv`
  - `execution-checklist.md`
  - `training-guide.md`
  - `controls.csv`
  - `test-cases.md`
  - `executive-summary.md`
  - `source-flowchart.json`
  - `manifest.json`

The manifest records the source project revision and SHA-256 checksums. Treat an operating-document package as stale after the flowchart document revision changes.

Evidence and operating-document packages require project-management access.

## Accounts, roles, and workspace administration

### Basic users

- View accessible flowcharts and live updates.
- Participate when granted commenter or approver access.
- Create work items and update items they reported or are assigned to.
- Comment on workspace work and receive assignments and mentions.
- Cannot create or edit flowcharts solely through the basic workspace role.

### Administrators

- Create and edit flowcharts.
- Clear canvases after confirmation.
- Invite contacts and choose an admin or basic role.
- Manage project access and governed packages.
- Manage all work items, sprint lifecycle and capacity, and releases.

Workspace administrators can add contacts from **Settings → Entity & contacts**. The contact receives an account-setup email, follows the expiring link, and sets a password before becoming active.

Entities themselves are created or edited only through the protected internal API by the platform owner; there is no entity-management UI.

## Appearance and notifications

Open the account menu in the top-right corner.

- **Profile** changes the signed-in user's display name and email.
- **Settings** controls light, dark, or system-default appearance.
- **Notifications** contains mentions, task assignments, and other actionable activity.
- **Messages** contains one-to-one conversations, workspace channels, private groups, and their combined unread badge.
- **Calendar** contains the signed-in user's private events and meetings where they are an organizer or attendee.

Conversation messages appear only in the Messages widget rather than being duplicated in the notification center.
Meeting invitations, updates, cancellations, and attendee responses appear in Notifications because they require action.

## Troubleshooting

### AI unavailable

The FlowForge API is working, but it cannot reach the self-hosted model endpoint.

- Manual diagram editing, collaboration, analytics, governance, and exports continue to work.
- For local development, start the configured llama.cpp or vLLM service on port `8001`.
- Confirm [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) reports `model_server_reachable: true`.

### Service unavailable

Start the FastAPI service on port `8000`, then refresh the browser.

### Observe is disabled

Save the flowchart first. Event imports and analytics belong to a persisted project.

### CSV import fails

- Confirm the file has `case_id`, `activity`, and `timestamp` headers.
- Confirm every row has a valid timestamp.
- Confirm cost values are numeric and non-negative.
- Imports are limited to 10,000 events per request.

### Save conflict

Another editor saved a newer document revision. Review your local canvas, select **Reload latest**, and reapply any necessary changes. FlowForge does not overwrite the local canvas automatically.

### Export does not start

- Save the project before using server exports.
- Allow downloads from the FlowForge site.
- Evidence and operating-document packages require management access.
- Retry after confirming the worker and storage checks are healthy.

### Attachment cannot be downloaded

The file may still be uploading or awaiting a malware scan. Only completed, clean attachments can be downloaded.

## Operations control plane

Open **Operations** to manage the connected system around project delivery. Choose a project scope at the top when you want project-specific results.

- **Projects** combines status, progress, risks, decisions, linked documents and meetings, reusable group access, and project workflow/field/notification/integration/automation rules.
- **Organization** models departments, business units, teams, reporting lines, member allocation, skills, capacity, job titles, profiles, and timezones.
- **Dependencies** visualizes cross-project blockers, reports circular links, estimates schedule impact, and identifies critical work paths.
- **Memory & audit** searches the cross-object history. Administrators can verify the tamper-evident chain, export events, and set retention or legal hold.
- **Meetings** stores agenda, notes, action items, transcript, and recording references. Mark transcript lines with `Action:`, `Decision:`, or `Risk:` to extract follow-ups without a hosted AI provider.
- **Dashboards** saves selected operational widgets, shared/private scope, layout, and delivery metadata. **Reports** groups projects, work, or risks by governed dimensions.
- **Files** organizes folders and external or stored-file references with tags, classification, sharing, versions, preview links, and searchable content text.
- **Approvals** defines reusable sequential or parallel stages, requests approval for supported object types, delegates decisions, and sends reminder/escalation notifications.
- **Notifications** controls in-app, email, push, digest, and mute preferences by activity type. Provider-backed email and push delivery must be configured by an operator.

## Knowledge workspace

Open **Knowledge** from the top navigation. Workspace admins create spaces and can choose workspace-wide or restricted visibility. Editors can then create a blank page or start from a project brief, SOP, meeting notes, decision record, or policy template.

- Use **Edit** to write Markdown, set the owner and classification, publish/archive the page, and schedule review or expiry.
- Link another page with `[[doc:document-id]]`; the **Backlinks** tab shows both incoming and outgoing relationships.
- Use **Comments** for review. Enter a member's displayed `@handle` to notify them; the notification opens the referenced document directly.
- Owners and admins use **Access** to grant viewer, commenter, or editor permission. Restricted pages are not returned by list, search, or detail endpoints to unauthorized users.
- **History** preserves every save. Restoring a version creates a new version rather than erasing the audit trail.

If a save reports a conflict, another editor saved first. Copy any unsaved text, reopen the page, compare the latest version, and apply the intended change. Current collaboration is conflict-safe versioned editing; character-by-character simultaneous coauthoring requires a future CRDT editing service.

## Data residency administration

Residency is managed only through the internal entity API. Provision an entity with `data_region` matching the deployment's `FLOWFORGE_DEPLOYMENT_REGION`; optionally set `data_residency_locked` to `true`. A locked entity cannot be moved or unlocked through the application. The infrastructure deployment must keep databases, object storage, queues, inference, logs, backups, and replicas in that same geography.

## Related technical documentation

- [Main README](../README.md)
- [Product implementation plan](PRODUCT_IMPLEMENTATION_PLAN.md)
- [Recovery runbook](RECOVERY_RUNBOOK.md)
