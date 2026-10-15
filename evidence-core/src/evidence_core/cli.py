"""Command-line interface for demonstrations and independent verification."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .benchmark import write_benchmark
from .canonical import canonical_json
from .connectors import AzureSqlConnector, EntraIdConnector, GitHubActionsConnector, KeyVaultConnector, KubernetesAuditConnector
from .controls import ControlVersion
from .pack import create_evidence_pack, verify_evidence_pack
from .metrics import ImpactLedger
from .signing import generate_keypair, load_private_key, load_public_key
from .synthetic import healthcare_dataset


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evidence-core", description="Build and verify cryptographic evidence packs")
    commands = parser.add_subparsers(dest="command", required=True)
    key = commands.add_parser("generate-key", help="Generate an Ed25519 signing keypair")
    key.add_argument("--private", required=True)
    key.add_argument("--public", required=True)
    demo = commands.add_parser("demo", help="Create a signed pack from synthetic non-PHI events")
    demo.add_argument("--output", required=True)
    demo.add_argument("--private-key", required=True)
    demo.add_argument("--incidents", type=int, default=5)
    demo.add_argument("--noise", type=int, default=20)
    verify = commands.add_parser("verify", help="Verify a pack's content, signature, and optional trust anchor")
    verify.add_argument("pack")
    verify.add_argument("--trusted-public-key")
    benchmark = commands.add_parser("benchmark", help="Run a deterministic synthetic benchmark")
    benchmark.add_argument("--output", required=True)
    benchmark.add_argument("--incidents", type=int, default=250)
    benchmark.add_argument("--noise", type=int, default=1000)
    benchmark.add_argument("--seed", type=int, default=42)
    benchmark.add_argument("--manual-minutes", type=float)
    benchmark.add_argument("--assisted-minutes", type=float)
    benchmark.add_argument("--hourly-cost", type=float)
    benchmark.add_argument("--compute-cost", type=float)
    normalize = commands.add_parser("normalize", help="Normalize a JSON array or JSONL export")
    normalize.add_argument("--source", required=True, choices=("azure-sql", "entra-id", "azure-key-vault", "kubernetes", "github-actions"))
    normalize.add_argument("--input", required=True)
    normalize.add_argument("--output", required=True)
    ledger_add = commands.add_parser("ledger-add", help="Append an evidence-backed public impact metric")
    ledger_add.add_argument("ledger")
    ledger_add.add_argument("--metric", required=True)
    ledger_add.add_argument("--value", type=float, required=True)
    ledger_add.add_argument("--source", required=True)
    ledger_add.add_argument("--evidence-url", default="")
    ledger_verify = commands.add_parser("ledger-verify", help="Verify an impact metric ledger hash chain")
    ledger_verify.add_argument("ledger")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "generate-key":
        generate_keypair(arguments.private, arguments.public)
        print(json.dumps({"private_key": arguments.private, "public_key": arguments.public}, indent=2))
        return 0
    if arguments.command == "demo":
        dataset = healthcare_dataset(arguments.incidents, arguments.noise)
        control = ControlVersion(
            control_id="AU-6",
            framework="Synthetic healthcare reference",
            version="1.0",
            title="Audit record review and correlation",
            requirements=("Correlate audit records across defined sources.",),
            effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            metadata={"synthetic": True},
        )
        manifest = create_evidence_pack(arguments.output, dataset.records, (control,), load_private_key(arguments.private_key), "evidence-core-cli")
        print(json.dumps({"output": arguments.output, "pack_id": manifest["pack_id"], "records": len(manifest["records"])}, indent=2))
        return 0
    if arguments.command == "verify":
        trusted = load_public_key(arguments.trusted_public_key) if arguments.trusted_public_key else None
        result = verify_evidence_pack(arguments.pack, trusted)
        print(json.dumps({
            "valid": result.valid,
            "errors": result.errors,
            "pack_id": result.pack_id,
            "record_count": result.record_count,
            "signer_fingerprint": result.signer_fingerprint,
            "signer_trusted": result.signer_trusted,
            "timestamp_verified": result.timestamp_verified,
            "timestamp_trusted": result.timestamp_trusted,
        }, indent=2))
        return 0 if result.valid else 1
    if arguments.command == "normalize":
        connectors = {
            "azure-sql": AzureSqlConnector(),
            "entra-id": EntraIdConnector(),
            "azure-key-vault": KeyVaultConnector(),
            "kubernetes": KubernetesAuditConnector(),
            "github-actions": GitHubActionsConnector(),
        }
        raw = Path(arguments.input).read_text(encoding="utf-8")
        items = json.loads(raw) if raw.lstrip().startswith("[") else [json.loads(line) for line in raw.splitlines() if line.strip()]
        records = connectors[arguments.source].normalize_many(items)
        target = Path(arguments.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            for record in records:
                handle.write(canonical_json(record.as_dict()) + b"\n")
        print(json.dumps({"source": arguments.source, "input_records": len(items), "output_records": len(records), "output": str(target)}, indent=2))
        return 0
    if arguments.command == "benchmark":
        result = write_benchmark(
            arguments.output,
            incident_count=arguments.incidents,
            noise_count=arguments.noise,
            seed=arguments.seed,
            manual_minutes=arguments.manual_minutes,
            assisted_minutes=arguments.assisted_minutes,
            hourly_cost=arguments.hourly_cost,
            compute_cost=arguments.compute_cost,
        )
        print(json.dumps(result, indent=2))
        return 0
    ledger = ImpactLedger(arguments.ledger)
    if arguments.command == "ledger-add":
        print(json.dumps(ledger.append(arguments.metric, arguments.value, arguments.source, arguments.evidence_url), indent=2))
        return 0
    valid, error = ledger.verify()
    print(json.dumps({"valid": valid, "error": error, "totals": ledger.totals()}, indent=2))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
