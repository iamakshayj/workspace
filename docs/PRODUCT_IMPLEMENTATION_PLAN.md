# FlowForge product implementation plan

## Product thesis

FlowForge should become a private process-intelligence platform, not a general-purpose whiteboard. The product loop is:

**Capture → validate → approve → execute → observe → improve**

The flowchart is the shared interface for a controlled operational process. Tasks, notes, evidence, analytics, and automation should remain attached to that process instead of becoming separate products.

## Delivery principles

- Build trust before adding breadth: access control, approvals, immutable revisions, and auditability come first.
- Keep the current graph document in PostgreSQL JSONB; introduce a graph database only for cross-process dependency analysis.
- Preserve a self-hosted model option, but isolate inference behind a queued service so app reliability does not depend on model latency.
- Make every enterprise feature tenant-aware and enforce permissions on the server, not only in the UI.
- Ship each phase behind measurable release gates and retain compatibility with existing flowcharts.

## Phase 1 — Trust and governance

**Objective:** make a flowchart a controlled process record.

Deliverables:

- Project visibility: workspace-wide or restricted.
- Project access roles: owner, editor, commenter, viewer, and approver; workspace admins retain emergency administration access.
- Immutable numbered revisions created on explicit saves.
- Approval requests and approve/request-changes decisions tied to a revision.
- Restorable revision history.
- Audit events for project creation, saves, access changes, approval actions, and restoration.
- A Governance view in Project details showing status, access, history, and recent activity.
- Alembic migration files for new production schema changes.

Acceptance criteria:

- A restricted flowchart is not returned to an entity member without access.
- An editor can update a flowchart but cannot change access or approve it.
- An approver can decide a pending approval but cannot edit the graph unless separately granted editor access.
- Approvals reference an immutable revision; saving a later revision returns the project to draft.
- Restoring an old revision creates a new revision rather than rewriting history.
- Every governance mutation records actor, action, time, project, and structured context.

## Phase 2 — Scale and reliability

**Objective:** remove single-process and large-volume bottlenecks.

Deliverables:

- PostgreSQL in every deployed environment and Alembic-only production startup.
- Cursor pagination and indexed search for projects, tasks, notes, audit events, and revisions.
- Redis pub/sub and presence storage for multi-instance WebSockets.
- Revision preconditions and delta-based graph operations; adopt Yjs when simultaneous editing usage justifies CRDT complexity.
- Background jobs for model inference, email, export, attachment scanning, and evidence packages.
- Object storage with presigned uploads/downloads and malware scanning.
- Per-tenant quotas, request throttling, structured logs, metrics, tracing, and error reporting.
- Backup/restore runbooks with routinely tested recovery targets.

Release gates:

- Load tests cover concurrent editors, 10k-project tenants, large diagrams, and queued generations.
- No in-memory component is required for correctness across multiple API replicas.
- Large files never pass through or live inside the relational database.

## Phase 3 — Process intelligence

**Objective:** make the approved diagram observable and operationally valuable.

Deliverables:

- CSV and webhook event ingestion with a versioned event mapping model.
- Per-node and per-branch overlays for volume, cycle time, SLA misses, failures, and cost.
- Drift detection between approved revisions and observed execution paths.
- Compliance controls and evidence requirements attached to nodes.
- Auditor-ready evidence packages with approval and revision provenance.
- Natural-language change proposals rendered as reviewable graph diffs.
- Linked SOP, RACI, checklist, training, control, and test-case artifacts with staleness detection.

Release gates:

- A customer can connect one operational event stream and see actionable process variance.
- Every metric and evidence item identifies its source and time range.
- Proposed model changes never mutate the approved process without human approval.

## Phase 4 — Defensible platform

**Objective:** compound customer process data into a durable system of record.

Deliverables:

- Cross-process dependency graph for systems, teams, vendors, controls, and data classes.
- Impact analysis when an owner, system, policy, vendor, or regulation changes.
- Capacity and cost simulation using volumes, branch probabilities, wait time, staffing, and failure rates.
- Controlled human workflow execution, then selected webhooks, forms, approvals, and scheduled actions.
- OIDC and SAML SSO plus SCIM provisioning are repository-complete, alongside TOTP MFA, encrypted recovery state, revocable browser-session administration, SAML metadata inspection, signed AuthnRequests, overlapping certificate rollover, and bidirectional SAML Single Logout. Real-provider staging validation, retention policies, DLP, encryption key options, and data residency controls remain.
- Public APIs, webhooks, embedded diagrams, and targeted enterprise integrations.

## Prioritized backlog outside the critical path

Diagram depth should improve in focused slices: swimlanes and subprocesses first; then multi-select, alignment, routing, keyboard workflows, templates, SVG/PDF/BPMN interoperability, presentation mode, accessibility, and mobile viewing. General-purpose chat, broad work management, and novelty canvas features should not outrank governance or process intelligence.

## Metrics

- Activation: first verified flowchart created and shared within one day.
- Trust: percentage of active flowcharts with an owner, approver, and approved revision.
- Engagement: weekly viewers/editors per governed flowchart and revision review time.
- Intelligence: connected event sources, detected drift incidents, and resolved SLA/control exceptions.
- Expansion: governed processes and active collaborators per entity.
- Reliability: save conflict rate, WebSocket reconnect rate, generation queue time, and restore success.

## Current implementation slice

Phases 1 and 2 are implemented end to end. The first integrated Phase 3/4 product slice is also implemented:

- CSV execution-event imports persist a versioned activity-to-node mapping and drive per-step and per-branch overlays for volume, wait time, SLA misses, failures, and cost.
- Conformance analysis persists reviewable drift incidents for unexpected transitions, skipped required/control steps, unmapped activities, failures, and SLA breaches.
- Nodes carry operating metadata for ownership, systems, vendors, controls, policies, evidence, segregation, risk, data classification, SLA, review date, layers, and hierarchy.
- Evidence packages include process import and insight provenance. Operating-document packages generate an SOP, RACI, checklist, training guide, controls register, test cases, and executive summary with source-revision and checksum metadata.
- The entity dependency index exposes impact search across owners, systems, vendors, policies, controls, and data classes.
- Editor depth now includes swimlanes, subprocesses, layer filtering, grid snapping, multi-selection, alignment, distribution, and duplication.
- Diagram nodes now have normalized delivery bindings: a primary epic/story/task, optional sprint context, and an optional sub-flowchart. Epic children and sprint metrics roll up into live node progress, while deep links preserve the selected flowchart/node context in the Work hub.
- The communication hub now combines tenant-scoped one-to-one messages, discoverable workspace channels, and member-selected private groups. Each conversation has independent unread state and realtime socket delivery without duplicating chat traffic into actionable notifications.
- Authenticated call signaling now connects direct conversations, channels, groups, and scheduled calendar meetings to one reusable WebRTC call panel. Camera and microphone permission is deferred to the lobby’s explicit join action; production ICE/TURN configuration is build-time deployable.
- Each account now has a tenant-scoped personal calendar. Private focus blocks remain owner-only; one-to-one and team meetings use explicit attendee membership, RSVP state, realtime updates, deep-linked notifications, and organizer-controlled rescheduling or cancellation.
- Team scheduling now provides a tenant-scoped free/busy query and ranked common openings for up to 100 participants. The response contains merged time blocks only, never private event metadata, and the UI transfers a selected slot into the existing invitation workflow.

The reliability foundation remains:

- Production uses PostgreSQL, runs Alembic as a one-shot deployment step, and refuses to start on a missing or unexpected database revision.
- Fresh databases can migrate from the baseline through governance and scale-foundation revisions.
- The dashboard uses tenant-aware project search, a PostgreSQL full-text GIN index, stable cursor pagination, and bounded page sizes.
- GraphQL, REST, and WebSocket document writes require an expected revision. Stale writes are rejected without overwriting the editor's canvas, and rapid same-client live writes are serialized.
- Redis pub/sub fans project events, messages, and notifications across API replicas. Per-connection presence uses expiring Redis records, deduplicates multiple tabs, and recovers from unclean disconnects.
- Production readiness now includes PostgreSQL revision verification and Redis reachability. Local development retains a contract-compatible in-process broker.
- Flowchart generation runs as a durable database job. Redis wakes dedicated workers, while database polling, leases, retry limits, and persisted results protect correctness across restarts.
- Attachments use short-lived S3-compatible transfer grants. Bytes move through quarantine storage rather than PostgreSQL, scanning jobs call ClamAV, and only promoted clean objects can be downloaded.
- Development uses an embedded worker and filesystem object adapter; production requires a separate worker, private S3-compatible storage, and ClamAV.
- Platform-configured entity quotas now cover reserved seats, projects, storage reservations, monthly generation volume, and generation queue depth. Enforcement locks the entity row before counting and creating capacity-consuming records.
- HTTP requests are rate-controlled with Redis across production replicas and a contract-compatible local limiter in development. Responses report limits, remaining requests, reset timing, and retry timing.
- API and worker events use production JSON logs with request and trace correlation. A protected Prometheus endpoint reports bounded-route latency/status metrics, quota/rate rejections, queue depth, scan backlog, and oldest queued-job age.
- Worker maintenance removes abandoned quarantine uploads, redacts private job inputs/results after their retention window, and removes old job metadata. Automated tests cover expired worker leases and cleanup recovery.
- Invitation emails are transactionally queued with invitations, carry only an AES-GCM encrypted setup token, retry independently of API requests, and redact the encrypted payload after terminal completion.
- SVG and JSON exports plus manager-only evidence ZIPs run as durable jobs. Evidence manifests checksum the included graph, revisions, approvals, access, audit, and delivery-plan records.
- Generated artifacts use private object storage, authenticated expiring downloads, per-entity storage accounting, retention cleanup, and project-deletion cleanup.
- A bounded authenticated load tool identifies serving replicas and unique request IDs. A read-only recovery verifier compares database manifests and validates attachment/artifact objects after restore.

The remaining release work is tracked in [Enterprise Scale Program](ENTERPRISE_SCALE_PROGRAM.md). Tenant identity policy and the repository OIDC/SAML/SCIM slices are delivered. Immediate priorities are real-provider identity staging validation and certificate-rotation drills, followed by production-like multi-replica load, worker-failure, and backup/restore drills. Webhook connectors, simulation, natural-language change proposals, and external integrations remain dependency-ordered work above.
