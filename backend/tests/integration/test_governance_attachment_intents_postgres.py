from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.secrets import SecretResolver

_DATABASE_URL_ENV = "DATARIVER_REGISTRATION_RLS_TEST_DATABASE_URL"
_SECRET_REF_ENV = "DATARIVER_REGISTRATION_RLS_TEST_DATABASE_SECRET_REF"
_CONFIRM_ISOLATED_ENV = "DATARIVER_REGISTRATION_RLS_TEST_CONFIRM_ISOLATED"
_POSTGRES_ENABLED = bool(os.getenv(_DATABASE_URL_ENV)) and os.getenv(_CONFIRM_ISOLATED_ENV) == "1"


def _engine() -> AsyncEngine:
    return create_async_engine(
        os.environ[_DATABASE_URL_ENV],
        connect_args={
            "password": SecretResolver().resolve(
                os.getenv(_SECRET_REF_ENV, "file:/run/secrets/postgres_password")
            )
        },
    )


async def _set_app_context(
    connection: AsyncConnection,
    *,
    workspace_id: UUID,
    subject_id: UUID,
) -> None:
    await connection.execute(text("SET LOCAL ROLE datariver_app"))
    await connection.execute(
        text("SELECT set_config('app.workspace_id', :value, true)"),
        {"value": str(workspace_id)},
    )
    await connection.execute(
        text("SELECT set_config('app.subject_id', :value, true)"),
        {"value": str(subject_id)},
    )


async def _set_upload_role(connection: AsyncConnection) -> None:
    await connection.execute(text("SET LOCAL ROLE datariver_upload"))


async def _prepare_fixture(
    engine: AsyncEngine,
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    workspace_id = uuid4()
    uploader_id = uuid4()
    other_subject_id = uuid4()
    change_request_id = uuid4()
    round_id = uuid4()
    attachment_id = uuid4()
    now = datetime.now(UTC)
    attributes = json.dumps(
        {
            "groups": ["data-stewards"],
            "allowed_actions": ["change.edit"],
            "denied_actions": [],
        }
    )
    async with engine.begin() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == REQUIRED_DATABASE_REVISION
        await connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, version)
                VALUES (:id, :slug, 'Attachment intent test', 'ACTIVE', '{}'::jsonb, 1)
                """
            ),
            {"id": workspace_id, "slug": f"attachment-{workspace_id.hex}"},
        )
        for subject_id in (uploader_id, other_subject_id):
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.subjects
                        (id, issuer, external_subject, display_name, active)
                    VALUES (:id, 'https://issuer.test', :external_subject, 'Attachment actor', true)
                    """
                ),
                {"id": subject_id, "external_subject": str(subject_id)},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO iam.workspace_memberships
                        (workspace_id, subject_id, clearance, attributes, active, version)
                    VALUES (:workspace_id, :subject_id, 2, CAST(:attributes AS jsonb), true, 1)
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "subject_id": subject_id,
                    "attributes": attributes,
                },
            )
        await connection.execute(
            text(
                """
                INSERT INTO governance.change_requests
                    (id, workspace_id, number, request_type, title, description, state,
                     requester_id, current_round_id, current_round_number, classification,
                     version)
                VALUES
                    (:id, :workspace_id, :number, 'CATALOG_METADATA', 'Attachment test', '',
                     'REGISTERED', :requester_id, :round_id, 1, 1, 1)
                """
            ),
            {
                "id": change_request_id,
                "workspace_id": workspace_id,
                "number": f"CR-ATTACH-{change_request_id.hex}",
                "requester_id": uploader_id,
                "round_id": round_id,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO governance.change_request_rounds
                    (id, workspace_id, change_request_id, round_number, submitted_by,
                     submitted_at, evidence_hash)
                VALUES (:id, :workspace_id, :change_request_id, 1, :submitted_by,
                        :submitted_at, :evidence_hash)
                """
            ),
            {
                "id": round_id,
                "workspace_id": workspace_id,
                "change_request_id": change_request_id,
                "submitted_by": uploader_id,
                "submitted_at": now,
                "evidence_hash": "a" * 64,
            },
        )
    return (
        workspace_id,
        uploader_id,
        other_subject_id,
        change_request_id,
        round_id,
        attachment_id,
    )


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_attachment_intent_requires_independent_attestation_and_current_reauthorization() -> (
    None
):
    engine = _engine()
    async with engine.begin() as connection:
        original_upload_bypass = bool(
            await connection.scalar(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'datariver_upload'")
            )
        )
        await connection.execute(text("ALTER ROLE datariver_upload BYPASSRLS"))
    (
        workspace_id,
        uploader_id,
        other_subject_id,
        change_request_id,
        round_id,
        attachment_id,
    ) = await _prepare_fixture(engine)
    object_key = (
        f"governance/change-request-attachments/{workspace_id}/{change_request_id}/{attachment_id}"
    )
    parameters = {
        "id": attachment_id,
        "workspace_id": workspace_id,
        "change_request_id": change_request_id,
        "round_id": round_id,
        "bucket": "datariver-filefolder",
        "object_key": object_key,
        "uploaded_by": uploader_id,
        "size_bytes": 17,
        "content_sha256": "b" * 64,
    }
    try:
        async with engine.connect() as connection:
            for role in ("datariver_app", "datariver_upload"):
                update_columns = list(
                    (
                        await connection.scalars(
                            text(
                                """
                                SELECT attribute.attname
                                FROM pg_catalog.pg_attribute AS attribute
                                WHERE attribute.attrelid =
                                    'governance.change_request_attachment_upload_intents'
                                        ::regclass
                                  AND attribute.attnum > 0
                                  AND NOT attribute.attisdropped
                                  AND pg_catalog.has_column_privilege(
                                      :role,
                                      'governance.change_request_attachment_upload_intents',
                                      attribute.attname,
                                      'UPDATE'
                                  )
                                ORDER BY attribute.attname
                                """
                            ),
                            {"role": role},
                        )
                    ).all()
                )
                assert update_columns == []

        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await _set_app_context(
                        connection,
                        workspace_id=workspace_id,
                        subject_id=uploader_id,
                    )
                    await connection.execute(
                        text(
                            """
                            INSERT INTO governance.change_request_attachment_upload_intents
                                (id, workspace_id, change_request_id, round_id, kind,
                                 original_name, serial_number, bucket, object_key, content_type,
                                 expected_size_bytes, expected_content_sha256, state, size_bytes,
                                 content_sha256, provider_checksum, uploaded_by, stored_at, version)
                            VALUES
                                (:id, :workspace_id, :change_request_id, :round_id, 'REQUEST',
                                 'evidence.csv', 1, :bucket, :object_key, 'text/csv', :size_bytes,
                                 :content_sha256, 'STORED', :size_bytes, :content_sha256,
                                 'etag:forged', :uploaded_by, now(), 1)
                            """
                        ),
                        parameters,
                    )

        async with engine.begin() as connection:
            await _set_app_context(
                connection,
                workspace_id=workspace_id,
                subject_id=uploader_id,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO governance.change_request_attachment_upload_intents
                        (id, workspace_id, change_request_id, round_id, kind, original_name,
                         serial_number, bucket, object_key, content_type, expected_size_bytes,
                         expected_content_sha256, state, uploaded_by, version)
                    VALUES
                        (:id, :workspace_id, :change_request_id, :round_id, 'REQUEST',
                         'evidence.csv', 1, :bucket, :object_key, 'text/csv', :size_bytes,
                         :content_sha256, 'STARTED', :uploaded_by, 1)
                    """
                ),
                parameters,
            )

        async with engine.begin() as connection:
            await _set_app_context(
                connection,
                workspace_id=workspace_id,
                subject_id=uploader_id,
            )
            visible = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM governance.change_request_attachment_upload_intents
                    WHERE id = :id
                    """
                ),
                parameters,
            )
            assert int(visible or 0) == 1

        async with engine.begin() as connection:
            await _set_app_context(
                connection,
                workspace_id=uuid4(),
                subject_id=uploader_id,
            )
            visible = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM governance.change_request_attachment_upload_intents
                    WHERE id = :id
                    """
                ),
                parameters,
            )
            assert int(visible or 0) == 0

        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await _set_upload_role(connection)
                    await connection.scalar(
                        text(
                            """
                            SELECT count(*)
                            FROM governance.change_request_attachment_upload_intents
                            WHERE state = 'STARTED'
                              AND id = :id
                            """
                        ),
                        parameters,
                    )

        async with engine.connect() as connection:
            async with connection.begin():
                await _set_upload_role(connection)
                claimed = (
                    await connection.execute(
                        text(
                            """
                            SELECT id, state
                            FROM governance.claim_attachment_upload_reconciliation(
                                :before_or_at
                            )
                            """
                        ),
                        {"before_or_at": datetime.now(UTC)},
                    )
                ).one()
                assert claimed.id == attachment_id
                assert claimed.state == "STARTED"

        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await _set_upload_role(connection)
                    await connection.execute(
                        text(
                            """
                            UPDATE governance.change_request_attachment_upload_intents
                            SET updated_at = now(),
                                version = version + 1
                            WHERE id = :id
                            """
                        ),
                        parameters,
                    )

        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await _set_app_context(
                        connection,
                        workspace_id=workspace_id,
                        subject_id=uploader_id,
                    )
                    await connection.execute(
                        text(
                            """
                            UPDATE governance.change_request_attachment_upload_intents
                            SET state = 'STORED',
                                size_bytes = :size_bytes,
                                content_sha256 = :content_sha256,
                                provider_checksum = 'etag:forged',
                                stored_at = now(),
                                updated_at = now(),
                                version = version + 1
                            WHERE id = :id
                            """
                        ),
                        parameters,
                    )

        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await _set_app_context(
                        connection,
                        workspace_id=workspace_id,
                        subject_id=uploader_id,
                    )
                    await connection.execute(
                        text(
                            """
                            SELECT governance.attest_attachment_upload_object(
                                :workspace_id,
                                :id,
                                :size_bytes,
                                :content_sha256,
                                'etag:forged'
                            )
                            """
                        ),
                        parameters,
                    )

        for role in ("datariver_app", "datariver_upload"):
            async with engine.connect() as connection:
                with pytest.raises(DBAPIError):
                    async with connection.begin():
                        if role == "datariver_app":
                            await _set_app_context(
                                connection,
                                workspace_id=workspace_id,
                                subject_id=uploader_id,
                            )
                        else:
                            await _set_upload_role(connection)
                        await connection.execute(
                            text(
                                """
                                INSERT INTO governance.change_request_attachments
                                    (id, workspace_id, change_request_id, round_id, kind,
                                     original_name, serial_number, bucket, object_key,
                                     content_type, size_bytes, content_sha256, uploaded_by)
                                VALUES
                                    (:id, :workspace_id, :change_request_id, :round_id,
                                     'REQUEST', 'evidence.csv', 1, :bucket, :object_key,
                                     'text/csv', :size_bytes, :content_sha256, :uploaded_by)
                                """
                            ),
                            parameters,
                        )

        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await _set_upload_role(connection)
                    await connection.execute(
                        text(
                            """
                            SELECT governance.attest_attachment_upload_object(
                                :workspace_id,
                                :id,
                                :size_bytes,
                                :content_sha256,
                                'etag:evidence'
                            )
                            """
                        ),
                        {**parameters, "content_sha256": "c" * 64},
                    )

        async with engine.begin() as connection:
            await _set_upload_role(connection)
            await connection.execute(
                text(
                    """
                    SELECT governance.attest_attachment_upload_object(
                        :workspace_id,
                        :id,
                        :size_bytes,
                        :content_sha256,
                        'etag:evidence'
                    )
                    """
                ),
                parameters,
            )

        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await _set_upload_role(connection)
                    await connection.execute(
                        text(
                            """
                            SELECT governance.finalize_attachment_upload_intent(
                                :workspace_id,
                                :id,
                                1
                            )
                            """
                        ),
                        parameters,
                    )

        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await _set_app_context(
                        connection,
                        workspace_id=workspace_id,
                        subject_id=uploader_id,
                    )
                    await connection.execute(
                        text(
                            """
                            SELECT governance.finalize_attachment_upload_intent(
                                :workspace_id,
                                :id,
                                999
                            )
                            """
                        ),
                        parameters,
                    )

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE iam.workspace_memberships
                    SET active = false,
                        version = version + 1,
                        updated_at = now()
                    WHERE workspace_id = :workspace_id
                      AND subject_id = :uploaded_by
                    """
                ),
                parameters,
            )
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                async with connection.begin():
                    await _set_app_context(
                        connection,
                        workspace_id=workspace_id,
                        subject_id=uploader_id,
                    )
                    await connection.execute(
                        text(
                            """
                            SELECT governance.finalize_attachment_upload_intent(
                                :workspace_id,
                                :id,
                                1
                            )
                            """
                        ),
                        parameters,
                    )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE iam.workspace_memberships
                    SET active = true,
                        version = version + 1,
                        updated_at = now()
                    WHERE workspace_id = :workspace_id
                      AND subject_id = :uploaded_by
                    """
                ),
                parameters,
            )
        async with engine.begin() as connection:
            await _set_app_context(
                connection,
                workspace_id=workspace_id,
                subject_id=uploader_id,
            )
            finalized_id = await connection.scalar(
                text(
                    """
                    SELECT governance.finalize_attachment_upload_intent(
                        :workspace_id,
                        :id,
                        1
                    )
                    """
                ),
                parameters,
            )
            assert finalized_id == attachment_id
            timestamps = (
                await connection.execute(
                    text(
                        """
                        SELECT created_at, stored_at, finalized_at
                        FROM governance.change_request_attachment_upload_intents
                        WHERE id = :id
                        """
                    ),
                    parameters,
                )
            ).one()
            assert timestamps.created_at <= timestamps.stored_at <= timestamps.finalized_at

        async with engine.begin() as connection:
            await _set_app_context(
                connection,
                workspace_id=workspace_id,
                subject_id=other_subject_id,
            )
            visible = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM governance.change_request_attachment_upload_intents
                    WHERE id = :id
                    """
                ),
                {"id": attachment_id},
            )
            assert int(visible or 0) == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    DELETE FROM governance.change_request_attachment_upload_intents
                    WHERE workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": workspace_id},
            )
            await connection.execute(
                text(
                    """
                    DELETE FROM governance.change_request_attachments
                    WHERE workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": workspace_id},
            )
            await connection.execute(
                text(
                    """
                    DELETE FROM governance.change_requests
                    WHERE workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": workspace_id},
            )
            await connection.execute(
                text("DELETE FROM platform.workspaces WHERE id = :workspace_id"),
                {"workspace_id": workspace_id},
            )
            await connection.execute(
                text("DELETE FROM iam.subjects WHERE id IN (:uploader_id, :other_subject_id)"),
                {
                    "uploader_id": uploader_id,
                    "other_subject_id": other_subject_id,
                },
            )
            await connection.execute(
                text(
                    "ALTER ROLE datariver_upload "
                    + ("BYPASSRLS" if original_upload_bypass else "NOBYPASSRLS")
                )
            )
        await engine.dispose()
