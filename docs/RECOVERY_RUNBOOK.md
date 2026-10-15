# FlowForge backup and recovery runbook

## Objectives

- PostgreSQL and object storage are the durable systems of record.
- Redis contains only ephemeral wake-ups, presence, pub/sub messages, and rate-limit counters.
- Target recovery point objective (RPO): 15 minutes.
- Target recovery time objective (RTO): 60 minutes for a single-region deployment.

Adjust the targets before signing a customer contract, and monitor actual drill results rather than treating these targets as guarantees.

## Backup policy

1. Enable continuous PostgreSQL WAL archiving and take a daily encrypted base backup.
2. Enable versioning on the private attachment bucket and replicate it to a separate failure domain.
3. Back up deployment secrets through the chosen secret manager; never place them in database dumps.
4. Retain daily backups for 35 days and monthly backups for 12 months unless a tenant retention agreement requires otherwise.
5. Record the application image digest and Alembic revision with each backup set.

## Restore drill

Run this at least monthly in an isolated account or namespace.

1. Provision an empty PostgreSQL database and private object-storage bucket.
2. Restore the selected database base backup and replay WAL to the chosen recovery timestamp.
3. Restore or expose the matching versioned object snapshot.
4. Deploy the exact recorded application image with workers stopped.
5. Run `alembic current` and confirm it equals the application's expected revision.
6. Run the recovery verifier against the backup manifest while workers remain stopped.
7. Start one API replica and verify `/ready`, authentication, project counts, and a sample of attachment and generated-artifact metadata.
8. Verify clean sample attachments and unexpired generated artifacts can be downloaded; quarantine objects must remain inaccessible.
9. Start workers. Confirm stale `running` jobs are reclaimed after their lease and queued jobs complete.
10. Record achieved RPO/RTO, errors, and remediation owners in the incident system.

## Failure behavior

- Redis loss: API readiness fails in production; durable jobs remain in PostgreSQL and workers recover them by polling after Redis returns.
- Worker crash: a `running` job becomes claimable after `FLOWFORGE_JOB_LEASE_SECONDS`.
- Model outage: generation jobs retry with bounded backoff and then fail with a stable error code.
- Scanner or storage outage: attachment downloads remain locked; jobs retry without marking unscanned content clean.
- API replica loss: no correctness state is stored only in that process. Clients reconnect and reload the persisted project revision.

## Automated gates

- `backend/tests/test_background_jobs.py` verifies durable job claiming and worker execution.
- `backend/tests/test_reliability_controls.py` verifies quotas, throttling, stale upload cleanup, result redaction, and history retention.
- `backend/tests/test_artifacts_and_email_jobs.py` verifies encrypted queued email delivery, artifact generation, checksummed evidence contents, and expiry cleanup.
- `scripts/load_reliability.py` provides a bounded authenticated read load check with latency, error, request-ID, and replica-count thresholds.
- `python -m backend.app.recovery_check` creates and verifies read-only database/object manifests.

Run the recovery tests with:

```bash
.venv/bin/python -m pytest backend/tests/test_background_jobs.py backend/tests/test_reliability_controls.py -q
```

Create a manifest beside each completed database/object backup:

```bash
.venv/bin/python -m backend.app.recovery_check snapshot > backup-manifest.json
```

After restoring into an isolated environment, compare all durable database counts and HEAD every clean attachment and generated artifact:

```bash
.venv/bin/python -m backend.app.recovery_check verify \
  --manifest backup-manifest.json \
  --sample-objects 0
```

Run a read-only local load check with a test administrator account:

```bash
.venv/bin/python scripts/load_reliability.py \
  --email admin@example.com \
  --password 'test-password' \
  --requests 100 \
  --concurrency 10 \
  --min-instances 1
```

For the production-like multi-replica gate, point the same command at the load balancer and set `--min-instances 2`. The check fails if responses do not prove that at least two API instances served requests, if request IDs are missing/duplicated, if server errors occur, or if the p95 threshold is exceeded.
