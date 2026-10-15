# Production validation gates

Repository tests prove behavior in-process; they do not prove a deployment can meet enterprise scale or recovery objectives. Run and retain the following evidence against a production-like staging environment.

## Release sequence

1. Deploy at least two API replicas, two workers, managed PostgreSQL with point-in-time recovery, Redis, versioned object storage, malware scanning, ingress TLS, the local model service, logs, metrics, and alert routing.
2. Run migrations as a single pre-deploy job and verify `/ready` reports every critical dependency operational.
3. Run the full automated backend/frontend suites and migration upgrade/downgrade rehearsal.
4. Run `scripts/load_reliability.py` per high-value endpoint and `scripts/enterprise_scale_suite.py` for a mixed daily-work workload. Store p50/p95/p99, throughput, error rate, rate limits, and observed replica IDs.
5. Run concurrent editing, WebSocket reconnect, queued export, attachment scan, model outage, worker kill, Redis interruption, storage interruption, database failover, and API replica termination drills.
6. Execute `docs/RECOVERY_RUNBOOK.md` in an isolated environment and store achieved RPO/RTO plus database and object checksums.
7. Review open operational events, failed jobs, integration/webhook health, audit-chain verification, and compliance evidence before promotion.

## Default acceptance targets

| Gate | Initial target |
| --- | --- |
| Interactive API availability | ≥ 99.9% monthly |
| Mixed workload p95 | ≤ 1,000 ms |
| Error rate under rated load | < 0.5% |
| Realtime durable-write loss | 0 |
| Oldest queued interactive job | < 60 seconds |
| RPO / RTO | ≤ 15 / 60 minutes |
| Cross-tenant leakage | 0 findings |
| Accessibility | WCAG 2.2 AA for core flows |

Change targets only through a reviewed service-objective decision. Do not mark a gate complete without dated output from the actual staging topology.
