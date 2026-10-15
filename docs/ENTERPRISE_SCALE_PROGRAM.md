# Workspace enterprise scale program

This program turns the current integrated work platform into an enterprise-deployable product without treating external certifications or vendor infrastructure as code-complete features. Each phase has a dependency order, a repository deliverable, an operational deliverable, and a measurable release gate.

## Architecture boundaries

- **Tenant boundary:** every durable object carries an entity identifier; authorization is evaluated on the server and tested for cross-tenant denial.
- **Identity boundary:** local credentials, MFA, and sessions are owned by the application. SSO and lifecycle provisioning enter through a provider-neutral identity adapter.
- **Data boundary:** PostgreSQL is the system of record, Redis is coordination rather than durable truth, private object storage holds binaries, and search indexes are derived and rebuildable.
- **Realtime boundary:** API replicas share presence, messages, and document events through Redis. No correctness guarantee depends on one process's memory.
- **Intelligence boundary:** generated output is a proposal with source citations and permission checks; it never silently mutates governed records.
- **Regional boundary:** an entity is pinned to one deployment region. Cross-region moves use an explicit, audited migration process.

## Phase 1 — Enterprise identity and sessions

**Repository deliverables**

- Persisted, revocable browser sessions tied to a user and entity.
- Device/session inventory, revoke-one, revoke-others, logout revocation, and audit events.
- TOTP MFA enrollment, sign-in challenge, encrypted seed storage, one-time recovery codes, and disable flow.
- Session revocation enforced for HTTP and realtime WebSocket connections.
- Tenant-specific OIDC connections with encrypted client secrets, discovery validation, PKCE, nonce/state replay protection, verified login domains, just-in-time account linking, and an administrator break-glass path.
- Scoped, expiring, revocable SCIM bearer credentials plus tenant-isolated user and group provisioning.
- SAML 2.0 service-provider metadata, HTTP-Redirect authentication requests, HTTP-POST assertion consumption, encrypted signing certificates, signed-response verification, and replay protection.

**Operational deliverables**

- Identity-provider metadata/certificates, verified domains, break-glass owner accounts, and recovery procedures.
- Policies for required MFA, allowed authentication methods, session lifetime, and idle timeout.

**Release gate**

- Automated tests cover enrollment, challenge, recovery, revocation, tenant isolation, and realtime disconnect/reconnect.
- A revoked managed session cannot access REST, GraphQL, or WebSocket endpoints.
- SSO and SCIM are not marked complete until exercised against at least two real providers in staging.

**Current status:** local MFA and managed sessions are delivered in migration `20260912_21`. Migration `20260912_22` adds server-enforced tenant MFA scope, MFA session assurance, step-up verification, maximum session lifetime, idle expiry, compliance reporting, and policy administration. Migration `20260912_23` adds encrypted tenant OIDC configuration, globally unique verified domains, discovery, PKCE/state/nonce validation, JIT identity linking, SSO-only password routing, administrator break-glass access, one-time-display SCIM tokens, user lifecycle/session revocation, group synchronization, audit events, and an admin UI. Migration `20260912_24` adds the SAML repository adapter with SP metadata, AuthnRequest/RelayState handling, encrypted IdP certificates, signed-response validation, issuer/audience/destination/conditions/subject-confirmation enforcement, assertion replay storage, JIT linking, and shared domain policy. Migration `20260912_25` adds SSRF-guarded IdP metadata inspection, automatically generated per-connection SP signing keys, signed HTTP-Redirect AuthnRequests, signing-key publication in SP metadata, overlapping IdP certificate rotation, expiry/fingerprint visibility, last-certificate safeguards, and certificate lifecycle audit events. Migration `20260912_26` binds SAML NameID and SessionIndex to managed browser sessions, publishes the Redirect-binding logout service, and implements signed SP-initiated and IdP-initiated Single Logout with request state, issuer/destination/time/status validation, replay protection, targeted session revocation, cookie clearing, and audit events. Phase 1 remains operationally pending until OIDC, SAML, and SCIM are exercised against at least two real providers in staging, including an operational certificate-rotation and logout drill.

## Phase 2 — Policy, governance, and procurement controls

**Repository deliverables**

- One policy evaluator for entity, project, object, field, export, guest, and AI-source decisions.
- Reusable groups and group-backed grants; access requests with approval and expiry.
- Retention schedules by object class, legal holds, defensible deletion, admin audit search/export, and tamper-evident audit verification.
- DLP classification rules for uploads, messages, documents, generated output, and exports.
- Envelope-encryption abstraction with platform keys first and customer-managed key references second.
- Data-residency routing guardrails and an audited regional migration manifest.

**Operational deliverables**

- Data-processing inventory, subprocessor list, security whitepaper, incident process, vulnerability-management policy, and customer security questionnaire pack.
- Independent penetration test and the evidence program required for the chosen certification. These are external assurance activities, not application checkboxes.

**Release gate**

- A permission matrix test suite proves positive and negative access for admin, member, guest, group, project role, field, export, and AI retrieval.
- Legal-hold data survives normal retention cleanup; released data is deleted within the stated service objective.
- Security-sensitive admin actions are searchable, exportable, and integrity-verifiable.

**Current status:** migration `20260912_27` delivers the canonical policy evaluator, field/group/source-aware rules with deny precedence, DLP policies and metadata-only detection, classification and retention/residency policy records, legal holds, encryption-key references, feature entitlements, support access, SIEM NDJSON export, and a control-plane UI. Search, assistant, knowledge, chat, public API, export, and destructive project paths reuse the shared controls. Independent assurance, production retention execution, external KMS probes, and deployed regional verification remain operationally pending.

## Phase 3 — Production scale and disaster recovery

**Repository deliverables**

- Repeatable production topology for PostgreSQL, Redis, API replicas, workers, object storage, malware scanning, and observability.
- Idempotent background jobs, retry/dead-letter handling, queue aging alarms, bounded pagination, and large-object transfer grants.
- Load and failure-injection scenarios for search, chat, calendars, boards, large diagrams, calls, exports, and concurrent editing.
- Backup manifest, restore verifier, regional recovery runbook, and tenant export/delete tooling.

**Operational deliverables**

- Staging that mirrors production topology, monitored backup schedules, on-call ownership, incident exercises, and capacity forecasts.

**Release gate**

- Recorded tests meet defined p95 latency, error-rate, concurrency, and queue-delay objectives at target tenant size.
- Replica, worker, Redis, and object-storage interruptions degrade safely and recover without lost durable writes.
- A full restore is timed and validated against declared RPO/RTO, including private binary checksums.

**Current status:** the production topology, durable jobs, object quarantine/scanning, recovery manifest verifier, database-aware readiness, public status feed, authenticated metrics, endpoint load tool, and read-only mixed workload suite are repository-complete. Multi-replica soak, failover/fault injection, capacity evidence, monitored backups, and timed restores must still be run against production-like infrastructure.

## Phase 4 — Enterprise administration and commercial controls

**Repository deliverables**

- Admin center for domains, identity connections, groups, policies, integrations, retention, residency, audit, quotas, and feature entitlements.
- License/seat state, plan entitlements, usage metering, quota warnings, grace periods, and invoicing-provider adapter.
- Support-access workflow that is time-boxed, customer-approved, least-privileged, and audited.
- Health views for syncs, webhooks, imports, exports, background jobs, and realtime services.

**Release gate**

- A workspace owner can provision and govern a tenant without database access.
- Commercial entitlements are enforced server-side and never inferred only from UI visibility.
- Support personnel cannot enter a tenant without an approved, expiring audit trail.

**Current status:** **Admin** now provides policy, DLP/governance, legal hold, encryption-key inventory, connector/webhook/API-token controls, entitlements, quotas, approved expiring support access, incidents, service objectives, and compliance evidence. Billing-provider execution and real support-identity federation remain operational integrations rather than repository claims.

## Phase 5 — Usability system for daily work

**Repository deliverables**

- Shared design-system components for page headers, sidebars, tables, filters, editors, dialogs, loading, empty, error, offline, and permission-denied states.
- Consistent command palette, quick create, global navigation, keyboard model, undo semantics, responsive layouts, and accessibility coverage.
- One actionable inbox and one configurable home surface for assigned work, approvals, mentions, meetings, risks, and due items.
- Bulk operations, saved personal views, density preferences, and progressive disclosure for advanced controls.

**Release gate**

- Core workflows pass keyboard-only and screen-reader checks and meet WCAG 2.2 AA targets.
- Instrumented usability tests measure time-to-complete for onboarding, scheduling, project update, document review, and incident response.
- Every networked screen has stable loading, empty, retryable error, unauthorized, and stale-data behavior.

**Current status:** shared navigation, responsive shells, loading/empty/error states, offline indication, skip navigation, global search keyboard browsing/opening, undo and stale-save conflict handling are delivered across the primary surfaces. Formal WCAG audit, assistive-technology matrix, and instrumented usability studies remain operational validation gates.

## Phase 6 — Unified search and organizational memory

**Repository deliverables**

- Permission-filtered keyword search over projects, work, documents, messages, meetings, people, files, decisions, risks, and diagrams.
- Facets, saved/recent searches, snippets, result previews, keyboard navigation, and object-type deep links.
- Derived semantic index with tenant-scoped embeddings, hybrid ranking, source-level authorization rechecks, deletion propagation, and rebuild tooling.
- Cross-object timeline and historical query surface backed by canonical work-graph relationships.

**Release gate**

- Search relevance and permission-leak evaluation sets run in CI/staging.
- Index lag, failed indexing, orphaned documents, and deletion propagation are observable.
- Semantic retrieval never expands a user's rights beyond the source object's current authorization.

## Phase 7 — Integration platform

**Repository deliverables**

- Versioned public API, scoped service accounts, OAuth connection records, encrypted credentials, webhook subscriptions, signing, retries, replay, and delivery logs.
- Connector SDK with incremental sync cursors, rate-limit backoff, idempotency, field mapping, conflict policy, and admin health views.
- First production connectors selected from customer demand: typically calendar/email, file storage, identity, development, and CRM systems.
- Import/export interoperability for common document, task, diagram, calendar, and file formats.

**Release gate**

- Contract, replay, deletion, permission, expiry, and vendor-rate-limit tests exist for every connector.
- A failed connector cannot block interactive requests or corrupt the canonical source of record.
- Administrators can see scope, last sync, errors, retries, and disconnect impact before revoking access.

**Current status:** migration `20260912_27` adds encrypted connector state/cursors, scoped hashed service tokens, `/public/v1` read APIs, transactionally staged project/work lifecycle webhooks with signing, retries and delivery logs, and admin health controls. Vendor OAuth applications and adapter-specific sync execution remain operationally pending until credentialed contract suites pass.

## Phase 8 — Differentiated work intelligence

**Repository deliverables**

- Evidence-backed daily briefings, meeting preparation/follow-up, project health, dependency impact, workload risk, execution drift, and stale-knowledge detection.
- Human-reviewed graph changes, action extraction, and workflow automation with preview, approval, idempotency, rollback strategy, and audit provenance.
- Outcome instrumentation connecting plans, decisions, meetings, documents, workflow execution, and delivery results.

**Release gate**

- Every recommendation exposes its sources, freshness, confidence, permission scope, and proposed action.
- Offline evaluations cover correctness, permission leakage, harmful actions, and regression against a curated enterprise dataset.
- Automated actions require explicit policy and approval; intelligence features remain useful when model services are unavailable.

**Current status:** `/api/v1/intelligence/briefing` now produces deterministic, permission-filtered daily priorities, dependency blockers, project-health scores, material-risk prompts, meeting preparation/follow-up gaps, and stale-knowledge reviews. Every recommendation includes source links, observation time, freshness, confidence, evidence, current-user permission scope, and a non-mutating proposed review action. Home exposes these insights without adding another dashboard widget, and the engine remains available when the local model is offline. Migration `20260913_28` and `/api/v1/change-proposals` add permission-filtered graph-change previews, independent reviewer enforcement, evidence filtering, fingerprint-based drift protection, idempotent create/apply behavior, guarded rollback, notifications, relationship history, and audit provenance. The Operations approval center exposes this lifecycle without silently changing governed records. General action extraction, reusable automation policies, outcome attribution, and curated offline evaluation datasets remain the next Phase 8 slices.

## Delivery cadence and definition of done

Deliver each phase as vertical slices behind entity feature flags. A slice is complete only when schema migration, authorization, audit, API, UI, accessibility, telemetry, tests, operational documentation, rollback, and data cleanup are all covered. External certification, managed service deployment, DNS/email reputation, identity-provider configuration, TURN/SFU capacity, and vendor connector approval must remain visibly “operationally pending” until real staging or production evidence exists.

Recommended order: finish Phase 1 provider/policy work; run Phases 2 and 3 together; build Phase 4 on their APIs; then execute Phases 5–7 in customer-validated slices. Phase 8 should consume those foundations rather than create parallel data or permission systems.
