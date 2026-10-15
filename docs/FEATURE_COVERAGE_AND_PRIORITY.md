# Workspace feature coverage and priority

This is the implementation ledger for the 50-module Workspace guide. A feature is marked **delivered** only when it has persisted data, server-side authorization/validation, a usable UI, and regression coverage. UI demonstrations without the complete contract are marked **partial**.

## Delivered in the current hardening pass

- Project profiles now persist key, sponsor, department, team, program, priority, health, start and target dates, progress, classification, tags, and template selection. The values are available through REST and GraphQL, preserved in revisions/restores and JSON/evidence exports, editable in Project details, and summarized on workflow cards.
- The work-item engine now supports initiative, epic, feature, story, task, subtask, bug, spike, improvement, and technical-debt types; owner, severity, actual effort, component, team, checklist, watchers/following, archive/restore, duplicate, copy-link, and bulk-update contracts; and a larger set of typed relationships.
- Work notifications now deep-link to the affected work item and watchers receive meaningful update/comment activity without duplicating ordinary chat traffic.
- Agile reporting now includes throughput, blocked work, lead time, cycle time, and an active-sprint burndown derived from activity history.
- Smart tables gained filtering, sorting, and CSV export while retaining the workflow/board connection.
- Calendar gained an agenda view in addition to day, week, and month.
- Diagramming gained UML, ERD, architecture, network, mind-map, organization-chart, sticky-note, and comment objects in addition to the existing basic, BPMN, and enterprise symbols.
- Native chat now persists reply threads, reactions, author edits and soft deletion, conversation pins, personal bookmarks, safe link attachments, mention notifications, typing presence, direct-message read receipts, permission-filtered message search, and message-to-task conversion. Every message mutation revalidates tenant/conversation access on the server and fans changes through the realtime broker.
- Calls now offer microphone/camera selection before joining and in-call screen sharing while retaining direct, channel, group, and scheduled-meeting contexts plus the non-modal mini/collapsed/expanded call window.
- Revision 18 adds the **Operations** control plane: project risk and decision registers, reusable organization groups, project group access, employee reporting lines and capacity, a cross-object relationship graph, dependency/cycle/impact analysis, unified organizational history, meeting records and follow-up extraction, saved dashboards and reports, approval workflows, governed file references, notification preferences, audit-chain verification, and retention controls.
- Work management now includes formatted descriptions/comments, threaded replies, reactions, link attachments, custom fields, custom work types, split and merge actions, saved board views, swimlanes, release baselines/scenarios, release burnup, and chunked spreadsheet rendering with formulas.
- Diagramming now includes automatic layout, presentation mode, a facilitation timer, accessible nodes/handles, and revision-to-revision summary comparison.
- Guest accounts are enforced at the project, knowledge, work, audit, reporting, dependency, and Operations boundaries. Project field rules and reusable group grants are evaluated server-side.

## Current product coverage

| Guide area | Status | Completion detail |
|---|---|---|
| 3 Project management | Delivered | Operations project overview includes risks, decisions, relationships, linked documents/meetings, group access, and project workflow/field/notification/integration/automation/permission settings. |
| 4 Tasks / epics / stories | Delivered | Formatted content, threaded comments/reactions, attachments, split/merge/move, saved views, custom fields/types, hierarchy, and audit activity are persisted and authorized. |
| 5 Organization / teams / people | Delivered | Nested business units/teams, memberships, managers, reporting lines, skills, capacity, timezones, profiles, and organization view are persisted. |
| 7 Enterprise permissions | Delivered | Reusable groups, project group grants, field rules, guest role, access requests, document roles, and tenant/project filtering are server-enforced. |
| 9 Dependencies & blockers | Delivered | The work graph provides project/cross-project paths, write-time cycle prevention, cycle reporting, schedule impact, and critical-path-oriented analysis. |
| 10 Organizational memory | Delivered | Permission-gated cross-object history supports type/object/search filters and includes source, actor, request, and integrity evidence. |
| 11 Meetings | Delivered | Agenda, durable notes/actions, transcript and recording references, searchable history, and action/decision/risk extraction are persisted. |
| 15 My Work / Home | Delivered | Four focused widgets, evidence-backed daily briefing, notification triage, and one-hour snooze are live; custom dashboards provide user-selected widgets. |
| 16 Notifications / inbox | App complete | Type/channel/digest preferences, grouping keys, snooze, realtime in-app delivery, and filtering are implemented. Email-digest and browser/mobile push need provider credentials. |
| 17 Audit | Delivered | Admin history search/filter/export, configurable retention/legal hold, request correlation, and tamper-evident hash-chain verification are implemented. |
| 19 Kanban / agile | Delivered | Saved boards, assignee/team/project swimlanes, backlog/sprint/release planning, WIP limits, velocity, cumulative flow, burndown, and release burnup are implemented. |
| 22 Dashboards | Delivered | The builder persists widget sets, shared/private scope, layout metadata, drill-down query configuration, and scheduled-delivery metadata. |
| 24 Roadmaps | Delivered | Releases provide targets, baselines, named scenarios, progress/burnup, project context, and dependency linkage. |
| 28 Approvals | Delivered | Reusable definitions support sequential/parallel stages, delegation, reminders/escalations, generic targets, decisions, and project-access grants. |
| 31 Smart tables | Delivered | Sheet formulas, persisted custom columns, grouping, permission-aware editing, CSV export, validation, saved views, and bounded chunk rendering are implemented. |
| 33 Calendar | App complete | Day/week/month/agenda, recurring actions, shared availability, guests, reminders, and persisted working-hours/holiday/shared-calendar/sync settings are implemented. Google/Microsoft sync needs OAuth and a worker. |
| 34 Reporting | Delivered | Operations includes governed cross-object report building, saved definitions, dashboard delivery metadata, bounded aggregation, and audit export. |
| 38 Native chat | App complete | Direct/channel/group chat supports threads, reactions, code text, link attachments, search, edit/delete, pins/bookmarks, mentions, and conversion to task/request/decision/risk/meeting. Binary media and production moderation/export require storage/workers. |
| 39 Whiteboards | Substantial | Shape/symbol library, layers, multi-select, snap/alignment, auto-layout, timer, and presentation mode are delivered. Pressure-sensitive ink, voting sessions, and viewport virtualization remain specialized canvas work. |
| 40 Diagrams / flowcharts | Delivered | BPMN, UML, ERD, organization, mind-map, architecture, network and enterprise semantics, layout/routing, SVG/JSON/PNG export, revision comparison, and accessible nodes/handles are implemented. |
| 45 File management | App complete | Operations provides folders, tags, previews, versions, full-text metadata/content search, sharing, classification, and provider references. Binary provider sync needs credentials. |
| 46 Voice / video | Prototype complete | Authenticated direct/channel/group/meeting rooms, lobby, devices, screen share, roster, mute/camera, and mini window are implemented. Multi-party SFU/TURN, recording/captions, breakouts, and telemetry require media infrastructure. |

## Ranked broader-guide work

Rank combines customer value, enterprise sales impact, cross-module leverage, and dependency order.

1. **Enterprise Work Graph (module 1) — foundation delivered.** Typed tenant-scoped relationships, validation, history, dependency traversal, cycle checks, and related project views are present. Next: a single global multi-hop explorer and semantic index.
2. **Enterprise Search (module 6).** Permission-filtered keyword search first, then semantic/hybrid search, facets, saved searches, recent searches, and result previews. An all-in-one tool is not usable at scale without one search surface.
3. **Enterprise identity and security (modules 18, 49, 50).** Guest isolation, audit export/integrity verification, TOTP MFA with recovery codes, revocable session/device administration, tenant MFA scope, session assurance, idle expiry, session-lifetime policy, tenant OIDC/SAML configuration and domain discovery, scoped SCIM user/group provisioning, SAML metadata inspection, signed AuthnRequests, overlapping certificate rollover, and bidirectional SAML Single Logout are implemented. Real-provider identity staging evidence, DLP, customer-managed encryption keys, and operational data-residency deployment remain procurement-gate work.
4. **Documents and knowledge (module 13) — delivered.** Versioned rich-text documents, optimistic concurrency, comments and `@mentions`, document embeds/backlinks, spaces, templates, review/expiry lifecycle, classification, search, restore, and document-level viewer/commenter/editor access are available under **Knowledge**.
5. **Risks, issues, and decisions (modules 12 and 14) — core delivered.** Project registers, owners, due dates, scoring, mitigations, alternatives, consequences, status, and work-graph relationships are present. Next: portfolio risk simulations and decision supersession UI.
6. **Integration platform (module 8).** Connector framework, credentials, mapping, incremental sync, retries, conflict handling, observability, and webhooks before adding individual vendor integrations.
7. **Workflow automation (module 27).** Versioned trigger/condition/action rules, dry runs, execution logs, retries, idempotency, failure queues, and guardrails.
8. **Portfolio/program management and goals (modules 23 and 26).** Strategic hierarchy, prioritization, rollups, scenarios, OKRs, confidence, check-ins, and traceable contribution from delivered work.
9. **Resource/capacity planning and Gantt (modules 32 and 25).** Availability, allocations, skills, overbooking warnings, dependencies, baselines, critical path, and scenario planning.
10. **Unified inbox production transports (module 16).** App preferences, grouping, snooze, realtime delivery, and follow rules are present. Next: provider-backed email digest, browser/mobile push, and high-volume cursor pagination.
11. **Request center, forms, and approval engine (modules 29, 30, 28).** Schema-driven forms, catalogs, routing, SLA, reusable approval chains, delegation, escalation, and external intake.
12. **Executive intelligence expansion (modules 34 and 36).** Saved governed reports, dashboards, delivery metadata, drill-down configuration, and source audit are present. Next: anomaly explanations and a production scheduled-delivery worker.
13. **Custom objects (module 35).** Tenant-defined schemas, relationships, validation, permissions, views, lifecycle, search indexing, and audit history—after the canonical graph exists.
14. **File-provider operations (module 45).** Folder/tag organization, metadata previews, versions, search, permissions, lifecycle fields, and provider references are present. Next: OAuth-backed Dropbox/Box/Drive sync and binary preview generation.
15. **AI retrieval, evidence, and actions (modules 2, 20, 21).** Build on the local-model boundary already present, but only after search/work-graph permission filtering is canonical. Require citations, dry-run previews, approvals, and action logs.
16. **Chat and meeting production services (modules 11 and 38).** Threads, reactions, links, search, meeting artifacts, transcript ingestion, and follow-up extraction are present. Next: managed binary media, retention/export workers, and recorded-media transcription.
17. **Production voice/video (module 46).** Replace peer-to-peer prototype assumptions with an SFU/media service, TURN, recording/captions, screen sharing, moderation and telemetry.
18. **Advanced visual scale and interoperability (modules 19, 24, 31, 33, 39, 40).** Saved views, formulas, chunking, scenarios, layout, revision comparison, exports, and accessibility are present. Next: pressure-sensitive ink, voting, true viewport virtualization, and third-party diagram/calendar imports.
19. **Mobile and offline (modules 47 and 48).** Responsive/push-first mobile, offline read/cache, queued edits and conflict resolution after APIs and object semantics stabilize.
20. **No-code apps, expertise graph, financials, and agents (modules 41–44 and 37).** Valuable expansion products, but each depends on the graph, permissions, automation, search and governance layers above.

## Recommended next production slice

The highest-value application foundations in the requested table are now present. The next slice is infrastructure and operational hardening: deploy PostgreSQL/Redis/S3 plus an SFU/TURN media service, configure SMTP/push and Google/Microsoft OAuth providers, run digest/sync/retention/report-delivery workers, and add high-volume load tests and telemetry alerts. Those tasks require deployment credentials and service choices; they cannot be made production-complete solely inside the repository.
