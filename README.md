# Workspace

Workspace combines editable visual workflows with a live spreadsheet-style project tracker, agile planning, calendars, and team collaboration.

For an end-user walkthrough, see the [Workspace user guide](docs/USER_GUIDE.md).
For local role-based demonstrations, see the [enterprise demo playground](docs/DEMO_PLAYGROUND.md).
For the cross-object relationship and search architecture, see [Enterprise Work Graph and Search](docs/ENTERPRISE_WORK_GRAPH_SEARCH.md).
For policy, DLP, residency, legal holds, and access controls, see [Security and governance](docs/SECURITY_GOVERNANCE.md).
For service tokens, public APIs, connectors, and signed webhooks, see [Integration platform](docs/INTEGRATION_PLATFORM.md).
For staging, scale, recovery, and certification boundaries, see [Production validation gates](docs/PRODUCTION_VALIDATION.md).

## Architecture

- **React + React Flow** renders and edits graph data.
- **FastAPI** owns authentication, authorization, inference, validation, layout, health checks, and project APIs.
- **FastAPI WebSockets** provide project-scoped deliverables, tasks, notes, presence, and live document updates plus user-scoped direct, channel, group, and notification delivery.
- **WebRTC** provides in-app audio/video media while authenticated WebSockets authorize rooms and relay call signaling.
- **Redis** fans WebSocket events across API replicas and stores expiring distributed presence.
- **Durable workers** claim database-backed jobs, using Redis only as a low-latency wake-up channel.
- **S3-compatible object storage** holds attachment and generated artifact bytes outside PostgreSQL; ClamAV scans attachment quarantine objects before promotion.
- **Strawberry GraphQL** provides the typed project, node, edge, query, and mutation contract at `/graphql`.
- **vLLM** serves an open-weight instruction model over an internal HTTP endpoint.
- **Pydantic JSON Schema** constrains the model to a versioned graph contract.
- **PostgreSQL** stores projects in the container stack; local development defaults to SQLite.

The browser never talks directly to the model server:

```text
React :3000 -> FastAPI :8000 -> vLLM :8001
                 GraphQL -> PostgreSQL JSONB
             WebSockets -> Redis pub/sub + presence
          generation jobs -> worker -> self-hosted model
         attachments/artifacts -> private S3/MinIO objects
                 attachments -> quarantine -> ClamAV -> clean objects
```

Authentication is application-managed: FastAPI stores Argon2 password hashes, supports TOTP MFA with one-time recovery codes, persists revocable browser sessions behind signed HTTP-only cookies, and enforces entity and project-level access on the server. Workspace administrators can require MFA for admins or all members and set maximum session and idle lifetimes; non-compliant sessions are restricted to an audited enrollment or step-up flow.

## What is implemented

- Text-to-flowchart generation through a self-hosted model
- Strict node and edge schema with closed node types
- Invalid-edge removal, disconnected-node checks, and decision-branch warnings
- Model-response repair followed by strict schema validation
- Deterministic layered layout
- Clarification questions returned by the model
- Editable React Flow canvas with undo, drag handles, and precise width/height controls
- Free text, shapes, swimlanes, subprocesses, BPMN events/tasks/gateways/data objects, and enterprise system symbols
- Diagram layers, grid snapping, multi-selection, left alignment, vertical distribution, and step duplication
- Four-sided, multi-connection node handles and optional bidirectional arrows
- Node-specific attachments with presigned transfer, authenticated download, project-editor management, scanning state, and a 10 MB file limit
- Service readiness indicator
- SQLite/PostgreSQL project persistence APIs
- Project descriptions, lifecycle status, accountable owners, and normalized collaborator membership
- Searchable single- and multi-person selectors across ownership, collaboration, meetings, messaging groups, and assigned work; large result sets are capped until a query narrows them
- Admin-provisioned email/password accounts with Argon2 password hashing
- Entity-owned projects with workspace or restricted visibility
- Project owner, editor, commenter, viewer, and approver access roles
- Immutable numbered revisions, revision restoration, and approval decisions bound to a revision
- Project audit events for creation, saves, access changes, approvals, and restorations
- Alembic-only production startup with a fresh-database baseline, governance migrations, and startup revision verification
- Searchable, cursor-paginated project catalog with tenant-scoped PostgreSQL indexes
- Revision-aware GraphQL, REST, and live-collaboration saves that preserve local work on stale-write conflicts
- Platform-owner-only entity creation and editing through a protected internal API
- Entity-admin contact invitations and role changes
- Expiring invitation links, pending contacts, password setup, and SMTP email delivery
- Durable invitation-email delivery with encrypted-at-rest setup tokens, retries, and terminal payload redaction
- Real-time same-entity collaboration with active-user avatars and live cursors
- Cross-instance WebSocket fan-out and TTL-backed distributed presence through Redis
- Durable, retryable model-generation jobs with stale-worker lease recovery
- S3-compatible attachment storage with short-lived upload/download grants and quarantine-to-clean promotion
- ClamAV worker integration that blocks infected or unscanned files from download
- Per-entity user, project, storage, monthly-generation, and pending-generation quotas
- Redis-coordinated request throttling with standard limit and retry response headers
- Request IDs, W3C trace correlation, production JSON logs, and Prometheus metrics
- Automatic stale-upload cleanup plus private job payload/result and history retention
- Queued SVG/JSON exports, manager-only evidence ZIPs, and generated operating-document packages
- CSV process-event ingestion with versioned activity-to-node mappings
- Node and branch overlays for volume, wait time, SLA misses, failures, cost, and conformance
- Persisted drift alerts for unexpected paths, skipped controls, unmapped activities, failures, and SLA breaches
- Step-level owners, backups, systems, vendors, controls, policies, evidence, segregation rules, risk, data class, SLA, and review dates
- Entity-wide impact search across process dependencies
- First-class Work hub for board, issue navigator, story hierarchy, ranked backlog, sprint, release, roadmap, dependency, and delivery-report views
- Deterministic, permission-filtered work intelligence for daily priorities, project health, blockers, meeting follow-up, and stale knowledge, with evidence, freshness, confidence, and review-only actions
- Governed work-graph change proposals with preview fingerprints, independent approval, idempotent application, drift protection, reversible snapshots, notifications, and audit history
- Entity-level customizable workflows with reusable cross-functional presets, configurable stages/colors/progress weights/WIP limits, and custom work-type hierarchies
- QA-aware sprint progress, testing queues, WIP warnings, story rollups, flowchart-node delivery metrics, and reporting
- Tenant-scoped epics, stories, tasks, bugs, milestones, assignments, estimates, labels, dates, and optimistic revisions
- Admin-managed sprint goals, capacity, lifecycle controls, releases, targets, and velocity reporting
- Work-item comments with mentions, dependency links, immutable activity history, and optional flowchart/node context
- Node delivery bindings for a primary epic/story/task, sprint context, and nested sub-flowcharts, with live progress badges and context-preserving navigation
- Epic → story → subtask breakdowns with inherited flowchart-node context, hierarchy rollups, and flowchart-scoped planning views
- Generated SOP, RACI, checklist, training guide, controls register, test cases, and executive summary with source-revision checksums
- Authenticated, expiring artifact downloads, artifact quota accounting, and object cleanup on expiry or project deletion
- Persisted per-flowchart tasks and notes with reconnecting document synchronization
- Per-flowchart delivery plans with owned deliverables, target dates, status, and calendar/agenda views
- A focused Home dashboard with four detailed previews for assigned work, today’s schedule, notifications, and flowchart health
- A persistent responsive top navigation across Home, Work, Calendar, Workflows, Knowledge, and the workflow editor
- An Operations control plane for project risks/decisions/settings, organization hierarchy and capacity, cross-project dependencies, organizational history, meeting records, dashboards/reports, approvals, file references, notification preferences, and audit verification
- A tenant-scoped typed work graph with dangling-reference rejection, circular-dependency prevention, reusable team grants, project access requests, and guest-safe read boundaries
- Tamper-evident audit chaining with request correlation, admin filtering/export, retention controls, and legal-hold configuration
- Saved board views and swimlanes, formatted threaded work comments and reactions, custom fields/types, split/merge operations, release baselines/scenarios, and release-burnup reporting
- Smart issue queries across status, type, priority, people, sprint, release, project, label, component, team, and delivery signals, with reusable saved filters
- Permission-aware bulk triage for status, assignee, priority, sprint, and release, automatically batched for large selections
- Scalable backlog ranking, sprint capacity planning, release-readiness gates, generated release notes, cross-project blocker paths, schedule-risk signals, and circular-dependency detection
- A dedicated searchable Workflows library with progress rollups from linked tasks and deliverables
- A governed Knowledge workspace with spaces, templates, versioned Markdown documents, search, comments and mentions, backlinks, review/expiry dates, classifications, and document-level roles
- Diagram, Sheet, and Split views backed by the same real-time tasks and deliverables, with inline owners, statuses, priorities, dates, and workflow-step links
- Private same-entity direct messages with searchable contacts and unread badges
- Workspace channels and member-selected private groups with realtime messages, per-user read state, and admin/owner member management
- Rich direct and channel conversations with threads, reactions, mentions, formatting, code blocks, polls, link/media previews, pins, personal saves, permission-filtered search, conversation export, and conversion into tasks, requests, decisions, risks, or meetings
- Personalized daily, weekly, and monthly calendars with private focus blocks, one-to-one and team meetings, workspace attendees, external email guests, RSVP responses, locations, meeting links, and realtime invitation updates
- A unified, privacy-safe meeting scheduler for up to 100 workspace members, with searchable participant selection, merged free/busy timelines, working-hour and duration constraints, everyone-open suggestions, ranked alternatives, manual scheduling, and personal-time creation
- Per-attendee calendar reminders with configurable timing, idempotent delivery through the notification bell, event deep links, and automatic reset when schedules change
- Alarm-style recurring schedules for daily, weekday, weekly, monthly, and custom intervals, bounded by an end date or occurrence count, with timezone/DST-safe occurrences and one/future/series cancellation controls
- In-app WebRTC audio/video rooms for direct messages, channels, groups, and scheduled meetings, with a non-modal mini/collapsed/expanded call window, permission-safe lobby, incoming-call controls, participant roster, mute, camera, and configurable STUN/TURN
- Integrated call collaboration with in-call chat, notes, live browser captions, downloadable consent-gated local recordings, reactions, raised hands, screen sharing, host controls, breakout assignments, peer-quality telemetry, and durable scheduled-meeting notes/transcripts
- Node-linked flowchart notes with `@username` suggestions, mentions, and resolution state
- Assigned tasks with priorities, due dates, statuses, deliverable links, flowchart-step links, and live assignee notifications
- Persisted notification center with live message, mention, and assignment delivery
- Admin co-editing with live, view-only updates for basic users
- HTTP-only managed sessions, device revocation, TOTP MFA, and authenticated API routes
- Typed GraphQL queries and mutations for flowchart project CRUD
- PNG, SVG, JSON, and evidence-package export plus browser autosave
- Docker configuration for frontend, API, worker, PostgreSQL, Redis, MinIO, ClamAV, and optional NVIDIA vLLM service

## Local development

### 1. Start a compatible model server

The backend speaks directly to a vLLM-compatible HTTP endpoint. For an NVIDIA host:

```bash
docker compose --profile gpu up model
```

The container default is `Qwen/Qwen3-4B`. Set `MODEL_NAME` to another instruction-tuned model that works with vLLM structured outputs.

For Apple Silicon, this workspace is configured for the 2.5 GB `ggml-org/Qwen3-4B-GGUF:Q4_K_M` model with llama.cpp:

```bash
./scripts/install-local-model.sh  # first setup only
./scripts/start-local-model.sh
```

The backend defaults to the server's `qwen3-4b-local` alias.

The Apple Silicon configuration uses llama.cpp's lightweight JSON-object mode followed by strict Pydantic validation. The vLLM container uses full schema-constrained output through `FLOWFORGE_MODEL_RESPONSE_FORMAT=json_schema`.

Local development starts an embedded background worker inside FastAPI and stores attachment objects under `.flowforge-storage/`. The relational database contains only attachment metadata. Production disables the embedded worker and runs the dedicated `worker` service.

### 2. Start the backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
# Replace FLOWFORGE_AUTH_SECRET with: openssl rand -hex 32
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

### 3. Start React

```bash
cp .env.example .env
npm install
npm start
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000).

## Production container deployment

Production mode intentionally refuses placeholder secrets, insecure cookies, SQLite, non-HTTPS public URLs, or console-only invitation delivery. Copy the production environment template, replace every placeholder, and keep the resulting file out of version control:

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production config
```

Run the application behind an HTTPS load balancer or reverse proxy. The bundled frontend proxies API, GraphQL, health, and WebSocket traffic over the same public origin, so the API and model containers do not need public ports.

With an external compatible model endpoint, set `FLOWFORGE_MODEL_BASE_URL` in `.env.production` and start:

```bash
docker compose --env-file .env.production up -d --build frontend api worker postgres redis minio clamav
```

The API waits for the one-shot `migrate` service to run `alembic upgrade head`, then verifies the database is at the exact application revision before accepting traffic. Production startup never calls `create_all` or performs ad-hoc schema changes. To run the migration step separately during a controlled deployment:

```bash
docker compose --env-file .env.production run --rm migrate
```

After deploying revision `20260829_06`, move any pre-existing database-backed attachment bytes into object storage before enforcing database-size policies:

```bash
docker compose --env-file .env.production run --rm worker python -m backend.app.migrate_attachments
```

Keep the bucket private. Route `FLOWFORGE_STORAGE_PUBLIC_ENDPOINT_URL` through TLS to the S3 API, allow the FlowForge frontend origin to make `POST`, `GET`, and `HEAD` requests in bucket CORS, and expire abandoned `quarantine/` objects with a short lifecycle rule. ClamAV port 3310 and the MinIO console must remain on the private service network.

On an NVIDIA Docker host, use the included model service:

```bash
docker compose --env-file .env.production --profile gpu up -d --build
```

Use a managed secret store in the target environment instead of committing `.env.production`. Terminate TLS before the frontend, restrict the internal entity and metrics endpoints at the network layer, and configure database backups and monitoring before accepting production traffic. The backup and restore procedure is in [docs/RECOVERY_RUNBOOK.md](docs/RECOVERY_RUNBOOK.md).

### Data residency

Each regional deployment must set `FLOWFORGE_DEPLOYMENT_REGION` to one of the supported region identifiers. Entities are provisioned through the internal API with a matching `data_region`; requests are rejected if an entity reaches a deployment outside that region. Setting `data_residency_locked` to `true` is irreversible through the API. This creates an enforceable application boundary, but the infrastructure operator must also keep PostgreSQL, object storage, Redis, model inference, backups, logs, and disaster-recovery replicas inside the declared geography.

## Knowledge and documents

The **Knowledge** workspace provides a Confluence-style, tenant-scoped home for permission-filtered pages. It includes:

- Workspace and restricted spaces, hierarchical child-page trees, custom page icons, labels, favorites, recent pages, archived-page views, and reusable page templates.
- Markdown authoring with headings, links, mentions, tasks, tables, code blocks, information/warning/success panels, expandable sections, live preview, outlines, and local draft recovery.
- Page copy, move, archive/restore, Markdown export, print/PDF, page following, follower update notifications, comments, threaded replies, `@mentions`, and resolved conversations.
- Bidirectional backlinks through `[[doc:document-id]]`, permission-aware search, page/space access roles, owner and classification metadata, review and expiry dates, and space settings.
- Immutable revision history, side-by-side version comparison, and restore. Saves carry an expected revision; a stale editor receives a conflict instead of overwriting another person's work.

These capabilities cover the core content, navigation, collaboration, and governance workflows without depending on Atlassian services. Marketplace apps, Atlassian-specific import fidelity, full multiplayer WYSIWYG editing, and enterprise identity provisioning remain separate integrations rather than being presented as local feature parity.

The detailed delivered/platform/integration inventory is maintained in [docs/CONFLUENCE_FEATURES.md](docs/CONFLUENCE_FEATURES.md).

## API contract

`POST /api/v1/flowcharts/generation-jobs`

```json
{
  "text": "A customer submits a request. Support triages it..."
}
```

The browser uses `POST /api/v1/flowcharts/generation-jobs`, then polls `GET /api/v1/flowcharts/generation-jobs/{job_id}` until the durable worker succeeds or exhausts its retries. Job payloads are never returned by the status API. The former synchronous generation route has been removed so inference cannot bypass tenant quotas or queue recovery.

Saved projects expose durable artifact jobs through `POST /api/v1/projects/{project_id}/artifact-jobs`, followed by `GET /api/v1/projects/{project_id}/artifact-jobs/{job_id}`. SVG and JSON exports are available to project members; governance evidence and operating-document ZIPs require project-management access. Completed artifacts use authenticated, expiring downloads at `GET /api/v1/projects/{project_id}/artifacts/{artifact_id}/download`, live in private object storage, count toward the entity storage quota, and are removed after the configured retention period.

Process intelligence is available at `POST /api/v1/projects/{project_id}/process-events/imports` and `GET /api/v1/projects/{project_id}/process-analytics`. Each imported event identifies a case, activity, timestamp, and optional status, owner, and cost. Activity mappings are stored with the import so observed paths can be compared with the governed graph. Entity-wide dependency impact search is available at `GET /api/v1/process-impact?query=...`.

Entity admins can inspect current usage at `GET /api/v1/operations/usage`. Platform owners configure limits through the internal create/update entity payloads: `max_users`, `max_projects`, `max_storage_bytes`, `max_monthly_generations`, and `max_pending_generations`. Pending invitations and incomplete direct uploads reserve capacity until accepted, canceled, or expired/cleaned.

Prometheus-compatible process and queue metrics are exposed at `GET /metrics`. Production requests must include `X-FlowForge-Metrics-Key`. Every API response includes `X-Request-ID` and `Traceparent`; rate-controlled responses also include `RateLimit-Limit`, `RateLimit-Remaining`, and `RateLimit-Reset`.

The result contains positioned nodes, validated edges, clarification questions, and graph warnings. Project reads and writes use authenticated GraphQL queries and mutations at `/graphql`; the development server exposes GraphiQL at the same URL. Home loads a small recent-project pulse while the Flowcharts library uses the tenant-scoped `projectPage` query for indexed title/description search and stable cursor pagination. Project mutations include the last `documentRevision`; stale saves return a `CONFLICT` without overwriting either version.

The original REST project routes remain available for compatibility. `PUT /api/v1/projects/{project_id}` requires the last returned document revision in an `If-Match` header, returns `428` when the precondition is absent, and returns `409` when it is stale.

Diagram objects persist their `shape`, optional `symbol`, `width`, and `height` in the versioned graph document, with defaults that keep older saved flowcharts compatible. `project_attachments` stores only filename, object key, ownership, size, upload state, and scan state. The browser requests a short-lived upload grant, transfers bytes directly to S3-compatible quarantine storage, and completes the upload through the API. Production workers scan the quarantine object with ClamAV and promote clean bytes to a different key; download is denied until that transition succeeds. Existing database-backed attachments remain readable during migration.

Authentication endpoints are available under `/api/v1/auth`: login, logout, invitation acceptance, current-account lookup, profile updates, MFA enrollment/verification, and session administration. There is no public registration endpoint or sign-up UI. All project and generation endpoints require a valid session cookie.

Workspace administrators configure enterprise identity from **Settings → Security → Enterprise identity**. OIDC connections use discovery, PKCE, one-time hashed state, nonce validation, signed ID-token verification, encrypted client secrets, and verified-domain account linking. SAML connections can inspect a public HTTPS IdP metadata document, publish service-provider metadata, and use signed HTTP-Redirect AuthnRequests plus an HTTP-POST assertion consumer. Each connection receives a generated SP signing key encrypted at rest; its public certificate is published in metadata. The consumer requires XML signatures and validates issuer, audience, destination, request binding, validity conditions, subject confirmation, verified email domain, and durable assertion replay state. Administrators can overlap active and retiring IdP signing certificates during rotation, see fingerprints and expiry, and cannot revoke the final usable certificate of an enabled provider. Connections stay opt-in until a company domain is verified through the generated HTTPS well-known challenge and an administrator explicitly enables them. Enforcing SSO routes matching non-admin password logins to the provider; the default administrator password fallback preserves a break-glass recovery path.

The same settings surface creates expiring, scoped SCIM credentials. The plaintext bearer token is displayed once and only its SHA-256 digest is retained. Provisioners use `/scim/v2/Users` and `/scim/v2/Groups`; suspending a SCIM user revokes their active application sessions. Revoke a credential immediately after rotation. SAML sessions retain their NameID and SessionIndex so normal sign-out can use a signed SP-initiated Single Logout exchange; signed IdP-initiated requests revoke only matching sessions and receive a signed response. Logout request state and IdP-initiated request IDs are replay protected. OIDC, SAML, and SCIM must still be interoperability-tested with selected production identity providers, including real certificate-rotation and logout drills.

Entity admins manage contacts from **Settings → Entity & contacts**, but cannot create or rename entities. A new contact is stored as a pending invitation with a hashed, seven-day setup token. The email is delivered by a durable background job; the temporary delivery secret is AES-GCM encrypted at rest and redacted when the job completes or permanently fails. After the recipient follows the emailed link and sets a password, FlowForge creates their active user record in the same entity. Basic users can read all entity flowcharts but cannot generate, create, edit, save, or delete them.

Saved flowcharts expose an authenticated WebSocket room at
`/api/v1/collaboration/projects/{project_id}`. Users in the project's entity can see active
profile avatars, follow each other's cursors, and use a persisted delivery plan, tasks, and notes.
The flowchart's **Collaborate** panel is intentionally action-oriented: **Plan** defines owned
deliverables, target dates, calendar milestones, and progress; **Tasks** holds assigned work linked
to deliverables and specific diagram steps; **Notes** holds shared context and node-level
`@mentions`. Conversations live only
in the header **Messages** inbox, avoiding two competing chat surfaces. Admins can co-edit the graph
and receive live document updates; basic users receive the same
updates but remain view-only. The browser reconnects automatically after a temporary connection
loss.

Each saved flowchart also has durable project metadata. `projects.description` stores up to 2,000
characters of purpose and operating context, `projects.status` tracks `draft`, `active`, or
`archived`, and `projects.owner_id` identifies the accountable workspace member. The normalized
`project_collaborators` join table records the active working team without changing entity-level
visibility: all users in the entity can still view saved flowcharts, while admins manage project
metadata. The dashboard surfaces status, description, owner, and collaborator avatars; the editor's
**Project details** dialog is the management surface. `project_deliverables` stores the delivery
task completion into each outcome, while `project_tasks.node_id` anchors execution work back to the
diagram. Dashboard project cards expose the resulting deliverable/task counts and completion
percentage without opening the editor.

Every active entity contact also appears in the header message inbox. The inbox supports private
one-to-one conversations, workspace-wide channels, and member-selected private groups. Messages,
memberships, and per-user read state are stored in SQLite/PostgreSQL, while
`/api/v1/communications` delivers new messages and notifications immediately to the appropriate
recipients. Message unread counts stay in the Messages widget rather than being duplicated in the
notification bell. Flowchart notes can target the whole
diagram or a specific node. Typing `@` opens the entity contact picker; publishing the note creates
a durable notification for each selected username. Usernames are stable handles derived from the
contact's email prefix and user ID.

Collaboration and communication rooms retain only the sockets connected to each API replica.
Redis pub/sub fans project events, messages, and notifications to the replica that owns each
recipient socket. Presence is stored per connection with a TTL, deduplicated per user, and pruned
after crashes or network loss. PostgreSQL revisions remain the source of truth, so clients can
recover a missed ephemeral event by reconnecting and loading the latest snapshot.

Local development uses `FLOWFORGE_EMAIL_DELIVERY_MODE=console` and shows the generated setup link to the admin. For real delivery, set the mode to `smtp` and configure `FLOWFORGE_SMTP_HOST`, port, credentials, sender address, and TLS options from `backend/.env.example`.

## Internal entity API

Only the platform owner can create, list, or rename entities. Set a separate high-entropy `FLOWFORGE_INTERNAL_API_KEY`, then send it in the `X-FlowForge-Internal-Key` header from Postman or another trusted server-side client. Never put this key in the React environment or browser code.

Create an entity with at least one admin:

```http
POST http://127.0.0.1:8000/api/v1/internal/entities
Content-Type: application/json
X-FlowForge-Internal-Key: your-owner-key

{
  "name": "Northwind Operations",
  "data_region": "us-central",
  "data_residency_locked": true,
  "admins": [
    {
      "display_name": "Avery Admin",
      "email": "avery@northwind.example",
      "password": "replace-with-a-strong-initial-password"
    }
  ]
}
```

The admin can sign in immediately and invite additional admin or basic contacts. Admin passwords must contain at least 12 characters. The API rejects an empty admin list, duplicate admin emails, emails already assigned to another account, and a `data_region` that does not match this deployment. Once `data_residency_locked` is enabled, it cannot be disabled or moved through the API.

List entities and retrieve their IDs:

```http
GET http://127.0.0.1:8000/api/v1/internal/entities
X-FlowForge-Internal-Key: your-owner-key
```

Rename an entity:

```http
PATCH http://127.0.0.1:8000/api/v1/internal/entities/{entity_id}
Content-Type: application/json
X-FlowForge-Internal-Key: your-owner-key

{
  "name": "Northwind Global Operations",
  "max_users": 250,
  "max_projects": 5000,
  "max_storage_bytes": 53687091200,
  "max_monthly_generations": 5000,
  "max_pending_generations": 50
}
```

## Production work remaining

Before public launch, add email verification, password reset, dedicated login/invitation abuse policies, real-provider OIDC/SAML/SCIM staging validation, workspace-role audit events, managed production secret storage, off-process error aggregation, production multi-replica/10k-tenant load drills, automated backup restore drills, and a labeled model evaluation suite. Tenant authentication policy plus the repository OIDC, SCIM, SAML, metadata-import, request-signing, certificate-rotation, and Single Logout implementations are delivered in migrations `20260912_22` through `20260912_26`; this does not substitute for provider interoperability, certificate-rotation, and failover exercises. A bounded read-load tool is available at `scripts/load_reliability.py`; the dependency-ordered roadmap is in [docs/ENTERPRISE_SCALE_PROGRAM.md](docs/ENTERPRISE_SCALE_PROGRAM.md).

For an existing pre-governance database, install the backend requirements, back up the database, then adopt and apply the migrations before deploying the new application version:

```bash
alembic stamp 20260826_00
alembic upgrade head
```

Databases created by the Phase 1 governance build should be stamped at `20260827_01` and upgraded. Databases already initialized by the current development compatibility startup include the current schema and can be stamped at `20260829_10` instead of replaying migrations. Always inspect and back up an existing database before stamping it.
