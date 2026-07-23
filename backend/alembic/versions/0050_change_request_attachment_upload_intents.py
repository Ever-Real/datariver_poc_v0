"""Add durable change-request attachment upload intents.

Revision ID: 0050
Revises: 0049
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "change_request_attachment_upload_intents"
_QUALIFIED_TABLE = f"governance.{_TABLE}"


def _table_exists() -> bool:
    return (
        op.get_bind()
        .execute(sa.text("SELECT to_regclass(:table_name)"), {"table_name": _QUALIFIED_TABLE})
        .scalar_one()
        is not None
    )


def _create_table() -> None:
    op.create_table(
        _TABLE,
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("change_request_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("original_name", sa.String(length=500), nullable=False),
        sa.Column("serial_number", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("expected_size_bytes", sa.Integer(), nullable=False),
        sa.Column("expected_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("provider_checksum", sa.String(length=255), nullable=True),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
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
            "kind IN ('REQUEST', 'TEST')",
            name=op.f("ck_cr_attachment_intent_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('STARTED', 'STORED', 'FINALIZED', 'FAILED')",
            name=op.f("ck_cr_attachment_intent_state"),
        ),
        sa.CheckConstraint(
            "serial_number BETWEEN 1 AND 999999",
            name=op.f("ck_cr_attachment_intent_serial"),
        ),
        sa.CheckConstraint(
            "expected_size_bytes BETWEEN 1 AND 10485760",
            name=op.f("ck_cr_attachment_intent_expected_size"),
        ),
        sa.CheckConstraint(
            "expected_content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cr_attachment_intent_expected_sha"),
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes BETWEEN 1 AND 10485760",
            name=op.f("ck_cr_attachment_intent_size"),
        ),
        sa.CheckConstraint(
            "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_cr_attachment_intent_sha"),
        ),
        sa.CheckConstraint(
            "(state = 'STARTED' AND size_bytes IS NULL AND content_sha256 IS NULL "
            "AND provider_checksum IS NULL AND stored_at IS NULL AND finalized_at IS NULL "
            "AND failed_at IS NULL AND failure_code IS NULL) OR "
            "(state = 'STORED' AND size_bytes = expected_size_bytes "
            "AND content_sha256 = expected_content_sha256 AND stored_at IS NOT NULL "
            "AND finalized_at IS NULL AND failed_at IS NULL AND failure_code IS NULL) OR "
            "(state = 'FINALIZED' AND size_bytes = expected_size_bytes "
            "AND content_sha256 = expected_content_sha256 AND stored_at IS NOT NULL "
            "AND finalized_at IS NOT NULL AND failed_at IS NULL AND failure_code IS NULL) OR "
            "(state = 'FAILED' AND size_bytes IS NULL AND content_sha256 IS NULL "
            "AND provider_checksum IS NULL AND stored_at IS NULL AND finalized_at IS NULL "
            "AND failed_at IS NOT NULL AND failure_code IS NOT NULL)",
            name=op.f("ck_cr_attachment_intent_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id"],
            ["governance.change_requests.workspace_id", "governance.change_requests.id"],
            name="fk_change_request_attachment_upload_intents_request",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id", "round_id"],
            [
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ],
            name="fk_change_request_attachment_upload_intents_round",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "uploaded_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_change_request_attachment_upload_intents_uploader",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_change_request_attachment_upload_intents",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_change_request_attachment_upload_intents_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "bucket",
            "object_key",
            name="uq_change_request_attachment_upload_intent_object",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "kind",
            "original_name",
            "serial_number",
            name="uq_change_request_attachment_upload_intent_serial",
        ),
        schema="governance",
    )
    op.create_index(
        "ix_change_request_attachment_upload_intents_reconcile",
        _TABLE,
        ["state", "updated_at", "id"],
        schema="governance",
    )
    op.create_index(
        "ix_change_request_attachment_upload_intents_request",
        _TABLE,
        ["workspace_id", "change_request_id"],
        schema="governance",
    )


def _install_security() -> None:
    op.execute(
        "ALTER TABLE governance.change_request_attachment_upload_intents "
        "ALTER COLUMN state DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE governance.change_request_attachment_upload_intents "
        "ALTER COLUMN version DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE governance.change_request_attachment_upload_intents ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE governance.change_request_attachment_upload_intents FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS workspace_isolation "
        "ON governance.change_request_attachment_upload_intents"
    )
    op.execute(
        """
        CREATE POLICY workspace_isolation
        ON governance.change_request_attachment_upload_intents
        USING (
            workspace_id =
                NULLIF(pg_catalog.current_setting('app.workspace_id', true), '')::uuid
        )
        WITH CHECK (
            workspace_id =
                NULLIF(pg_catalog.current_setting('app.workspace_id', true), '')::uuid
        )
        """
    )
    op.execute(
        "DROP POLICY IF EXISTS attachment_upload_intent_subject "
        "ON governance.change_request_attachment_upload_intents"
    )
    op.execute(
        """
        CREATE POLICY attachment_upload_intent_subject
        ON governance.change_request_attachment_upload_intents
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_user <> 'datariver_app'
            OR uploaded_by =
                NULLIF(pg_catalog.current_setting('app.subject_id', true), '')::uuid
        )
        WITH CHECK (
            current_user <> 'datariver_app'
            OR uploaded_by =
                NULLIF(pg_catalog.current_setting('app.subject_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.guard_attachment_upload_intent()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'STARTED'
                   OR NEW.version <> 1
                   OR NEW.created_at > clock_timestamp() + interval '30 seconds'
                   OR NEW.created_at < clock_timestamp() - interval '30 seconds'
                   OR NEW.updated_at < NEW.created_at
                   OR NEW.updated_at > clock_timestamp() + interval '30 seconds' THEN
                    RAISE EXCEPTION
                        'attachment upload intent must begin with a current STARTED fence';
                END IF;
                RETURN NEW;
            END IF;
            IF ROW(
                NEW.workspace_id,
                NEW.change_request_id,
                NEW.round_id,
                NEW.kind,
                NEW.original_name,
                NEW.serial_number,
                NEW.bucket,
                NEW.object_key,
                NEW.content_type,
                NEW.expected_size_bytes,
                NEW.expected_content_sha256,
                NEW.uploaded_by,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.workspace_id,
                OLD.change_request_id,
                OLD.round_id,
                OLD.kind,
                OLD.original_name,
                OLD.serial_number,
                OLD.bucket,
                OLD.object_key,
                OLD.content_type,
                OLD.expected_size_bytes,
                OLD.expected_content_sha256,
                OLD.uploaded_by,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'attachment upload intent identity is immutable';
            END IF;

            IF OLD.state = NEW.state THEN
                IF ROW(
                    NEW.workspace_id,
                    NEW.change_request_id,
                    NEW.round_id,
                    NEW.kind,
                    NEW.original_name,
                    NEW.serial_number,
                    NEW.bucket,
                    NEW.object_key,
                    NEW.content_type,
                    NEW.expected_size_bytes,
                    NEW.expected_content_sha256,
                    NEW.state,
                    NEW.size_bytes,
                    NEW.content_sha256,
                    NEW.provider_checksum,
                    NEW.uploaded_by,
                    NEW.stored_at,
                    NEW.finalized_at,
                    NEW.failed_at,
                    NEW.failure_code,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.workspace_id,
                    OLD.change_request_id,
                    OLD.round_id,
                    OLD.kind,
                    OLD.original_name,
                    OLD.serial_number,
                    OLD.bucket,
                    OLD.object_key,
                    OLD.content_type,
                    OLD.expected_size_bytes,
                    OLD.expected_content_sha256,
                    OLD.state,
                    OLD.size_bytes,
                    OLD.content_sha256,
                    OLD.provider_checksum,
                    OLD.uploaded_by,
                    OLD.stored_at,
                    OLD.finalized_at,
                    OLD.failed_at,
                    OLD.failure_code,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION
                        'same-state attachment reconciliation may only advance its retry fence';
                END IF;
            ELSIF NOT (
                (OLD.state = 'STARTED' AND NEW.state IN ('STORED', 'FAILED'))
                OR (OLD.state = 'STORED' AND NEW.state = 'FINALIZED')
            ) THEN
                RAISE EXCEPTION 'attachment upload intent state transition is invalid';
            END IF;
            IF NEW.version <> OLD.version + 1
               OR NEW.updated_at < OLD.updated_at
               OR NEW.updated_at > clock_timestamp() + interval '30 seconds' THEN
                RAISE EXCEPTION 'attachment upload intent version/time fence is invalid';
            END IF;
            IF NEW.state = 'FINALIZED' AND NOT EXISTS (
                SELECT 1
                FROM governance.change_request_attachments AS attachment
                WHERE attachment.id = NEW.id
                  AND attachment.workspace_id = NEW.workspace_id
                  AND attachment.change_request_id = NEW.change_request_id
                  AND attachment.round_id = NEW.round_id
                  AND attachment.kind = NEW.kind
                  AND attachment.original_name = NEW.original_name
                  AND attachment.serial_number = NEW.serial_number
                  AND attachment.bucket = NEW.bucket
                  AND attachment.object_key = NEW.object_key
                  AND attachment.content_type = NEW.content_type
                  AND attachment.size_bytes = NEW.size_bytes
                  AND attachment.content_sha256 = NEW.content_sha256
                  AND attachment.uploaded_by = NEW.uploaded_by
            ) THEN
                RAISE EXCEPTION
                    'finalized attachment row does not match its stored upload intent';
            END IF;
            RETURN NEW;
        END
        $function$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS guard_attachment_upload_intent "
        "ON governance.change_request_attachment_upload_intents"
    )
    op.execute(
        """
        CREATE TRIGGER guard_attachment_upload_intent
        BEFORE INSERT OR UPDATE ON governance.change_request_attachment_upload_intents
        FOR EACH ROW
        EXECUTE FUNCTION governance.guard_attachment_upload_intent()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.guard_change_request_attachment_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM governance.change_request_attachment_upload_intents AS intent
                WHERE intent.id = NEW.id
                  AND intent.workspace_id = NEW.workspace_id
                  AND intent.change_request_id = NEW.change_request_id
                  AND intent.round_id = NEW.round_id
                  AND intent.kind = NEW.kind
                  AND intent.original_name = NEW.original_name
                  AND intent.serial_number = NEW.serial_number
                  AND intent.bucket = NEW.bucket
                  AND intent.object_key = NEW.object_key
                  AND intent.content_type = NEW.content_type
                  AND intent.expected_size_bytes = NEW.size_bytes
                  AND intent.expected_content_sha256 = NEW.content_sha256
                  AND intent.size_bytes = NEW.size_bytes
                  AND intent.content_sha256 = NEW.content_sha256
                  AND intent.uploaded_by = NEW.uploaded_by
                  AND intent.state = 'STORED'
            ) THEN
                RAISE EXCEPTION
                    'attachment insert requires matching STORED upload intent';
            END IF;
            RETURN NEW;
        END
        $function$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS guard_change_request_attachment_insert "
        "ON governance.change_request_attachments"
    )
    op.execute(
        """
        CREATE TRIGGER guard_change_request_attachment_insert
        BEFORE INSERT ON governance.change_request_attachments
        FOR EACH ROW
        EXECUTE FUNCTION governance.guard_change_request_attachment_insert()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.claim_attachment_upload_reconciliation(
            p_before_or_at timestamptz
        )
        RETURNS SETOF governance.change_request_attachment_upload_intents
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, governance
        AS $function$
        DECLARE
            claimed_at timestamptz := clock_timestamp();
        BEGIN
            RETURN QUERY
            WITH candidate AS (
                SELECT intent.workspace_id, intent.id
                FROM governance.change_request_attachment_upload_intents AS intent
                WHERE intent.state = 'STARTED'
                  AND intent.updated_at <= p_before_or_at
                ORDER BY intent.updated_at, intent.id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE governance.change_request_attachment_upload_intents AS intent
            SET updated_at = claimed_at,
                version = intent.version + 1
            FROM candidate
            WHERE intent.workspace_id = candidate.workspace_id
              AND intent.id = candidate.id
              AND intent.state = 'STARTED'
              AND intent.updated_at <= p_before_or_at
            RETURNING intent.*;
        END
        $function$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.attest_attachment_upload_object(
            p_workspace_id uuid,
            p_attachment_id uuid,
            p_size_bytes integer,
            p_content_sha256 text,
            p_provider_checksum text
        )
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, governance
        AS $function$
        DECLARE
            intent governance.change_request_attachment_upload_intents%ROWTYPE;
            observed_at timestamptz := clock_timestamp();
        BEGIN
            SELECT *
            INTO intent
            FROM governance.change_request_attachment_upload_intents
            WHERE workspace_id = p_workspace_id
              AND id = p_attachment_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'attachment upload intent does not exist';
            END IF;
            IF intent.state IN ('STORED', 'FINALIZED') THEN
                IF intent.size_bytes IS DISTINCT FROM p_size_bytes
                   OR intent.content_sha256 IS DISTINCT FROM p_content_sha256
                   OR intent.provider_checksum IS DISTINCT FROM p_provider_checksum THEN
                    RAISE EXCEPTION 'attachment provider evidence conflicts with prior attestation';
                END IF;
                RETURN;
            END IF;
            IF intent.state <> 'STARTED' THEN
                RAISE EXCEPTION 'attachment upload intent is not attestable';
            END IF;
            IF p_size_bytes IS DISTINCT FROM intent.expected_size_bytes
               OR p_content_sha256 IS DISTINCT FROM intent.expected_content_sha256
               OR p_content_sha256 !~ '^[0-9a-f]{64}$'
               OR length(trim(COALESCE(p_provider_checksum, ''))) NOT BETWEEN 1 AND 255 THEN
                RAISE EXCEPTION 'attachment provider evidence does not match precommit';
            END IF;
            IF intent.created_at > observed_at THEN
                RAISE EXCEPTION 'attachment provider observation time is not monotonic';
            END IF;
            UPDATE governance.change_request_attachment_upload_intents
            SET state = 'STORED',
                size_bytes = p_size_bytes,
                content_sha256 = p_content_sha256,
                provider_checksum = p_provider_checksum,
                stored_at = observed_at,
                updated_at = observed_at,
                version = version + 1
            WHERE workspace_id = p_workspace_id
              AND id = p_attachment_id;
        END
        $function$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.defer_attachment_upload_reconciliation(
            p_workspace_id uuid,
            p_attachment_id uuid
        )
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, governance
        AS $function$
        BEGIN
            UPDATE governance.change_request_attachment_upload_intents
            SET updated_at = clock_timestamp(),
                version = version + 1
            WHERE workspace_id = p_workspace_id
              AND id = p_attachment_id
              AND state = 'STARTED';
        END
        $function$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.fail_attachment_upload_intent(
            p_workspace_id uuid,
            p_attachment_id uuid,
            p_failure_code text
        )
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, governance
        AS $function$
        DECLARE
            actor_id uuid :=
                NULLIF(pg_catalog.current_setting('app.subject_id', true), '')::uuid;
            contextual_workspace_id uuid :=
                NULLIF(pg_catalog.current_setting('app.workspace_id', true), '')::uuid;
            failed_time timestamptz := clock_timestamp();
        BEGIN
            IF contextual_workspace_id IS DISTINCT FROM p_workspace_id
               OR actor_id IS NULL
               OR p_failure_code <> 'OBJECT_KEY_ALREADY_EXISTS' THEN
                RAISE EXCEPTION 'attachment create rejection context is invalid';
            END IF;
            UPDATE governance.change_request_attachment_upload_intents
            SET state = 'FAILED',
                failed_at = failed_time,
                failure_code = p_failure_code,
                updated_at = failed_time,
                version = version + 1
            WHERE workspace_id = p_workspace_id
              AND id = p_attachment_id
              AND uploaded_by = actor_id
              AND state = 'STARTED';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'attachment upload intent is not rejectable';
            END IF;
        END
        $function$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.finalize_attachment_upload_intent(
            p_workspace_id uuid,
            p_attachment_id uuid,
            p_expected_change_request_version integer
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, governance, iam, platform, catalog
        AS $function$
        DECLARE
            intent governance.change_request_attachment_upload_intents%ROWTYPE;
            request governance.change_requests%ROWTYPE;
            actor_id uuid :=
                NULLIF(pg_catalog.current_setting('app.subject_id', true), '')::uuid;
            contextual_workspace_id uuid :=
                NULLIF(pg_catalog.current_setting('app.workspace_id', true), '')::uuid;
            action_name text;
            finalized_time timestamptz := clock_timestamp();
        BEGIN
            IF contextual_workspace_id IS DISTINCT FROM p_workspace_id OR actor_id IS NULL THEN
                RAISE EXCEPTION 'attachment finalization context is invalid';
            END IF;
            SELECT *
            INTO intent
            FROM governance.change_request_attachment_upload_intents
            WHERE workspace_id = p_workspace_id
              AND id = p_attachment_id
              AND uploaded_by = actor_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'attachment upload intent does not exist';
            END IF;
            IF intent.state = 'FINALIZED' THEN
                IF EXISTS (
                    SELECT 1
                    FROM governance.change_request_attachments AS attachment
                    WHERE attachment.workspace_id = intent.workspace_id
                      AND attachment.id = intent.id
                      AND attachment.object_key = intent.object_key
                      AND attachment.content_sha256 = intent.content_sha256
                ) THEN
                    RETURN intent.id;
                END IF;
                RAISE EXCEPTION 'finalized attachment evidence is inconsistent';
            END IF;
            IF intent.state <> 'STORED'
               OR intent.created_at > intent.stored_at
               OR intent.stored_at > finalized_time THEN
                RAISE EXCEPTION 'attachment upload intent is not ready to finalize';
            END IF;
            SELECT *
            INTO request
            FROM governance.change_requests
            WHERE workspace_id = p_workspace_id
              AND id = intent.change_request_id
            FOR UPDATE;
            IF NOT FOUND
               OR request.version IS DISTINCT FROM p_expected_change_request_version
               OR request.current_round_id IS DISTINCT FROM intent.round_id
               OR request.updated_at > finalized_time THEN
                RAISE EXCEPTION 'attachment change-request authorization is stale';
            END IF;
            action_name := CASE intent.kind
                WHEN 'TEST' THEN 'change.review'
                ELSE 'change.edit'
            END;
            IF (intent.kind = 'TEST' AND request.state <> 'TESTING')
               OR (
                   intent.kind = 'REQUEST'
                   AND request.state NOT IN ('REGISTERED', 'CHANGES_REQUESTED')
               ) THEN
                RAISE EXCEPTION 'attachment change-request state is not authorized';
            END IF;
            PERFORM 1
            FROM iam.workspace_memberships AS membership
            JOIN iam.subjects AS subject
              ON subject.id = membership.subject_id
            JOIN platform.workspaces AS workspace
              ON workspace.id = membership.workspace_id
            WHERE membership.workspace_id = p_workspace_id
              AND membership.subject_id = actor_id
              AND workspace.status = 'ACTIVE'
              AND subject.active IS TRUE
              AND membership.active IS TRUE
              AND (
                  membership.access_expires_at IS NULL
                  OR membership.access_expires_at > finalized_time
              )
              AND membership.clearance >= GREATEST(
                  request.classification,
                  COALESCE(
                      (
                          SELECT max(item.target_classification)
                          FROM governance.change_request_items AS item
                          WHERE item.workspace_id = p_workspace_id
                            AND item.change_request_id = request.id
                      ),
                      0
                  )
              )
              AND COALESCE(
                  membership.attributes -> 'allowed_actions',
                  '[]'::jsonb
              ) ? action_name
              AND NOT (
                  COALESCE(
                      membership.attributes -> 'denied_actions',
                      '[]'::jsonb
                  ) ? action_name
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM governance.change_request_items AS item
                  WHERE item.workspace_id = p_workspace_id
                    AND item.change_request_id = request.id
                    AND COALESCE(item.routing_system_id, item.target_system_id) IS NOT NULL
                    AND NOT (
                        COALESCE(
                            membership.attributes -> 'allowed_system_ids',
                            '[]'::jsonb
                        ) ? COALESCE(
                            item.routing_system_id,
                            item.target_system_id
                        )::text
                    )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM governance.change_request_items AS item
                  WHERE item.workspace_id = p_workspace_id
                    AND item.change_request_id = request.id
                    AND item.target_domain_id IS NOT NULL
                    AND NOT (
                        COALESCE(
                            membership.attributes -> 'allowed_domain_ids',
                            '[]'::jsonb
                        ) ? item.target_domain_id::text
                    )
              )
            FOR UPDATE OF membership, subject, workspace;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'attachment current actor authorization is invalid';
            END IF;
            IF intent.kind = 'TEST' AND NOT EXISTS (
                SELECT 1
                FROM platform.system_assignees AS assignee
                JOIN governance.change_request_items AS item
                  ON item.workspace_id = assignee.workspace_id
                 AND COALESCE(item.routing_system_id, item.target_system_id) =
                     assignee.system_id
                WHERE item.workspace_id = p_workspace_id
                  AND item.change_request_id = request.id
                  AND assignee.subject_id = actor_id
                  AND assignee.responsibility = 'DEVELOPER'
                  AND assignee.active IS TRUE
            ) THEN
                RAISE EXCEPTION 'attachment developer assignment is not current';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM governance.change_request_items AS item
                LEFT JOIN catalog.assets_projection AS asset
                  ON asset.workspace_id = item.workspace_id
                 AND asset.id = item.target_asset_id
                WHERE item.workspace_id = p_workspace_id
                  AND item.change_request_id = request.id
                  AND item.target_asset_id IS NOT NULL
                  AND (
                      asset.id IS NULL
                      OR asset.external_urn IS DISTINCT FROM item.target_ref
                      OR asset.asset_type IS DISTINCT FROM item.target_asset_type
                      OR asset.system_id IS DISTINCT FROM item.target_system_id
                      OR asset.domain_id IS DISTINCT FROM item.target_domain_id
                      OR asset.owner_department_id
                          IS DISTINCT FROM item.target_owner_department_id
                      OR asset.classification IS DISTINCT FROM item.target_classification
                      OR asset.lifecycle IS DISTINCT FROM item.target_lifecycle
                  )
            ) THEN
                RAISE EXCEPTION 'attachment catalog target binding is stale';
            END IF;
            INSERT INTO governance.change_request_attachments (
                id,
                workspace_id,
                change_request_id,
                round_id,
                kind,
                original_name,
                serial_number,
                bucket,
                object_key,
                content_type,
                size_bytes,
                content_sha256,
                uploaded_by,
                created_at,
                updated_at
            ) VALUES (
                intent.id,
                intent.workspace_id,
                intent.change_request_id,
                intent.round_id,
                intent.kind,
                intent.original_name,
                intent.serial_number,
                intent.bucket,
                intent.object_key,
                intent.content_type,
                intent.size_bytes,
                intent.content_sha256,
                intent.uploaded_by,
                finalized_time,
                finalized_time
            );
            UPDATE governance.change_request_attachment_upload_intents
            SET state = 'FINALIZED',
                finalized_at = finalized_time,
                updated_at = finalized_time,
                version = version + 1
            WHERE workspace_id = p_workspace_id
              AND id = p_attachment_id;
            RETURN p_attachment_id;
        END
        $function$;
        """
    )
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'datariver_app') THEN
                REVOKE ALL PRIVILEGES
                    ON governance.change_request_attachment_upload_intents
                    FROM datariver_app;
                REVOKE INSERT
                    ON governance.change_request_attachments
                    FROM datariver_app;
                GRANT SELECT, INSERT
                    ON governance.change_request_attachment_upload_intents TO datariver_app;
                GRANT EXECUTE ON FUNCTION
                    governance.fail_attachment_upload_intent(uuid, uuid, text)
                    TO datariver_app;
                GRANT EXECUTE ON FUNCTION
                    governance.finalize_attachment_upload_intent(uuid, uuid, integer)
                    TO datariver_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'datariver_upload') THEN
                REVOKE ALL PRIVILEGES
                    ON governance.change_request_attachment_upload_intents
                    FROM datariver_upload;
                REVOKE ALL PRIVILEGES
                    ON governance.change_request_attachments
                    FROM datariver_upload;
                GRANT USAGE ON SCHEMA governance TO datariver_upload;
                GRANT EXECUTE ON FUNCTION
                    governance.claim_attachment_upload_reconciliation(timestamptz)
                    TO datariver_upload;
                GRANT EXECUTE ON FUNCTION
                    governance.attest_attachment_upload_object(uuid, uuid, integer, text, text)
                    TO datariver_upload;
                GRANT EXECUTE ON FUNCTION
                    governance.defer_attachment_upload_reconciliation(uuid, uuid)
                    TO datariver_upload;
            END IF;
        END
        $datariver$;
        """
    )
    for signature in (
        "governance.claim_attachment_upload_reconciliation(timestamptz)",
        "governance.attest_attachment_upload_object(uuid, uuid, integer, text, text)",
        "governance.defer_attachment_upload_reconciliation(uuid, uuid)",
        "governance.fail_attachment_upload_intent(uuid, uuid, text)",
        "governance.finalize_attachment_upload_intent(uuid, uuid, integer)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")


def _assert_contract() -> None:
    op.execute(
        """
        DO $datariver$
        DECLARE
            actual_column_contract text[];
            expected_column_contract constant text[] := ARRAY[
                'bucket:character varying(255):true:false',
                'change_request_id:uuid:true:false',
                'content_sha256:character varying(64):false:false',
                'content_type:character varying(255):true:false',
                'created_at:timestamp with time zone:true:true',
                'expected_content_sha256:character varying(64):true:false',
                'expected_size_bytes:integer:true:false',
                'failed_at:timestamp with time zone:false:false',
                'failure_code:character varying(100):false:false',
                'finalized_at:timestamp with time zone:false:false',
                'id:uuid:true:false',
                'kind:character varying(16):true:false',
                'object_key:text:true:false',
                'original_name:character varying(500):true:false',
                'provider_checksum:character varying(255):false:false',
                'round_id:uuid:true:false',
                'serial_number:integer:true:false',
                'size_bytes:integer:false:false',
                'state:character varying(16):true:false',
                'stored_at:timestamp with time zone:false:false',
                'updated_at:timestamp with time zone:true:true',
                'uploaded_by:uuid:true:false',
                'version:integer:true:false',
                'workspace_id:uuid:true:false'
            ];
            expected_constraints constant text[] := ARRAY[
                'ck_cr_attachment_intent_expected_sha:eb8b81b6fdf8ca5df026d7200e368123',
                'ck_cr_attachment_intent_expected_size:9aa13e2c6ec7540907e0bc5857bd91dc',
                'ck_cr_attachment_intent_kind:45044c4c3ee6e9c7434dc4a932584f6a',
                'ck_cr_attachment_intent_serial:b9f119f84a96c0b3502ae99608c14ac4',
                'ck_cr_attachment_intent_sha:56083cdf51225447a95eabe3f7067446',
                'ck_cr_attachment_intent_shape:e3fb13d7b2c513ba0428697f09e5ddde',
                'ck_cr_attachment_intent_size:28581f7c12f6d147319f529084b18105',
                'ck_cr_attachment_intent_state:13fbec7f2232c8b317d9a7994a587baf',
                'fk_change_request_attachment_upload_intents_request:'
                    'd7c3ff5f1dabf535513853c669571014',
                'fk_change_request_attachment_upload_intents_round:'
                    'd5e31c4e0dfaa07695112bca9b7c91f2',
                'fk_change_request_attachment_upload_intents_uploader:'
                    'e797b4ad3c2a3e89229e8840cd4bd70f',
                'pk_change_request_attachment_upload_intents:'
                    '4c6419b3704337bbfe50f018842a9ad3',
                'uq_change_request_attachment_upload_intent_object:'
                    '18cbbd00265352d79af729fbe6ed704b',
                'uq_change_request_attachment_upload_intent_serial:'
                    '20f2fbd5b02f68541d42f91b9d40bf86',
                'uq_change_request_attachment_upload_intents_workspace_id_id:'
                    'b45cc43f27c80ddc77c3503eeaeb2729'
            ];
            actual_constraints text[];
            actual_indexes text[];
            expected_indexes constant text[] := ARRAY[
                'ix_change_request_attachment_upload_intents_reconcile:'
                    'false:false:btree:state,updated_at,id',
                'ix_change_request_attachment_upload_intents_request:'
                    'false:false:btree:workspace_id,change_request_id',
                'pk_change_request_attachment_upload_intents:'
                    'true:true:btree:id',
                'uq_change_request_attachment_upload_intent_object:'
                    'true:false:btree:bucket,object_key',
                'uq_change_request_attachment_upload_intent_serial:'
                    'true:false:btree:workspace_id,change_request_id,kind,'
                    'original_name,serial_number',
                'uq_change_request_attachment_upload_intents_workspace_id_id:'
                    'true:false:btree:workspace_id,id'
            ];
            extra_update_columns text[];
        BEGIN
            SELECT pg_catalog.array_agg(
                attname::text || ':' ||
                pg_catalog.format_type(atttypid, atttypmod) || ':' ||
                attnotnull::text || ':' ||
                atthasdef::text
                ORDER BY attname
            )
            INTO actual_column_contract
            FROM pg_catalog.pg_attribute
            WHERE attrelid =
                'governance.change_request_attachment_upload_intents'::regclass
              AND attnum > 0
              AND NOT attisdropped;
            IF actual_column_contract IS DISTINCT FROM expected_column_contract THEN
                RAISE EXCEPTION
                    'attachment upload intent column contract drifted: %',
                    actual_column_contract;
            END IF;
            IF EXISTS (
                SELECT 1
                FROM pg_catalog.pg_attribute
                WHERE attrelid =
                    'governance.change_request_attachment_upload_intents'::regclass
                  AND attname IN ('state', 'version')
                  AND atthasdef
            ) THEN
                RAISE EXCEPTION 'attachment upload intent defaults drifted';
            END IF;

            SELECT pg_catalog.array_agg(
                conname::text || ':' || pg_catalog.md5(
                    pg_catalog.pg_get_constraintdef(oid, true)
                )
                ORDER BY conname
            )
            INTO actual_constraints
            FROM pg_catalog.pg_constraint
            WHERE conrelid =
                'governance.change_request_attachment_upload_intents'::regclass;
            IF actual_constraints IS DISTINCT FROM expected_constraints THEN
                RAISE EXCEPTION
                    'attachment upload intent constraints drifted: %', actual_constraints;
            END IF;

            SELECT pg_catalog.array_agg(
                index_class.relname::text || ':' ||
                index_record.indisunique::text || ':' ||
                index_record.indisprimary::text || ':' ||
                access_method.amname::text || ':' ||
                (
                    SELECT pg_catalog.string_agg(attribute.attname, ',' ORDER BY key.ordinality)
                    FROM pg_catalog.unnest(index_record.indkey::smallint[])
                        WITH ORDINALITY AS key(attnum, ordinality)
                    JOIN pg_catalog.pg_attribute AS attribute
                      ON attribute.attrelid = index_record.indrelid
                     AND attribute.attnum = key.attnum
                    WHERE key.ordinality <= index_record.indnkeyatts
                )
                ORDER BY index_class.relname
            )
            INTO actual_indexes
            FROM pg_catalog.pg_index AS index_record
            JOIN pg_catalog.pg_class AS index_class
              ON index_class.oid = index_record.indexrelid
            JOIN pg_catalog.pg_class AS table_class
              ON table_class.oid = index_record.indrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = table_class.relnamespace
            JOIN pg_catalog.pg_am AS access_method
              ON access_method.oid = index_class.relam
            WHERE namespace.nspname = 'governance'
              AND table_class.relname = 'change_request_attachment_upload_intents'
              AND index_record.indisvalid
              AND index_record.indisready
              AND index_record.indislive
              AND index_record.indexprs IS NULL
              AND index_record.indpred IS NULL
              AND index_record.indnkeyatts = index_record.indnatts;
            IF actual_indexes IS DISTINCT FROM expected_indexes THEN
                RAISE EXCEPTION 'attachment upload intent indexes drifted: %', actual_indexes;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class
                WHERE oid =
                    'governance.change_request_attachment_upload_intents'::regclass
                  AND relrowsecurity
                  AND relforcerowsecurity
            ) THEN
                RAISE EXCEPTION 'attachment upload intent RLS is not forced';
            END IF;

            IF (
                SELECT pg_catalog.array_agg(policyname::text ORDER BY policyname)
                FROM pg_catalog.pg_policies
                WHERE schemaname = 'governance'
                  AND tablename = 'change_request_attachment_upload_intents'
            ) IS DISTINCT FROM ARRAY[
                'attachment_upload_intent_subject',
                'workspace_isolation'
            ]::text[] THEN
                RAISE EXCEPTION 'attachment upload intent policies drifted';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_policies
                WHERE schemaname = 'governance'
                  AND tablename = 'change_request_attachment_upload_intents'
                  AND policyname = 'attachment_upload_intent_subject'
                  AND permissive = 'RESTRICTIVE'
                  AND cmd = 'ALL'
            ) THEN
                RAISE EXCEPTION 'attachment upload intent subject policy drifted';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_trigger
                WHERE tgrelid =
                    'governance.change_request_attachment_upload_intents'::regclass
                  AND tgname = 'guard_attachment_upload_intent'
                  AND NOT tgisinternal
            ) THEN
                RAISE EXCEPTION 'attachment upload intent transition guard is missing';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_trigger
                WHERE tgrelid = 'governance.change_request_attachments'::regclass
                  AND tgname = 'guard_change_request_attachment_insert'
                  AND NOT tgisinternal
            ) THEN
                RAISE EXCEPTION 'attachment insert intent guard is missing';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc
                WHERE oid = 'governance.guard_attachment_upload_intent()'::regprocedure
                  AND NOT prosecdef
                  AND proconfig = ARRAY['search_path=pg_catalog']::text[]
            ) THEN
                RAISE EXCEPTION 'attachment upload intent guard configuration drifted';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc
                WHERE oid =
                    'governance.guard_change_request_attachment_insert()'::regprocedure
                  AND NOT prosecdef
                  AND proconfig = ARRAY['search_path=pg_catalog']::text[]
            ) THEN
                RAISE EXCEPTION 'attachment insert guard configuration drifted';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        (
                            'governance.claim_attachment_upload_reconciliation('
                            'timestamp with time zone)'::text
                        ),
                        (
                            'governance.attest_attachment_upload_object('
                            'uuid,uuid,integer,text,text)'::text
                        ),
                        (
                            'governance.defer_attachment_upload_reconciliation('
                            'uuid,uuid)'::text
                        ),
                        (
                            'governance.fail_attachment_upload_intent('
                            'uuid,uuid,text)'::text
                        ),
                        (
                            'governance.finalize_attachment_upload_intent('
                            'uuid,uuid,integer)'::text
                        )
                ) AS expected(signature)
                LEFT JOIN pg_catalog.pg_proc AS actual
                  ON actual.oid = expected.signature::regprocedure
                WHERE actual.oid IS NULL
                   OR NOT actual.prosecdef
                   OR actual.proconfig IS NULL
                   OR NOT (
                       actual.proconfig[1] LIKE 'search_path=pg_catalog, governance%'
                   )
                   OR EXISTS (
                       SELECT 1
                       FROM pg_catalog.aclexplode(
                           COALESCE(
                               actual.proacl,
                               pg_catalog.acldefault('f', actual.proowner)
                           )
                       ) AS privilege
                       WHERE privilege.grantee = 0
                         AND privilege.privilege_type = 'EXECUTE'
                   )
            ) THEN
                RAISE EXCEPTION 'attachment upload intent function boundary drifted';
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'datariver_app'
            ) THEN
                IF NOT pg_catalog.has_table_privilege(
                    'datariver_app',
                    'governance.change_request_attachment_upload_intents',
                    'SELECT, INSERT'
                ) OR pg_catalog.has_table_privilege(
                    'datariver_app',
                    'governance.change_request_attachment_upload_intents',
                    'UPDATE'
                ) THEN
                    RAISE EXCEPTION 'attachment upload intent table grants drifted';
                END IF;
                SELECT pg_catalog.array_agg(attribute.attname ORDER BY attribute.attname)
                INTO extra_update_columns
                FROM pg_catalog.pg_attribute AS attribute
                WHERE attribute.attrelid =
                    'governance.change_request_attachment_upload_intents'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND pg_catalog.has_column_privilege(
                      'datariver_app',
                      'governance.change_request_attachment_upload_intents',
                      attribute.attname,
                      'UPDATE'
                  );
                IF extra_update_columns IS NOT NULL
                   OR pg_catalog.has_table_privilege(
                       'datariver_app',
                       'governance.change_request_attachments',
                       'INSERT'
                   )
                   OR NOT pg_catalog.has_function_privilege(
                       'datariver_app',
                       'governance.fail_attachment_upload_intent(uuid,uuid,text)',
                       'EXECUTE'
                   )
                   OR NOT pg_catalog.has_function_privilege(
                       'datariver_app',
                       'governance.finalize_attachment_upload_intent(uuid,uuid,integer)',
                       'EXECUTE'
                   )
                   OR pg_catalog.has_function_privilege(
                       'datariver_app',
                       'governance.claim_attachment_upload_reconciliation('
                           'timestamp with time zone)',
                       'EXECUTE'
                   )
                   OR pg_catalog.has_function_privilege(
                       'datariver_app',
                       'governance.attest_attachment_upload_object('
                           'uuid,uuid,integer,text,text)',
                       'EXECUTE'
                   ) THEN
                    RAISE EXCEPTION
                        'attachment app boundary is overbroad: %',
                        extra_update_columns;
                END IF;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'datariver_upload'
            ) THEN
                SELECT pg_catalog.array_agg(attribute.attname ORDER BY attribute.attname)
                INTO extra_update_columns
                FROM pg_catalog.pg_attribute AS attribute
                WHERE attribute.attrelid =
                    'governance.change_request_attachment_upload_intents'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND pg_catalog.has_column_privilege(
                      'datariver_upload',
                      'governance.change_request_attachment_upload_intents',
                      attribute.attname,
                      'UPDATE'
                );
                IF extra_update_columns IS NOT NULL
                   OR EXISTS (
                       SELECT 1
                       FROM pg_catalog.unnest(ARRAY[
                           'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                           'TRUNCATE', 'REFERENCES', 'TRIGGER'
                       ]) AS privilege_name
                       WHERE pg_catalog.has_table_privilege(
                           'datariver_upload',
                           'governance.change_request_attachment_upload_intents',
                           privilege_name
                       )
                   )
                   OR pg_catalog.has_table_privilege(
                       'datariver_upload',
                       'governance.change_request_attachments',
                       'INSERT'
                   )
                   OR NOT pg_catalog.has_function_privilege(
                       'datariver_upload',
                       'governance.claim_attachment_upload_reconciliation('
                           'timestamp with time zone)',
                       'EXECUTE'
                   )
                   OR NOT pg_catalog.has_function_privilege(
                       'datariver_upload',
                       'governance.attest_attachment_upload_object('
                           'uuid,uuid,integer,text,text)',
                       'EXECUTE'
                   )
                   OR NOT pg_catalog.has_function_privilege(
                       'datariver_upload',
                       'governance.defer_attachment_upload_reconciliation(uuid,uuid)',
                       'EXECUTE'
                   )
                   OR pg_catalog.has_function_privilege(
                       'datariver_upload',
                       'governance.finalize_attachment_upload_intent(uuid,uuid,integer)',
                       'EXECUTE'
                   ) THEN
                    RAISE EXCEPTION
                        'attachment upload worker boundary is overbroad: %',
                        extra_update_columns;
                END IF;
            END IF;
        END
        $datariver$;
        """
    )


def upgrade() -> None:
    if not _table_exists():
        _create_table()
    _install_security()
    _assert_contract()


def downgrade() -> None:
    # Evidence durability is forward-only; removing the intent ledger would orphan stored bytes.
    pass
