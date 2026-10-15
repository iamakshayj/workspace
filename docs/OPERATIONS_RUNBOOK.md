# Operations and incident runbook

## Observe

- `/health` exposes dependency diagnostics; `/ready` gates traffic and now includes database connectivity; `/status` is a sanitized public status-page feed.
- `/metrics` requires the metrics key in production and includes request, job, queue-age, storage, scan, and process gauges.
- **Admin → Reliability** shows durable job status, deduplicated client/server operational events, integration degradation, webhook delivery history, and service objectives.
- Browser errors and unhandled promise rejections are scrubbed, fingerprinted, deduplicated, and reported to the operational-event store after authentication.

## Respond

1. Acknowledge the alert and name an incident commander.
2. Determine affected tenants/regions, first occurrence, deployment version, dependency state, queue age, and data-integrity risk.
3. Contain with a feature entitlement, connector disconnect, webhook disable, traffic rollback, or worker pause as appropriate.
4. Never delete or rewrite customer records during diagnosis. Use time-boxed, customer-approved support access and preserve legal holds.
5. Recover, verify representative reads/writes/realtime reconnects, monitor one full traffic window, and resolve the operational event.
6. Record the timeline, root cause, customer impact, evidence, corrective owner/date, and whether a notification obligation was triggered.

## Routine checks

- Daily: failed/stale jobs, connector lag, webhook failures, storage/scanner health, error regressions, certificate expiry.
- Weekly: quota growth, database/storage capacity, slow queries, audit export, access/support grants, SLO burn.
- Monthly: restore drill, key/secret rotation sample, permission matrix, cross-tenant tests, dependency upgrades, incident exercise.

External paging, log retention, SIEM ingestion, cloud dashboards, and on-call schedules remain deployment-specific and must be validated operationally.
