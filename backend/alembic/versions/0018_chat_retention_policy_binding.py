"""Bind Chat persistence to the active governed retention policy.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "chat_sessions"
SCHEMA = "assistant"
ACTIVE = "ACTIVE_POLICY_V1"
CONTRACT_COLUMNS = (
    "retention_policy_id",
    "retention_policy_hash",
    "retention_basis_at",
    "retention_binding_version",
)
EXPECTED_OBJECT_COUNT = len(CONTRACT_COLUMNS)


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = 'assistant'
                  AND table_name = 'chat_sessions'
                  AND column_name IN (
                      'retention_policy_id',
                      'retention_policy_hash',
                      'retention_basis_at',
                      'retention_binding_version'
                  )
                """
            )
        )
        .scalar_one()
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The Chat retention binding schema is only partially present.")
        _assert_chat_retention_binding_contract()
        return

    # Existing Chat content has a deadline but no trustworthy policy reference. Preserve it
    # explicitly as append-closed legacy evidence instead of fabricating an active-policy binding.
    op.add_column(
        TABLE,
        sa.Column("retention_policy_id", sa.Uuid(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("retention_policy_hash", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("retention_basis_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "retention_binding_version",
            sa.String(length=32),
            server_default="LEGACY_UNBOUND_V1",
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.alter_column(
        TABLE,
        "retention_binding_version",
        server_default=ACTIVE,
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_chat_sessions_retention_binding_version_allowlist",
        TABLE,
        "retention_binding_version IN ('LEGACY_UNBOUND_V1', 'ACTIVE_POLICY_V1')",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_chat_sessions_retention_binding_shape",
        TABLE,
        "(retention_binding_version = 'LEGACY_UNBOUND_V1' "
        "AND retention_policy_id IS NULL AND retention_policy_hash IS NULL "
        "AND retention_basis_at IS NULL) OR "
        "(retention_binding_version = 'ACTIVE_POLICY_V1' "
        "AND retention_policy_id IS NOT NULL AND retention_policy_hash IS NOT NULL "
        "AND retention_basis_at IS NOT NULL AND retention_until IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_chat_sessions_retention_policy_hash_sha256",
        TABLE,
        "retention_policy_hash IS NULL OR retention_policy_hash ~ '^[0-9a-f]{64}$'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_chat_sessions_retention_window",
        TABLE,
        "retention_until IS NULL OR retention_basis_at IS NULL "
        "OR retention_until > retention_basis_at",
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_chat_sessions_retention_policy_binding",
        TABLE,
        "policy_versions",
        ["workspace_id", "retention_policy_id", "retention_policy_hash"],
        ["workspace_id", "id", "payload_hash"],
        source_schema=SCHEMA,
        referent_schema="retention",
        ondelete="RESTRICT",
    )
    for statement in _chat_retention_binding_sql():
        op.execute(statement)
    op.execute(
        """
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                REVOKE UPDATE ON assistant.chat_sessions FROM datariver_app;
                GRANT UPDATE (version, updated_at) ON assistant.chat_sessions TO datariver_app;
            END IF;
        END
        $grant$
        """
    )
    _assert_chat_retention_binding_contract()


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns this canonical retention contract.
    pass


def _assert_chat_retention_binding_contract() -> None:
    op.execute(
        """
        DO $contract$
        DECLARE
            binding_default text;
        BEGIN
            SELECT column_default
            INTO binding_default
            FROM information_schema.columns
            WHERE table_schema = 'assistant'
              AND table_name = 'chat_sessions'
              AND column_name = 'retention_binding_version'
              AND is_nullable = 'NO';
            IF binding_default IS NULL OR binding_default NOT LIKE '%ACTIVE_POLICY_V1%' THEN
                RAISE EXCEPTION 'Chat retention binding default contract is invalid';
            END IF;

            IF (
                SELECT count(*)
                FROM pg_constraint
                WHERE conrelid = 'assistant.chat_sessions'::regclass
                  AND conname IN (
                      'ck_chat_sessions_retention_binding_version_allowlist',
                      'ck_chat_sessions_retention_binding_shape',
                      'ck_chat_sessions_retention_policy_hash_sha256',
                      'ck_chat_sessions_retention_window',
                      'fk_chat_sessions_retention_policy_binding'
                  )
            ) <> 5 THEN
                RAISE EXCEPTION 'Chat retention binding constraint contract is invalid';
            END IF;

            IF (
                SELECT count(*)
                FROM pg_trigger
                WHERE NOT tgisinternal
                  AND tgname IN (
                      'enforce_chat_session_retention_binding',
                      'enforce_chat_message_retention_binding'
                  )
            ) <> 2 THEN
                RAISE EXCEPTION 'Chat retention binding trigger contract is invalid';
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app')
               AND (
                   has_table_privilege(
                       'datariver_app', 'assistant.chat_sessions', 'UPDATE'
                   )
                   OR has_column_privilege(
                       'datariver_app', 'assistant.chat_sessions', 'retention_until', 'UPDATE'
                   )
                   OR NOT has_column_privilege(
                       'datariver_app', 'assistant.chat_sessions', 'version', 'UPDATE'
                   )
                   OR has_table_privilege(
                       'datariver_app', 'assistant.chat_sessions', 'DELETE'
                   )
               ) THEN
                RAISE EXCEPTION 'Chat retention binding privilege contract is invalid';
            END IF;
        END
        $contract$
        """
    )


def _chat_retention_binding_sql() -> tuple[str, ...]:
    session_function = """
CREATE FUNCTION assistant.enforce_chat_session_retention_binding()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
DECLARE
    policy_days integer;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
           OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.retention_until IS DISTINCT FROM OLD.retention_until
           OR NEW.retention_policy_id IS DISTINCT FROM OLD.retention_policy_id
           OR NEW.retention_policy_hash IS DISTINCT FROM OLD.retention_policy_hash
           OR NEW.retention_basis_at IS DISTINCT FROM OLD.retention_basis_at
           OR NEW.retention_binding_version IS DISTINCT FROM OLD.retention_binding_version THEN
            RAISE EXCEPTION 'Chat session retention evidence is immutable'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.retention_binding_version <> 'ACTIVE_POLICY_V1' THEN
        RAISE EXCEPTION 'new Chat sessions require an active-policy retention binding'
            USING ERRCODE = '23514';
    END IF;

    SELECT policy.chat_content_days
    INTO policy_days
    FROM retention.policy_versions AS policy
    WHERE policy.workspace_id = NEW.workspace_id
      AND policy.id = NEW.retention_policy_id
      AND policy.payload_hash = NEW.retention_policy_hash
      AND policy.state = 'ACTIVE'
    FOR KEY SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Chat retention policy binding is not active'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.retention_basis_at IS DISTINCT FROM transaction_timestamp() THEN
        RAISE EXCEPTION 'Chat retention basis must equal the persistence transaction time'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.retention_until IS DISTINCT FROM
       NEW.retention_basis_at + make_interval(days => policy_days) THEN
        RAISE EXCEPTION 'Chat retention deadline does not match the active policy'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
""".strip()
    session_trigger = """
CREATE TRIGGER enforce_chat_session_retention_binding
BEFORE INSERT OR UPDATE ON assistant.chat_sessions
FOR EACH ROW
EXECUTE FUNCTION assistant.enforce_chat_session_retention_binding()
""".strip()
    message_function = """
CREATE FUNCTION assistant.enforce_chat_message_retention_binding()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $function$
BEGIN
    PERFORM 1
    FROM assistant.chat_sessions AS session
    JOIN retention.policy_versions AS policy
      ON policy.workspace_id = session.workspace_id
     AND policy.id = session.retention_policy_id
     AND policy.payload_hash = session.retention_policy_hash
    WHERE session.workspace_id = NEW.workspace_id
      AND session.id = NEW.session_id
      AND session.owner_id =
          NULLIF(current_setting('app.subject_id', true), '')::uuid
      AND session.retention_binding_version = 'ACTIVE_POLICY_V1'
      AND session.retention_until > transaction_timestamp()
      AND policy.state = 'ACTIVE'
    FOR KEY SHARE OF session, policy;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Chat session is not appendable under the active retention policy'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$
""".strip()
    message_trigger = """
CREATE TRIGGER enforce_chat_message_retention_binding
BEFORE INSERT ON assistant.chat_messages
FOR EACH ROW
EXECUTE FUNCTION assistant.enforce_chat_message_retention_binding()
""".strip()
    return session_function, session_trigger, message_function, message_trigger
