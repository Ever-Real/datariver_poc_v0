# ruff: noqa: E501 -- fixed schema expressions retain canonical PostgreSQL text.

"""Add the append-only change-history persistence foundation.

Revision ID: 0096
Revises: 0095
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0096"
down_revision: str | Sequence[str] | None = "0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORKSPACE_RLS = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
_TABLES = ("sources", "ledger_events", "checkpoints", "cr_link_events")
_FORBIDDEN_DOCUMENT_JSONPATH = (
    '$.** ? (@.type() == "object").keyvalue() ? '
    '(@.key == "raw" || @.key == "payload" || @.key == "aspect" || '
    '@.key == "schemaMetadata" || @.key == "previousAspectValue")'
)

_SOURCE_IDENTITY_GUARD_SQL = """
CREATE FUNCTION change_history.guard_source_identity_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'change-history source evidence cannot be deleted'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.source_identity_hash IS DISTINCT FROM OLD.source_identity_hash
       OR NEW.source_generation IS DISTINCT FROM OLD.source_generation
       OR NEW.source_kind IS DISTINCT FROM OLD.source_kind
       OR NEW.provider_name IS DISTINCT FROM OLD.provider_name
       OR NEW.provider_version IS DISTINCT FROM OLD.provider_version
       OR NEW.schema_contract_hash IS DISTINCT FROM OLD.schema_contract_hash
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'change-history source identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
""".strip()

_APPEND_ONLY_GUARD_SQL = """
CREATE FUNCTION change_history.reject_append_only_mutation_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
BEGIN
    RAISE EXCEPTION 'change-history ledger and CR link history are append-only'
        USING ERRCODE = '23514';
END
$function$
""".strip()

_CHECKPOINT_GUARD_SQL = """
CREATE FUNCTION change_history.guard_checkpoint_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'change-history checkpoints cannot be deleted'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.source_id IS DISTINCT FROM OLD.source_id
       OR NEW.topic_contract IS DISTINCT FROM OLD.topic_contract
       OR NEW.source_partition IS DISTINCT FROM OLD.source_partition
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.version <> OLD.version + 1
       OR NEW.fence_epoch < OLD.fence_epoch
       OR NEW.fence_epoch > OLD.fence_epoch + 1
       OR NEW.next_offset < OLD.next_offset THEN
        RAISE EXCEPTION 'change-history checkpoint identity/version/offset is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.first_exact_offset IS NOT NULL AND (
        NEW.first_exact_offset IS DISTINCT FROM OLD.first_exact_offset
        OR NEW.first_mcl_offset IS DISTINCT FROM OLD.first_mcl_offset
    ) THEN
        RAISE EXCEPTION 'first exact checkpoint evidence is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.first_exact_offset IS NULL AND NEW.first_exact_offset IS NOT NULL AND (
        NEW.first_exact_offset <> OLD.next_offset
        OR NEW.first_mcl_offset IS DISTINCT FROM NEW.first_exact_offset
    ) THEN
        RAISE EXCEPTION 'first exact checkpoint must use the prior next offset'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.next_offset > OLD.next_offset AND (
        NEW.fence_epoch <> OLD.fence_epoch
        OR NEW.lease_owner_fingerprint IS DISTINCT FROM OLD.lease_owner_fingerprint
        OR NEW.lease_token_hash IS DISTINCT FROM OLD.lease_token_hash
        OR OLD.lease_expires_at IS NULL
        OR OLD.lease_expires_at <= clock_timestamp()
    ) THEN
        RAISE EXCEPTION 'checkpoint advancement requires the current unexpired fence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
""".strip()

_CR_LINK_CHAIN_GUARD_SQL = """
CREATE FUNCTION change_history.guard_cr_link_chain_v1()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, change_history
AS $function$
DECLARE
    prior_version integer;
    prior_hash text;
    prior_primary_cr uuid;
    prior_primary_round uuid;
BEGIN
    IF NEW.workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid THEN
        RAISE EXCEPTION 'CR link workspace context is invalid'
            USING ERRCODE = '42501';
    END IF;
    PERFORM 1
    FROM change_history.ledger_events AS ledger
    WHERE ledger.workspace_id = NEW.workspace_id
      AND ledger.id = NEW.ledger_event_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'change-history ledger event does not exist'
            USING ERRCODE = '23503';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM change_history.cr_link_events AS link
        WHERE link.workspace_id = NEW.workspace_id
          AND link.ledger_event_id = NEW.ledger_event_id
          AND link.link_version = NEW.link_version
          AND link.event_hash = NEW.event_hash
    ) THEN
        RETURN NEW;
    END IF;

    SELECT link.link_version, link.event_hash,
           link.resulting_primary_change_request_id,
           link.resulting_primary_round_id
      INTO prior_version, prior_hash, prior_primary_cr, prior_primary_round
    FROM change_history.cr_link_events AS link
    WHERE link.workspace_id = NEW.workspace_id
      AND link.ledger_event_id = NEW.ledger_event_id
    ORDER BY link.link_version DESC
    LIMIT 1;

    IF prior_version IS NULL THEN
        IF NEW.link_version <> 1 OR NEW.prior_link_hash IS NOT NULL THEN
            RAISE EXCEPTION 'first CR link event must start the hash chain'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.link_version <> prior_version + 1
          OR NEW.prior_link_hash IS DISTINCT FROM prior_hash THEN
        RAISE EXCEPTION 'CR link event has a stale version or prior hash'
            USING ERRCODE = '40001';
    END IF;

    IF NEW.action = 'SET_PRIMARY' AND (
        NEW.resulting_primary_change_request_id IS DISTINCT FROM NEW.change_request_id
        OR NEW.resulting_primary_round_id IS DISTINCT FROM NEW.change_request_round_id
    ) THEN
        RAISE EXCEPTION 'SET_PRIMARY result must identify the target CR round'
            USING ERRCODE = '23514';
    ELSIF NEW.action = 'CLEAR_PRIMARY' AND (
        prior_primary_cr IS NULL
        OR NEW.change_request_id IS DISTINCT FROM prior_primary_cr
        OR NEW.change_request_round_id IS DISTINCT FROM prior_primary_round
        OR NEW.resulting_primary_change_request_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'CLEAR_PRIMARY must clear the current primary CR round'
            USING ERRCODE = '23514';
    ELSIF NEW.action IN ('ADD_CANDIDATE', 'REMOVE_CANDIDATE') AND (
        NEW.resulting_primary_change_request_id IS DISTINCT FROM prior_primary_cr
        OR NEW.resulting_primary_round_id IS DISTINCT FROM prior_primary_round
    ) THEN
        RAISE EXCEPTION 'candidate events cannot change the current primary CR round'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
""".strip()

_CLAIM_CHECKPOINT_SQL = """
CREATE FUNCTION change_history.claim_checkpoint_v1(
    p_workspace_id uuid,
    p_source_id uuid,
    p_topic_contract text,
    p_source_partition integer,
    p_initial_next_offset bigint,
    p_owner_fingerprint text,
    p_lease_token_hash text,
    p_lease_duration_seconds integer
)
RETURNS TABLE(checkpoint_id uuid, checkpoint_version integer,
              checkpoint_fence bigint, checkpoint_next_offset bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, change_history
AS $function$
DECLARE
    checkpoint change_history.checkpoints%ROWTYPE;
    lease_now timestamptz := clock_timestamp();
BEGIN
    IF p_workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR p_source_partition < 0 OR p_initial_next_offset < 0
       OR p_owner_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_lease_token_hash !~ '^[0-9a-f]{64}$'
       OR p_lease_duration_seconds <= 0 THEN
        RAISE EXCEPTION 'invalid checkpoint lease request' USING ERRCODE = '23514';
    END IF;

    INSERT INTO change_history.checkpoints (
        id, workspace_id, source_id, topic_contract, source_partition,
        next_offset, status, fence_epoch, version, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), p_workspace_id, p_source_id, p_topic_contract,
        p_source_partition, p_initial_next_offset, 'READY', 0, 1,
        lease_now, lease_now
    )
    ON CONFLICT (workspace_id, source_id, topic_contract, source_partition) DO NOTHING;

    SELECT * INTO checkpoint
    FROM change_history.checkpoints
    WHERE workspace_id = p_workspace_id
      AND source_id = p_source_id
      AND topic_contract = p_topic_contract
      AND source_partition = p_source_partition
    FOR UPDATE;

    IF checkpoint.fence_epoch = 0 AND checkpoint.next_offset <> p_initial_next_offset THEN
        RAISE EXCEPTION 'checkpoint initialization offset conflicts with stored evidence'
            USING ERRCODE = '40001';
    END IF;
    IF checkpoint.lease_expires_at > lease_now
       AND checkpoint.lease_token_hash IS DISTINCT FROM p_lease_token_hash THEN
        RAISE EXCEPTION 'checkpoint lease is held by another owner'
            USING ERRCODE = '55P03';
    END IF;

    UPDATE change_history.checkpoints
    SET lease_owner_fingerprint = p_owner_fingerprint,
        lease_token_hash = p_lease_token_hash,
        lease_acquired_at = lease_now,
        lease_expires_at = lease_now + make_interval(secs => p_lease_duration_seconds),
        fence_epoch = checkpoint.fence_epoch + 1,
        version = checkpoint.version + 1,
        status = 'ACTIVE',
        last_error_code = NULL,
        updated_at = lease_now
    WHERE id = checkpoint.id
    RETURNING id, version, fence_epoch, next_offset
    INTO checkpoint_id, checkpoint_version, checkpoint_fence, checkpoint_next_offset;
    RETURN NEXT;
END
$function$
""".strip()

_ADVANCE_CHECKPOINT_SQL = """
CREATE FUNCTION change_history.advance_checkpoint_v1(
    p_workspace_id uuid,
    p_checkpoint_id uuid,
    p_expected_version integer,
    p_expected_fence bigint,
    p_expected_next_offset bigint,
    p_next_offset bigint,
    p_owner_fingerprint text,
    p_lease_token_hash text,
    p_last_event_identity text,
    p_source_occurred_at timestamptz,
    p_captured_at timestamptz,
    p_establish_first_exact boolean
)
RETURNS TABLE(checkpoint_id uuid, checkpoint_version integer,
              checkpoint_fence bigint, checkpoint_next_offset bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, change_history
AS $function$
DECLARE
    checkpoint change_history.checkpoints%ROWTYPE;
BEGIN
    IF p_workspace_id IS DISTINCT FROM
       NULLIF(current_setting('app.workspace_id', true), '')::uuid
       OR p_next_offset <= p_expected_next_offset
       OR p_owner_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_lease_token_hash !~ '^[0-9a-f]{64}$'
       OR p_last_event_identity !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid checkpoint advancement request' USING ERRCODE = '23514';
    END IF;

    SELECT * INTO checkpoint
    FROM change_history.checkpoints
    WHERE workspace_id = p_workspace_id AND id = p_checkpoint_id
    FOR UPDATE;
    IF NOT FOUND
       OR checkpoint.version <> p_expected_version
       OR checkpoint.fence_epoch <> p_expected_fence
       OR checkpoint.next_offset <> p_expected_next_offset
       OR checkpoint.lease_owner_fingerprint IS DISTINCT FROM p_owner_fingerprint
       OR checkpoint.lease_token_hash IS DISTINCT FROM p_lease_token_hash
       OR checkpoint.lease_expires_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'checkpoint version, offset, or lease fence is stale'
            USING ERRCODE = '40001';
    END IF;
    IF p_establish_first_exact AND checkpoint.first_exact_offset IS NOT NULL THEN
        RAISE EXCEPTION 'first exact checkpoint is already established'
            USING ERRCODE = '40001';
    END IF;

    UPDATE change_history.checkpoints
    SET first_exact_offset = CASE WHEN p_establish_first_exact
                                  THEN p_expected_next_offset ELSE first_exact_offset END,
        first_mcl_offset = CASE WHEN p_establish_first_exact
                                THEN p_expected_next_offset ELSE first_mcl_offset END,
        next_offset = p_next_offset,
        last_contiguous_event_identity = p_last_event_identity,
        last_source_occurred_at = p_source_occurred_at,
        last_captured_at = p_captured_at,
        status = 'ACTIVE',
        last_error_code = NULL,
        version = checkpoint.version + 1,
        updated_at = p_captured_at
    WHERE id = checkpoint.id
    RETURNING id, version, fence_epoch, next_offset
    INTO checkpoint_id, checkpoint_version, checkpoint_fence, checkpoint_next_offset;
    RETURN NEXT;
END
$function$
""".strip()

_GRANTS_SQL = """
DO $datariver$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        GRANT USAGE ON SCHEMA change_history TO datariver_app;
        GRANT SELECT, INSERT ON change_history.sources,
            change_history.ledger_events,
            change_history.cr_link_events TO datariver_app;
        GRANT SELECT ON change_history.checkpoints TO datariver_app;
        REVOKE UPDATE, DELETE ON change_history.sources,
            change_history.ledger_events,
            change_history.checkpoints,
            change_history.cr_link_events FROM datariver_app;
        GRANT EXECUTE ON FUNCTION change_history.claim_checkpoint_v1(
            uuid, uuid, text, integer, bigint, text, text, integer
        ) TO datariver_app;
        GRANT EXECUTE ON FUNCTION change_history.advance_checkpoint_v1(
            uuid, uuid, integer, bigint, bigint, bigint, text, text, text,
            timestamptz, timestamptz, boolean
        ) TO datariver_app;
    END IF;
END
$datariver$
""".strip()


def security_statements() -> tuple[str, ...]:
    return (
        _SOURCE_IDENTITY_GUARD_SQL,
        "CREATE TRIGGER guard_source_identity BEFORE UPDATE OR DELETE "
        "ON change_history.sources FOR EACH ROW "
        "EXECUTE FUNCTION change_history.guard_source_identity_v1()",
        _APPEND_ONLY_GUARD_SQL,
        "CREATE TRIGGER reject_append_only_mutation BEFORE UPDATE OR DELETE "
        "ON change_history.ledger_events FOR EACH ROW "
        "EXECUTE FUNCTION change_history.reject_append_only_mutation_v1()",
        _CHECKPOINT_GUARD_SQL,
        "CREATE TRIGGER guard_checkpoint BEFORE UPDATE OR DELETE "
        "ON change_history.checkpoints FOR EACH ROW "
        "EXECUTE FUNCTION change_history.guard_checkpoint_v1()",
        _CR_LINK_CHAIN_GUARD_SQL,
        "CREATE TRIGGER guard_cr_link_chain BEFORE INSERT "
        "ON change_history.cr_link_events FOR EACH ROW "
        "EXECUTE FUNCTION change_history.guard_cr_link_chain_v1()",
        "REVOKE ALL ON FUNCTION change_history.guard_cr_link_chain_v1() FROM PUBLIC",
        "CREATE TRIGGER reject_append_only_mutation BEFORE UPDATE OR DELETE "
        "ON change_history.cr_link_events FOR EACH ROW "
        "EXECUTE FUNCTION change_history.reject_append_only_mutation_v1()",
        _CLAIM_CHECKPOINT_SQL,
        _ADVANCE_CHECKPOINT_SQL,
        "REVOKE ALL ON FUNCTION change_history.claim_checkpoint_v1("
        "uuid, uuid, text, integer, bigint, text, text, integer) FROM PUBLIC",
        "REVOKE ALL ON FUNCTION change_history.advance_checkpoint_v1("
        "uuid, uuid, integer, bigint, bigint, bigint, text, text, text, "
        "timestamptz, timestamptz, boolean) FROM PUBLIC",
        _GRANTS_SQL,
    )


def _create_sources() -> None:
    op.create_table(
        "sources",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_identity_hash", sa.String(64), nullable=False),
        sa.Column("source_generation", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("provider_version", sa.String(100), nullable=False),
        sa.Column("schema_contract_hash", sa.String(64), nullable=False),
        sa.Column("capture_state", sa.String(32), nullable=False),
        sa.Column("history_available_from", sa.DateTime(timezone=True)),
        sa.Column("ledger_guarantee_from", sa.DateTime(timezone=True)),
        sa.Column("first_exact_capture_at", sa.DateTime(timezone=True)),
        sa.Column("first_timeline_checkpoint", sa.DateTime(timezone=True)),
        sa.Column("first_mcl_offsets", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("last_successful_capture_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source_identity_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_sources_identity_sha256")
        ),
        sa.CheckConstraint(
            "schema_contract_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_sources_schema_sha256")
        ),
        sa.CheckConstraint("source_generation > 0", name=op.f("ck_sources_generation_positive")),
        sa.CheckConstraint("source_kind IN ('DATAHUB')", name=op.f("ck_sources_kind_vocabulary")),
        sa.CheckConstraint(
            "capture_state IN ('DISABLED', 'READY', 'CAPTURING', 'DEGRADED_GAP', 'TARGET_RECHECK_REQUIRED', 'FAILED')",
            name=op.f("ck_sources_capture_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "char_length(provider_name) BETWEEN 1 AND 100 AND provider_name = btrim(provider_name)",
            name=op.f("ck_sources_provider_name_bounded"),
        ),
        sa.CheckConstraint(
            "char_length(provider_version) BETWEEN 1 AND 100 AND provider_version = btrim(provider_version)",
            name=op.f("ck_sources_provider_version_bounded"),
        ),
        sa.CheckConstraint(
            "first_mcl_offsets IS NULL OR (jsonb_typeof(first_mcl_offsets) = 'object' AND octet_length(first_mcl_offsets::text) <= 4096 AND NOT jsonb_path_exists(first_mcl_offsets, '$.* ? (@.type() != \"number\")') AND NOT jsonb_path_exists(first_mcl_offsets, '$.* ? (@ < 0)'))",
            name=op.f("ck_sources_first_mcl_offsets_bounded"),
        ),
        sa.CheckConstraint(
            "(ledger_guarantee_from IS NULL AND first_exact_capture_at IS NULL AND first_mcl_offsets IS NULL) OR (ledger_guarantee_from IS NOT NULL AND first_exact_capture_at IS NOT NULL AND first_mcl_offsets IS NOT NULL)",
            name=op.f("ck_sources_exact_boundary_shape"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_sources_version_positive")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="RESTRICT",
            name=op.f("fk_sources_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_sources_workspace_id")),
        sa.UniqueConstraint(
            "workspace_id",
            "source_identity_hash",
            name=op.f("uq_sources_workspace_id_source_identity_hash"),
        ),
        schema="change_history",
    )
    op.create_index(
        "ix_change_history_sources_state",
        "sources",
        ["workspace_id", "capture_state", "id"],
        schema="change_history",
    )


def _create_ledger_events() -> None:
    op.create_table(
        "ledger_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("event_identity", sa.String(64), nullable=False),
        sa.Column("source_event_identity", sa.String(64), nullable=False),
        sa.Column("normalized_change_transaction_id", sa.String(64), nullable=False),
        sa.Column("deterministic_ordinal", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("topic_contract", sa.String(255)),
        sa.Column("source_partition", sa.Integer()),
        sa.Column("source_offset", sa.BigInteger()),
        sa.Column("asset_id", sa.Uuid()),
        sa.Column("entity_urn", sa.Text(), nullable=False),
        sa.Column("entity_urn_hash", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("platform", sa.String(100)),
        sa.Column("database_name", sa.String(255)),
        sa.Column("schema_name", sa.String(255)),
        sa.Column("table_or_view_name", sa.String(500)),
        sa.Column("field_path", sa.String(1000)),
        sa.Column("normalized_entity_key", sa.String(1000), nullable=False),
        sa.Column("system_id", sa.Uuid()),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("source_aspect", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("before_hash", sa.String(64)),
        sa.Column("after_hash", sa.String(64)),
        sa.Column("actor_ref", sa.Text()),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True)),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_week_start", sa.Date()),
        sa.Column("precision", sa.String(32), nullable=False),
        sa.Column("tombstone", sa.Boolean(), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "event_identity ~ '^[0-9a-f]{64}$'", name=op.f("ck_ledger_events_identity_sha256")
        ),
        sa.CheckConstraint(
            "source_event_identity ~ '^[0-9a-f]{64}$'", name=op.f("ck_ledger_events_source_sha256")
        ),
        sa.CheckConstraint(
            "normalized_change_transaction_id ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_ledger_events_transaction_sha256"),
        ),
        sa.CheckConstraint(
            "entity_urn_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_ledger_events_entity_urn_sha256")
        ),
        sa.CheckConstraint(
            "deterministic_ordinal >= 0", name=op.f("ck_ledger_events_ordinal_nonnegative")
        ),
        sa.CheckConstraint(
            "source_kind IN ('MCL', 'TIMELINE', 'RECONCILIATION')",
            name=op.f("ck_ledger_events_source_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "(source_kind = 'MCL' AND topic_contract IS NOT NULL AND source_partition IS NOT NULL AND source_offset IS NOT NULL) OR (source_kind <> 'MCL' AND topic_contract IS NULL AND source_partition IS NULL AND source_offset IS NULL)",
            name=op.f("ck_ledger_events_source_position_shape"),
        ),
        sa.CheckConstraint(
            "source_partition IS NULL OR source_partition >= 0",
            name=op.f("ck_ledger_events_partition_nonnegative"),
        ),
        sa.CheckConstraint(
            "source_offset IS NULL OR source_offset >= 0",
            name=op.f("ck_ledger_events_offset_nonnegative"),
        ),
        sa.CheckConstraint(
            "category IN ('TECHNICAL_SCHEMA', 'DOCUMENTATION', 'TAG', 'GLOSSARY_TERM', 'OWNERSHIP')",
            name=op.f("ck_ledger_events_category_vocabulary"),
        ),
        sa.CheckConstraint(
            "(category = 'TECHNICAL_SCHEMA' AND source_aspect = 'schemaMetadata') OR (category = 'DOCUMENTATION' AND source_aspect IN ('datasetProperties', 'editableSchemaMetadata')) OR (category = 'TAG' AND source_aspect = 'globalTags') OR (category = 'GLOSSARY_TERM' AND source_aspect = 'glossaryTerms') OR (category = 'OWNERSHIP' AND source_aspect = 'ownership')",
            name=op.f("ck_ledger_events_category_aspect_allowlist"),
        ),
        sa.CheckConstraint(
            "operation IN ('CREATE', 'UPDATE', 'UPSERT', 'DELETE', 'ADD', 'REMOVE')",
            name=op.f("ck_ledger_events_operation_vocabulary"),
        ),
        sa.CheckConstraint(
            "precision IN ('EXACT_TIMELINE', 'EXACT_MCL', 'DRIFT_DETECTED', 'BACKFILLED_BEST_EFFORT', 'INITIAL_BASELINE')",
            name=op.f("ck_ledger_events_precision_vocabulary"),
        ),
        sa.CheckConstraint(
            "char_length(entity_urn) BETWEEN 1 AND 4096",
            name=op.f("ck_ledger_events_entity_urn_bounded"),
        ),
        sa.CheckConstraint(
            "char_length(normalized_entity_key) BETWEEN 1 AND 1000 AND normalized_entity_key = btrim(normalized_entity_key)",
            name=op.f("ck_ledger_events_entity_key_bounded"),
        ),
        sa.CheckConstraint(
            "before_data IS NULL OR (jsonb_typeof(before_data) = 'object' AND octet_length(before_data::text) <= 16384 "
            f"AND NOT jsonb_path_exists(before_data, '{_FORBIDDEN_DOCUMENT_JSONPATH}'))",
            name=op.f("ck_ledger_events_before_data_bounded"),
        ),
        sa.CheckConstraint(
            "after_data IS NULL OR (jsonb_typeof(after_data) = 'object' AND octet_length(after_data::text) <= 16384 "
            f"AND NOT jsonb_path_exists(after_data, '{_FORBIDDEN_DOCUMENT_JSONPATH}'))",
            name=op.f("ck_ledger_events_after_data_bounded"),
        ),
        sa.CheckConstraint(
            "before_hash IS NULL OR before_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_ledger_events_before_hash_sha256"),
        ),
        sa.CheckConstraint(
            "after_hash IS NULL OR after_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_ledger_events_after_hash_sha256"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_metadata) = 'object' AND octet_length(source_metadata::text) <= 4096 "
            "AND NOT (source_metadata ?| ARRAY['raw', 'payload', 'aspect', 'schemaMetadata', 'previousAspectValue']) "
            f"AND NOT jsonb_path_exists(source_metadata, '{_FORBIDDEN_DOCUMENT_JSONPATH}')",
            name=op.f("ck_ledger_events_source_metadata_bounded"),
        ),
        sa.CheckConstraint(
            "actor_ref IS NULL OR char_length(actor_ref) BETWEEN 1 AND 1000",
            name=op.f("ck_ledger_events_actor_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="RESTRICT",
            name=op.f("fk_ledger_events_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["change_history.sources.workspace_id", "change_history.sources.id"],
            ondelete="RESTRICT",
            name=op.f("fk_ledger_events_workspace_id_source_id_sources"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["catalog.assets_projection.workspace_id", "catalog.assets_projection.id"],
            ondelete="RESTRICT",
            name=op.f("fk_ledger_events_workspace_id_asset_id_assets_projection"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "system_id"],
            ["platform.data_systems.workspace_id", "platform.data_systems.id"],
            ondelete="RESTRICT",
            name=op.f("fk_ledger_events_workspace_id_system_id_data_systems"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_events")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_ledger_events_workspace_id")),
        sa.UniqueConstraint(
            "workspace_id",
            "event_identity",
            name=op.f("uq_ledger_events_workspace_id_event_identity"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "source_id",
            "source_event_identity",
            "deterministic_ordinal",
            name="uq_change_history_ledger_source_event_ordinal",
        ),
        schema="change_history",
    )
    op.create_index(
        "ix_change_history_ledger_keyset",
        "ledger_events",
        ["workspace_id", sa.text("source_occurred_at DESC"), sa.text("id DESC")],
        schema="change_history",
    )
    op.create_index(
        "ix_change_history_ledger_asset_history",
        "ledger_events",
        ["workspace_id", "asset_id", sa.text("source_occurred_at DESC"), sa.text("id DESC")],
        schema="change_history",
    )
    op.create_index(
        "ix_change_history_ledger_filters",
        "ledger_events",
        [
            "workspace_id",
            "category",
            "precision",
            "system_id",
            sa.text("source_occurred_at DESC"),
            sa.text("id DESC"),
        ],
        schema="change_history",
    )
    op.create_index(
        "ix_change_history_ledger_transaction",
        "ledger_events",
        ["workspace_id", "normalized_change_transaction_id", "id"],
        schema="change_history",
    )


def _create_checkpoints() -> None:
    op.create_table(
        "checkpoints",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("topic_contract", sa.String(255), nullable=False),
        sa.Column("source_partition", sa.Integer(), nullable=False),
        sa.Column("first_exact_offset", sa.BigInteger()),
        sa.Column("first_mcl_offset", sa.BigInteger()),
        sa.Column("next_offset", sa.BigInteger(), nullable=False),
        sa.Column("last_contiguous_event_identity", sa.String(64)),
        sa.Column("last_source_occurred_at", sa.DateTime(timezone=True)),
        sa.Column("last_captured_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("last_error_code", sa.String(100)),
        sa.Column("lease_owner_fingerprint", sa.String(64)),
        sa.Column("lease_token_hash", sa.String(64)),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("fence_epoch", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source_partition >= 0", name=op.f("ck_checkpoints_partition_nonnegative")
        ),
        sa.CheckConstraint("next_offset >= 0", name=op.f("ck_checkpoints_next_offset_nonnegative")),
        sa.CheckConstraint(
            "first_exact_offset IS NULL OR first_exact_offset >= 0",
            name=op.f("ck_checkpoints_first_exact_offset_nonnegative"),
        ),
        sa.CheckConstraint(
            "first_mcl_offset IS NULL OR first_mcl_offset >= 0",
            name=op.f("ck_checkpoints_first_mcl_offset_nonnegative"),
        ),
        sa.CheckConstraint(
            "first_mcl_offset IS NULL OR first_exact_offset = first_mcl_offset",
            name=op.f("ck_checkpoints_first_offset_consistent"),
        ),
        sa.CheckConstraint(
            "last_contiguous_event_identity IS NULL OR last_contiguous_event_identity ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_checkpoints_last_event_sha256"),
        ),
        sa.CheckConstraint(
            "status IN ('READY', 'ACTIVE', 'DEGRADED_GAP', 'BLOCKED', 'FAILED')",
            name=op.f("ck_checkpoints_status_vocabulary"),
        ),
        sa.CheckConstraint(
            "last_error_code IS NULL OR (char_length(last_error_code) BETWEEN 1 AND 100 AND last_error_code ~ '^[A-Z0-9_]+$')",
            name=op.f("ck_checkpoints_error_code_bounded"),
        ),
        sa.CheckConstraint("fence_epoch >= 0", name=op.f("ck_checkpoints_fence_epoch_nonnegative")),
        sa.CheckConstraint("version > 0", name=op.f("ck_checkpoints_version_positive")),
        sa.CheckConstraint(
            "(lease_owner_fingerprint IS NULL AND lease_token_hash IS NULL AND lease_acquired_at IS NULL AND lease_expires_at IS NULL) OR (lease_owner_fingerprint ~ '^[0-9a-f]{64}$' AND lease_token_hash ~ '^[0-9a-f]{64}$' AND lease_acquired_at IS NOT NULL AND lease_expires_at > lease_acquired_at)",
            name=op.f("ck_checkpoints_lease_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="RESTRICT",
            name=op.f("fk_checkpoints_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["change_history.sources.workspace_id", "change_history.sources.id"],
            ondelete="RESTRICT",
            name=op.f("fk_checkpoints_workspace_id_source_id_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkpoints")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_checkpoints_workspace_id")),
        sa.UniqueConstraint(
            "workspace_id",
            "source_id",
            "topic_contract",
            "source_partition",
            name="uq_change_history_checkpoint_partition",
        ),
        schema="change_history",
    )
    op.create_index(
        "ix_change_history_checkpoint_lease",
        "checkpoints",
        ["workspace_id", "status", "lease_expires_at", "id"],
        schema="change_history",
    )


def _create_cr_link_events() -> None:
    op.create_table(
        "cr_link_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("ledger_event_id", sa.Uuid(), nullable=False),
        sa.Column("link_version", sa.Integer(), nullable=False),
        sa.Column("link_kind", sa.String(16), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("change_request_id", sa.Uuid(), nullable=False),
        sa.Column("change_request_round_id", sa.Uuid(), nullable=False),
        sa.Column("active_result", sa.Boolean(), nullable=False),
        sa.Column("resulting_primary_change_request_id", sa.Uuid()),
        sa.Column("resulting_primary_round_id", sa.Uuid()),
        sa.Column("prior_link_hash", sa.String(64)),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("basis_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "link_version > 0", name=op.f("ck_cr_link_events_link_version_positive")
        ),
        sa.CheckConstraint(
            "link_kind IN ('PRIMARY', 'CANDIDATE')", name=op.f("ck_cr_link_events_kind_vocabulary")
        ),
        sa.CheckConstraint(
            "action IN ('SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE')",
            name=op.f("ck_cr_link_events_action_vocabulary"),
        ),
        sa.CheckConstraint(
            "(link_kind = 'PRIMARY' AND action IN ('SET_PRIMARY', 'CLEAR_PRIMARY')) OR (link_kind = 'CANDIDATE' AND action IN ('ADD_CANDIDATE', 'REMOVE_CANDIDATE'))",
            name=op.f("ck_cr_link_events_kind_action_shape"),
        ),
        sa.CheckConstraint(
            "active_result = (action IN ('SET_PRIMARY', 'ADD_CANDIDATE'))",
            name=op.f("ck_cr_link_events_active_result_shape"),
        ),
        sa.CheckConstraint(
            "(resulting_primary_change_request_id IS NULL AND resulting_primary_round_id IS NULL) OR (resulting_primary_change_request_id IS NOT NULL AND resulting_primary_round_id IS NOT NULL)",
            name=op.f("ck_cr_link_events_resulting_primary_shape"),
        ),
        sa.CheckConstraint(
            "prior_link_hash IS NULL OR prior_link_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cr_link_events_prior_hash_sha256"),
        ),
        sa.CheckConstraint(
            "event_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_cr_link_events_event_hash_sha256")
        ),
        sa.CheckConstraint(
            "policy_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_cr_link_events_policy_hash_sha256")
        ),
        sa.CheckConstraint(
            "basis_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_cr_link_events_basis_hash_sha256")
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 2000 AND reason = btrim(reason)",
            name=op.f("ck_cr_link_events_reason_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="RESTRICT",
            name=op.f("fk_cr_link_events_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "ledger_event_id"],
            ["change_history.ledger_events.workspace_id", "change_history.ledger_events.id"],
            ondelete="RESTRICT",
            name=op.f("fk_cr_link_events_workspace_id_ledger_event_id_ledger_events"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id", "change_request_round_id"],
            [
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ],
            ondelete="RESTRICT",
            name=op.f("fk_cr_link_events_target_round"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "resulting_primary_change_request_id", "resulting_primary_round_id"],
            [
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ],
            ondelete="RESTRICT",
            name=op.f("fk_cr_link_events_resulting_primary_round"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            ondelete="RESTRICT",
            name=op.f("fk_cr_link_events_workspace_id_actor_id_workspace_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cr_link_events")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_cr_link_events_workspace_id")),
        sa.UniqueConstraint(
            "workspace_id",
            "ledger_event_id",
            "link_version",
            name=op.f("uq_cr_link_events_workspace_id_ledger_event_id_link_version"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "ledger_event_id",
            "event_hash",
            name=op.f("uq_cr_link_events_workspace_id_ledger_event_id_event_hash"),
        ),
        schema="change_history",
    )
    op.create_index(
        "ix_change_history_cr_links_current",
        "cr_link_events",
        ["workspace_id", "ledger_event_id", sa.text("link_version DESC")],
        schema="change_history",
    )
    op.create_index(
        "ix_change_history_cr_links_request",
        "cr_link_events",
        [
            "workspace_id",
            "change_request_id",
            "change_request_round_id",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        schema="change_history",
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS change_history")
    _create_sources()
    _create_ledger_events()
    _create_checkpoints()
    _create_cr_link_events()
    for table in _TABLES:
        op.execute(f"ALTER TABLE change_history.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE change_history.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY workspace_isolation ON change_history.{table} "
            f"USING (workspace_id = {_WORKSPACE_RLS}) "
            f"WITH CHECK (workspace_id = {_WORKSPACE_RLS})"
        )
    for statement in security_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM change_history.sources LIMIT 1)
               OR EXISTS (SELECT 1 FROM change_history.ledger_events LIMIT 1)
               OR EXISTS (SELECT 1 FROM change_history.checkpoints LIMIT 1)
               OR EXISTS (SELECT 1 FROM change_history.cr_link_events LIMIT 1) THEN
                RAISE EXCEPTION
                    '0096 downgrade refuses to delete change-history evidence';
            END IF;
        END
        $datariver$
        """
    )
    op.execute(
        "DROP FUNCTION change_history.advance_checkpoint_v1(uuid, uuid, integer, bigint, bigint, bigint, text, text, text, timestamptz, timestamptz, boolean)"
    )
    op.execute(
        "DROP FUNCTION change_history.claim_checkpoint_v1(uuid, uuid, text, integer, bigint, text, text, integer)"
    )
    op.drop_table("cr_link_events", schema="change_history")
    op.drop_table("checkpoints", schema="change_history")
    op.drop_table("ledger_events", schema="change_history")
    op.drop_table("sources", schema="change_history")
    op.execute("DROP FUNCTION change_history.guard_cr_link_chain_v1()")
    op.execute("DROP FUNCTION change_history.guard_checkpoint_v1()")
    op.execute("DROP FUNCTION change_history.reject_append_only_mutation_v1()")
    op.execute("DROP FUNCTION change_history.guard_source_identity_v1()")
    op.execute("DROP SCHEMA change_history")
