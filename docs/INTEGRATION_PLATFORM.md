# Integration platform guide

## Contracts delivered

- `/public/v1` is a separately versioned API authenticated by hashed `wsp_` bearer tokens.
- Tokens are tenant-bound, scoped, expiring, revocable, residency-checked, and mapped back through current object authorization and policy decisions.
- Connector records persist encrypted credentials, requested scopes, health, incremental cursors, conflict policy, last/next sync, failures, and disconnect state.
- Syncs run through durable background jobs; interactive requests never wait on a vendor.
- Webhook subscriptions use one-time-display secrets. Project and work-item lifecycle changes stage an outbox delivery in the same transaction as the business mutation. Each delivery has an event ID, canonical JSON, HMAC-SHA256 signature, durable status, bounded retry, and delivery history.

## Public API examples

```bash
curl -H "Authorization: Bearer wsp_REDACTED" \
  "https://workspace.example.com/public/v1/projects?limit=100"
```

Available read scopes are `projects:read`, `work:read`, and `documents:read`. New resources must reuse the same principal, tenant, object-access, and policy checks before they are added.

Webhook receivers should verify `X-Workspace-Signature-256` over the exact request body, deduplicate `X-Workspace-Event-ID`, accept the event quickly, and process asynchronously.

Subscriptions accept an exact event (`project.updated`), a namespace wildcard (`project.*`), or the global wildcard (`*`). Current lifecycle events are `project.created`, `project.updated`, `project.deleted`, `work_item.created`, `work_item.updated`, `work_item.deleted`, and `work_item.comment.created`. Payloads intentionally contain identifiers and state metadata rather than user-authored content.

## Provider adapter definition of done

Each production adapter still needs vendor OAuth registration and contract tests for consent, token refresh, incremental paging, rate limiting, deletion, permission changes, replay, conflicts, and disconnect cleanup. A configured connector record is not evidence that a vendor adapter has passed those gates.
