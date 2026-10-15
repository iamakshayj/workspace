# Service desk and guest portal

Workspace includes a tenant-isolated service desk for requests, incidents, problems, and changes. Tickets share the same identity, permissions, notifications, audit trail, enterprise search, and work-graph services as projects, work items, documents, meetings, decisions, and risks.

## Service desk

Open **Service** from the global navigation. The queue shows severity, ownership, state, and response/resolution SLA health. Any workspace member can create a request. The requester, assigned agent, or an administrator can update it; administrators can also assign active workspace members.

Supported lifecycle states are `open`, `triage`, `in_progress`, `waiting`, `resolved`, and `closed`. Default response/resolution objectives are based on severity:

| Severity | First response | Resolution |
| --- | ---: | ---: |
| Critical | 15 minutes | 4 hours |
| High | 1 hour | 8 hours |
| Normal | 4 hours | 2 days |
| Low | 8 hours | 5 days |

On-call rotations are tenant-scoped records with a service, member list, timezone, cadence configuration, and active state. Administrators manage them through `/api/v1/service-desk/configuration/on-call`.

Service tickets are indexed by enterprise search as `service_ticket` objects and can participate in canonical work-graph relationships. For example, an incident can `impact` a project, be `documented_by` a runbook, or be `related_to` a deployment work item. Search and graph traversal apply the same permission filters as direct object access.

## External guest access

Administrators can create a seven-day ticket link from **Service → ticket → External collaboration**. A grant is limited to one resource, one guest email, an explicit permission set, and an expiration. Only a SHA-256 digest of the random bearer token is stored.

Guests open `/guest/{token}` without a workspace account. Depending on the grant, they may:

- view the shared resource;
- add a comment; or
- record an approval.

Every guest access and response updates the auditable resource history. Links can be revoked immediately, expire automatically, and never grant access to another object or tenant. The creation response is the only place the complete link is returned, so copy it before leaving the ticket.

## API overview

Authenticated service-desk endpoints are under `/api/v1/service-desk`:

- `GET/POST /service-desk`
- `PATCH /service-desk/{ticket_id}`
- `GET/POST /service-desk/{ticket_id}/comments`
- `GET/POST /service-desk/configuration/on-call`
- `GET/POST /service-desk/configuration/guest-grants`
- `POST /service-desk/configuration/guest-grants/{grant_id}/revoke`

Guest endpoints are under `/api/v1/public/guest/{token}`. They do not accept workspace sessions as authorization; the expiring, revocable token is the entire grant.

## Deployment

Run migration `20260915_29` before starting the updated backend:

```bash
alembic upgrade head
```

Set `FRONTEND_URL` to the externally reachable web origin so generated guest URLs point to the correct deployment. Always use HTTPS outside local development. Avoid sending guest links in public channels, and revoke them when the external collaboration is complete.
