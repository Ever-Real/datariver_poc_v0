from __future__ import annotations

from pathlib import Path

from datariver.infrastructure.db.outbox import SqlOutboxRelayStore


def test_relay_store_exposes_no_destructive_retention_operation() -> None:
    assert not hasattr(SqlOutboxRelayStore, "prune_completed")


def test_relay_role_cannot_delete_retained_event_evidence() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    relay_block = generator.split("rolname = 'datariver_relay'", maxsplit=1)[1].split(
        "END IF;", maxsplit=1
    )[0]
    migration = (root / "backend/alembic/versions/0006_disable_unsafe_event_pruning.py").read_text(
        encoding="utf-8"
    )

    assert "DELETE" not in relay_block
    assert "REVOKE DELETE ON integration.outbox_events FROM datariver_relay" in migration
    assert "REVOKE DELETE ON integration.inbox_messages FROM datariver_relay" in migration
