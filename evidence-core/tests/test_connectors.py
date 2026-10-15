from evidence_core.connectors import AzureSqlConnector, EntraIdConnector, GitHubActionsConnector, KeyVaultConnector, KubernetesAuditConnector


def test_azure_sql_normalizes_audit_row():
    record = AzureSqlConnector().normalize({"event_time": "2026-01-01T10:00:00Z", "action_name": "SELECT", "database_name": "clinical", "server_principal_name": "auditor"})
    assert record.source == "azure-sql"
    assert record.metadata["identity"] == "auditor"
    assert record.evidence_id.startswith("azure-sql-")


def test_entra_normalizes_sign_in():
    record = EntraIdConnector().normalize({"id": "e1", "createdDateTime": "2026-01-01T10:00:00Z", "userPrincipalName": "user@example.invalid", "ipAddress": "192.0.2.1"})
    assert record.evidence_id == "e1"
    assert record.metadata["identity"] == "user@example.invalid"


def test_key_vault_normalizes_diagnostic_event():
    record = KeyVaultConnector().normalize({"time": "2026-01-01T10:00:00Z", "operationName": "SecretGet", "resourceId": "/vaults/demo", "properties": {"clientIpAddress": "192.0.2.2"}})
    assert record.kind == "SecretGet"
    assert record.metadata["resource"] == "/vaults/demo"


def test_kubernetes_normalizes_audit_event():
    record = KubernetesAuditConnector().normalize({"auditID": "k1", "stageTimestamp": "2026-01-01T10:00:00Z", "verb": "create", "user": {"username": "system:serviceaccount:demo"}, "objectRef": {"namespace": "demo", "resource": "pods", "name": "api"}})
    assert record.kind == "kubernetes.create"
    assert record.metadata["resource"] == "demo/pods/api"


def test_github_actions_normalizes_workflow_run():
    record = GitHubActionsConnector().normalize({"id": 42, "event": "push", "run_started_at": "2026-01-01T10:00:00Z", "actor": {"login": "octocat"}, "repository": {"full_name": "example/repo"}})
    assert record.evidence_id == "42"
    assert record.metadata["workflow_run_id"] == "42"
