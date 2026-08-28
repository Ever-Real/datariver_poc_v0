"""Persist governed Knowledge source analysis, GraphRAG audit, and verified projection evidence.

Revision ID: 0037
Revises: 0036
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from datariver.infrastructure.db.migration_definition_fingerprint import (
    RelationDefinitionFingerprintV1,
    read_relation_definition_fingerprint_v1,
)

revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
EXPECTED_OBJECT_COUNT = 16

_CANONICAL_TABLES = {
    "source_snapshots": (
        (
            "workspace_id|uuid|uuid||NO",
            "graph_id|uuid|uuid||NO",
            "upload_id|uuid|uuid||NO",
            "bucket|character varying|varchar|255|NO",
            "object_key|text|text||NO",
            "storage_version|character varying|varchar|255|NO",
            "media_type|character varying|varchar|100|NO",
            "byte_size|bigint|int8||NO",
            "content_sha256|character varying|varchar|64|NO",
            "classification|integer|int4||NO",
            "state|character varying|varchar|32|NO",
            "created_by|uuid|uuid||NO",
            "id|uuid|uuid||NO",
            "created_at|timestamp with time zone|timestamptz||NO",
            "updated_at|timestamp with time zone|timestamptz||NO",
        ),
        (
            "ck_source_snapshots_bounded_size",
            "ck_source_snapshots_content_sha256",
            "ck_source_snapshots_media_type_vocabulary",
            "ck_source_snapshots_state_vocabulary",
            "fk_source_snapshots_manifest_graph",
            "fk_source_snapshots_workspace_id_graph_id_graphs",
            "pk_source_snapshots",
            "uq_source_snapshots_workspace_graph_id",
            "uq_source_snapshots_workspace_id_graph_id_upload_id",
            "uq_source_snapshots_workspace_id_id",
        ),
        ("ix_source_snapshots_graph_created",),
        ("trg_source_snapshot_job_scope",),
    ),
    "source_pages": (
        (
            "workspace_id|uuid|uuid||NO",
            "source_snapshot_id|uuid|uuid||NO",
            "page_number|integer|int4||NO",
            "content_sha256|character varying|varchar|64|NO",
            "content|text|text||NO",
        ),
        (
            "ck_source_pages_content_sha256",
            "ck_source_pages_page_number_positive",
            "fk_source_pages_workspace_id_source_snapshot_id_source__9a0d",
            "pk_source_pages",
        ),
        (),
        ("trg_source_page_job_scope",),
    ),
    "source_page_embeddings": (
        (
            "workspace_id|uuid|uuid||NO",
            "source_snapshot_id|uuid|uuid||NO",
            "page_number|integer|int4||NO",
            "provider|character varying|varchar|100|NO",
            "model_identity|character varying|varchar|200|NO",
            "dimension|integer|int4||NO",
            "embedding|jsonb|jsonb||NO",
            "content_sha256|character varying|varchar|64|NO",
            "id|uuid|uuid||NO",
            "created_at|timestamp with time zone|timestamptz||NO",
            "updated_at|timestamp with time zone|timestamptz||NO",
        ),
        (
            "ck_source_page_embeddings_bounded_dimension",
            "ck_source_page_embeddings_content_sha256",
            "fk_source_page_embeddings_workspace_id_source_snapshot__8ea1",
            "pk_source_page_embeddings",
            "uq_source_page_embeddings_source_snapshot_id_page_numbe_7805",
        ),
        ("ix_source_page_embeddings_source",),
        ("trg_source_embedding_job_scope",),
    ),
    "extraction_runs": (
        (
            "workspace_id|uuid|uuid||NO",
            "graph_id|uuid|uuid||NO",
            "source_snapshot_id|uuid|uuid||NO",
            "proposed_changeset_id|uuid|uuid||NO",
            "source_analysis_job_id|uuid|uuid||YES",
            "source_analysis_attempt_id|uuid|uuid||YES",
            "contract_version|character varying|varchar|32|NO",
            "state|character varying|varchar|32|NO",
            "parser_config_hash|character varying|varchar|64|NO",
            "embedding_binding|jsonb|jsonb||NO",
            "extraction_binding|jsonb|jsonb||NO",
            "input_hash|character varying|varchar|64|NO",
            "output_hash|character varying|varchar|64|NO",
            "error_code|character varying|varchar|100|YES",
            "id|uuid|uuid||NO",
            "created_at|timestamp with time zone|timestamptz||NO",
            "updated_at|timestamp with time zone|timestamptz||NO",
            "version|integer|int4||NO",
        ),
        (
            "ck_extraction_runs_contract_shape",
            "ck_extraction_runs_input_hash",
            "ck_extraction_runs_output_hash",
            "ck_extraction_runs_state_vocabulary",
            "fk_extraction_runs_workspace_id_graph_id_graphs",
            "fk_extraction_runs_workspace_id_proposed_changeset_id_c_f9f4",
            "fk_extraction_runs_workspace_id_source_analysis_attempt_ae22",
            "fk_extraction_runs_workspace_id_source_analysis_job_id__1b91",
            "fk_extraction_runs_workspace_id_source_snapshot_id_sour_9a6d",
            "pk_extraction_runs",
            "uq_extraction_runs_workspace_id_id",
        ),
        ("ix_extraction_runs_graph_created",),
        ("trg_extraction_run_job_scope",),
    ),
    "graphrag_audits": (
        (
            "workspace_id|uuid|uuid||NO",
            "graph_id|uuid|uuid||NO",
            "release_id|uuid|uuid||NO",
            "actor_id|uuid|uuid||NO",
            "request_id|character varying|varchar|100|NO",
            "question_sha256|character varying|varchar|64|NO",
            "evidence_ids|jsonb|jsonb||NO",
            "cited_evidence_ids|jsonb|jsonb||NO",
            "provider|character varying|varchar|100|NO",
            "model_identity|character varying|varchar|200|NO",
            "prompt_version|character varying|varchar|200|NO",
            "tool_schema_version|character varying|varchar|200|NO",
            "configuration_source|character varying|varchar|32|YES",
            "configuration_version|integer|int4||YES",
            "configuration_hash|character varying|varchar|64|YES",
            "input_tokens|integer|int4||YES",
            "output_tokens|integer|int4||YES",
            "id|uuid|uuid||NO",
            "created_at|timestamp with time zone|timestamptz||NO",
            "updated_at|timestamp with time zone|timestamptz||NO",
        ),
        (
            "ck_graphrag_audits_configuration_evidence_shape",
            "ck_graphrag_audits_input_tokens_nonnegative",
            "ck_graphrag_audits_output_tokens_nonnegative",
            "ck_graphrag_audits_question_sha256",
            "fk_graphrag_audits_workspace_id_graph_id_release_id_releases",
            "pk_graphrag_audits",
            "uq_graphrag_audits_workspace_id_request_id",
        ),
        ("ix_graphrag_audits_release_created",),
        (),
    ),
}
_WORKSPACE_POLICY_SHA256 = "9b5ca7ec5c37c60f1f4bbebc96a32edc1a47b8ee5f15c5cadceb73f291aedb86"
_EMPTY_DEFINITION_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_CANONICAL_POLICIES = {
    "knowledge.source_snapshots": (
        "knowledge_worker_current_source",
        "workspace_isolation",
    ),
    "knowledge.source_pages": ("workspace_isolation",),
    "knowledge.source_page_embeddings": ("workspace_isolation",),
    "knowledge.extraction_runs": ("workspace_isolation",),
    "knowledge.graphrag_audits": ("workspace_isolation",),
}
_CANONICAL_DEFINITION_FINGERPRINTS = {
    "knowledge.source_snapshots": RelationDefinitionFingerprintV1(
        "7c9b3d7dbaafe2fa800dad73da58e5e1b23905c97a5e9db01446cff44562e274",
        "dec7ac0314d71de691a89f3ffa011444446e161bd768980a304f6b43e819b9ac",
        "c721fec877c6a82e6cdb3c71505db022143a4fcea6a0b5e7ea724b1b3fccb5ce",
        "7a90ac0585ef83dcd3a507ed394b69f67134add10874e8e0769b957f8d9e2f00",
        "true|true",
    ),
    "knowledge.source_pages": RelationDefinitionFingerprintV1(
        "903e9b110bee8930c2c93b2152bdcd327117ab0a9db7907a67df3d03ddf73003",
        _EMPTY_DEFINITION_SHA256,
        _WORKSPACE_POLICY_SHA256,
        "0a6b0cb0e5829b7b4bf759ac180b2ef231ad474d9665ffa809add11f76b4015b",
        "true|true",
    ),
    "knowledge.source_page_embeddings": RelationDefinitionFingerprintV1(
        "bda929749a15b37335e98cc096a2039d1d532d319d942ed559c0e021557e3ebf",
        "b1a63e44b6530e62b233d88beef92a685ac901cc076e6415c8502ae3fe5a3982",
        _WORKSPACE_POLICY_SHA256,
        "580846b5cc80d63950aa729c2c5115a62d6b1fd1ee9fe7e725503ea9152077bb",
        "true|true",
    ),
    "knowledge.extraction_runs": RelationDefinitionFingerprintV1(
        "18f2aba6b70b27f3c11bb1c93148f6514e064dba7dd3a3687207dfa82c408850",
        "e094aacfc8e153355acca842f0aad4926871a45af1bf5cc780f8867795ad3d9b",
        _WORKSPACE_POLICY_SHA256,
        "be802981730811253316fd1c3f9fe09e63c0137b2fb6982f5f13a8a1e2ad7a39",
        "true|true",
    ),
    "knowledge.graphrag_audits": RelationDefinitionFingerprintV1(
        "912278759b496f564d8c85667d2134562c1c2f59a6485990137fcc93534fd9c5",
        "023f2063f42b3ec704c416f0a465ea54e26f1cb3e936ec13d6ab1df795d224c9",
        _WORKSPACE_POLICY_SHA256,
        _EMPTY_DEFINITION_SHA256,
        "true|true",
    ),
}
_CANONICAL_DEPLOYMENT_FINGERPRINT = RelationDefinitionFingerprintV1(
    "cd8f5b6199c1b6b0b4f58bc212c699f074967910e50f4828c226f47bce44ada9",
    "acdc7fb9f8cf63db24e05bff25a68135828666d1872998d80913fafe844b8764",
    "9b5ca7ec5c37c60f1f4bbebc96a32edc1a47b8ee5f15c5cadceb73f291aedb86",
    _EMPTY_DEFINITION_SHA256,
    "true|true",
)


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM information_schema.columns
                     WHERE table_schema = 'knowledge'
                       AND table_name = 'projection_deployments'
                       AND column_name IN (
                         'graph_id', 'job_id', 'verification_hash', 'verified_at', 'error_code'))
                    + (SELECT count(*) FROM pg_class AS item
                       JOIN pg_namespace AS namespace ON namespace.oid = item.relnamespace
                       WHERE namespace.nspname = 'knowledge'
                         AND item.relname IN (
                           'source_snapshots', 'source_pages', 'source_page_embeddings',
                           'extraction_runs', 'graphrag_audits')
                         AND item.relkind = 'r')
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conrelid = to_regclass('knowledge.projection_deployments')
                         AND conname LIKE
                           'fk_projection_deployments_workspace_id_graph_id_release_%')
                    + (SELECT count(*) FROM pg_policies
                       WHERE schemaname = 'knowledge'
                         AND tablename IN (
                           'source_snapshots', 'source_pages', 'source_page_embeddings',
                           'extraction_runs', 'graphrag_audits')
                         AND policyname = 'workspace_isolation')
                """
            )
        )
        .scalar_one()
    )


def _table_contract_is_exact(
    table_name: str,
    expected_columns: tuple[str, ...],
    expected_constraints: tuple[str, ...],
    expected_indexes: tuple[str, ...],
    expected_triggers: tuple[str, ...],
) -> bool:
    relation = f"knowledge.{table_name}"
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    ARRAY(
                        SELECT column_name || '|' || data_type || '|' || udt_name
                            || '|' || COALESCE(character_maximum_length::text, '')
                            || '|' || is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'knowledge' AND table_name = :table_name
                        ORDER BY ordinal_position
                    ) AS columns,
                    ARRAY(
                        SELECT conname FROM pg_constraint
                        WHERE conrelid = to_regclass(:relation)
                        ORDER BY conname
                    ) AS constraints,
                    ARRAY(
                        SELECT index_class.relname
                        FROM pg_index AS index_state
                        JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
                        WHERE index_state.indrelid = to_regclass(:relation)
                          AND NOT EXISTS (
                              SELECT 1 FROM pg_constraint
                              WHERE conindid = index_state.indexrelid
                          )
                        ORDER BY index_class.relname
                    ) AS indexes,
                    ARRAY(
                        SELECT polname FROM pg_policy
                        WHERE polrelid = to_regclass(:relation)
                        ORDER BY polname
                    ) AS policies,
                    ARRAY(
                        SELECT tgname FROM pg_trigger
                        WHERE tgrelid = to_regclass(:relation) AND NOT tgisinternal
                        ORDER BY tgname
                    ) AS triggers,
                    COALESCE((
                        SELECT relrowsecurity AND relforcerowsecurity
                        FROM pg_class WHERE oid = to_regclass(:relation)
                    ), FALSE) AS force_rls
                """
            ),
            {"relation": relation, "table_name": table_name},
        )
        .mappings()
        .one()
    )
    return (
        tuple(sorted(row["columns"])) == tuple(sorted(expected_columns))
        and tuple(row["constraints"]) == expected_constraints
        and tuple(row["indexes"]) == expected_indexes
        and tuple(row["policies"]) == _CANONICAL_POLICIES[relation]
        and tuple(row["triggers"]) == expected_triggers
        and bool(row["force_rls"])
        and read_relation_definition_fingerprint_v1(op.get_bind(), relation)
        == _CANONICAL_DEFINITION_FINGERPRINTS[relation]
    )


def _is_canonical_schema() -> bool:
    if not all(
        _table_contract_is_exact(table_name, *expected)
        for table_name, expected in _CANONICAL_TABLES.items()
    ):
        return False
    deployment_columns = tuple(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT column_name || '|' || data_type || '|' || udt_name
                    || '|' || COALESCE(character_maximum_length::text, '')
                    || '|' || is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'knowledge'
                  AND table_name = 'projection_deployments'
                  AND column_name IN (
                    'graph_id', 'job_id', 'verification_hash', 'verified_at', 'error_code'
                  )
                ORDER BY ordinal_position
                """
            )
        )
        .scalars()
        .all()
    )
    if tuple(sorted(deployment_columns)) != tuple(
        sorted(
            (
                "graph_id|uuid|uuid||NO",
                "job_id|uuid|uuid||YES",
                "verification_hash|character varying|varchar|64|YES",
                "verified_at|timestamp with time zone|timestamptz||YES",
                "error_code|character varying|varchar|100|YES",
            )
        )
    ):
        return False
    return (
        read_relation_definition_fingerprint_v1(op.get_bind(), "knowledge.projection_deployments")
        == _CANONICAL_DEPLOYMENT_FINGERPRINT
    )


def _install_security_contract() -> None:
    op.execute(
        """DO $datariver$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
            GRANT SELECT, INSERT, UPDATE ON knowledge.source_snapshots TO datariver_app;
            GRANT SELECT, INSERT ON knowledge.source_pages,
                knowledge.source_page_embeddings, knowledge.extraction_runs,
                knowledge.graphrag_audits TO datariver_app;
            GRANT SELECT, INSERT, UPDATE ON knowledge.projection_deployments TO datariver_app;
        END IF;
        END $datariver$"""
    )


def _workspace_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE knowledge.{table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE knowledge.{table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY workspace_isolation ON knowledge.{table_name} "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = "
        "NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT or not _is_canonical_schema():
            raise RuntimeError("The Knowledge pipeline schema is only partially present.")
        _install_security_contract()
        return
    op.add_column(
        "projection_deployments",
        sa.Column("graph_id", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "projection_deployments", sa.Column("job_id", sa.Uuid(), nullable=True), schema="knowledge"
    )
    op.add_column(
        "projection_deployments",
        sa.Column("verification_hash", sa.String(length=64), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "projection_deployments",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "projection_deployments",
        sa.Column("error_code", sa.String(length=100), nullable=True),
        schema="knowledge",
    )
    op.execute(
        """UPDATE knowledge.projection_deployments AS deployment
        SET graph_id = release.graph_id
        FROM knowledge.releases AS release
        WHERE release.workspace_id = deployment.workspace_id
          AND release.id = deployment.release_id"""
    )
    op.alter_column("projection_deployments", "graph_id", nullable=False, schema="knowledge")
    op.drop_constraint(
        op.f("fk_projection_deployments_workspace_id_release_id_releases"),
        "projection_deployments",
        schema="knowledge",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_projection_deployments_workspace_id_graph_id_release_id_releases"),
        "projection_deployments",
        "releases",
        ["workspace_id", "graph_id", "release_id"],
        ["workspace_id", "graph_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="CASCADE",
    )

    op.create_table(
        "source_snapshots",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("storage_version", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "byte_size > 0 AND byte_size <= 52428800", name="ck_source_snapshots_bounded_size"
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_snapshots_content_sha256"
        ),
        sa.CheckConstraint(
            "media_type = 'application/pdf'", name="ck_source_snapshots_pdf_media_type"
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ANALYZED', 'FAILED')",
            name="ck_source_snapshots_state_vocabulary",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["knowledge.graphs.workspace_id", "knowledge.graphs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "upload_id"],
            ["integration.object_manifests.workspace_id", "integration.object_manifests.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "graph_id", "upload_id"),
        sa.UniqueConstraint("workspace_id", "id"),
        schema="knowledge",
    )
    op.create_index(
        "ix_source_snapshots_graph_created",
        "source_snapshots",
        ["graph_id", "created_at"],
        schema="knowledge",
    )
    _workspace_rls("source_snapshots")

    op.create_table(
        "source_pages",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_pages_content_sha256"
        ),
        sa.CheckConstraint("page_number > 0", name="ck_source_pages_page_number_positive"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_snapshot_id"],
            ["knowledge.source_snapshots.workspace_id", "knowledge.source_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "source_snapshot_id", "page_number"),
        schema="knowledge",
    )
    _workspace_rls("source_pages")

    op.create_table(
        "source_page_embeddings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_identity", sa.String(length=200), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint(
            "dimension > 0 AND dimension <= 16384",
            name="ck_source_page_embeddings_bounded_dimension",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_page_embeddings_content_sha256"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_snapshot_id", "page_number"],
            [
                "knowledge.source_pages.workspace_id",
                "knowledge.source_pages.source_snapshot_id",
                "knowledge.source_pages.page_number",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_snapshot_id", "page_number", "provider", "model_identity"),
        schema="knowledge",
    )
    op.create_index(
        "ix_source_page_embeddings_source",
        "source_page_embeddings",
        ["source_snapshot_id", "page_number"],
        schema="knowledge",
    )
    _workspace_rls("source_page_embeddings")

    op.create_table(
        "extraction_runs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_changeset_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("parser_config_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_binding", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("extraction_binding", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
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
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_extraction_runs_input_hash"),
        sa.CheckConstraint("output_hash ~ '^[0-9a-f]{64}$'", name="ck_extraction_runs_output_hash"),
        sa.CheckConstraint(
            "state IN ('SUCCEEDED', 'FAILED')", name="ck_extraction_runs_state_vocabulary"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["knowledge.graphs.workspace_id", "knowledge.graphs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "proposed_changeset_id"],
            ["knowledge.changesets.workspace_id", "knowledge.changesets.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_snapshot_id"],
            ["knowledge.source_snapshots.workspace_id", "knowledge.source_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        schema="knowledge",
    )
    op.create_index(
        "ix_extraction_runs_graph_created",
        "extraction_runs",
        ["graph_id", "created_at"],
        schema="knowledge",
    )
    _workspace_rls("extraction_runs")

    op.create_table(
        "graphrag_audits",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("question_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("cited_evidence_ids", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_identity", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=200), nullable=False),
        sa.Column("tool_schema_version", sa.String(length=200), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
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
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_graphrag_audits_input_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_graphrag_audits_output_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "question_sha256 ~ '^[0-9a-f]{64}$'", name="ck_graphrag_audits_question_sha256"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "release_id"],
            [
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "request_id"),
        schema="knowledge",
    )
    op.create_index(
        "ix_graphrag_audits_release_created",
        "graphrag_audits",
        ["release_id", "created_at"],
        schema="knowledge",
    )
    _workspace_rls("graphrag_audits")

    _install_security_contract()


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical Knowledge pipeline schema.
    pass
