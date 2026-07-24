"""Initial canonical schemas.

Revision ID: 0001
Revises:
Create Date: 2026-07-14
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql


revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
        op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
        op.execute('CREATE SCHEMA IF NOT EXISTS platform')
        op.execute('CREATE SCHEMA IF NOT EXISTS iam')
        op.execute('CREATE SCHEMA IF NOT EXISTS authz')
        op.execute('CREATE SCHEMA IF NOT EXISTS catalog')
        op.execute('CREATE SCHEMA IF NOT EXISTS governance')
        op.execute('CREATE SCHEMA IF NOT EXISTS integration')
        op.execute('CREATE SCHEMA IF NOT EXISTS knowledge')
        op.execute('CREATE SCHEMA IF NOT EXISTS assistant')
        op.execute('CREATE SCHEMA IF NOT EXISTS sharing')
        op.execute('CREATE SCHEMA IF NOT EXISTS retention')
        op.create_table('policy_decisions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('resource_id', sa.Uuid(), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('effect', sa.String(length=10), nullable=False),
        sa.Column('reason_codes', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('policy_versions', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('evaluation_context', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('request_id', sa.String(length=100), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_policy_decisions')),
        schema='authz'
        )
        op.create_index('ix_policy_decisions_workspace_time', 'policy_decisions', ['workspace_id', 'decided_at'], unique=False, schema='authz')
        op.create_index('ux_policy_decisions_source_analysis_finalization', 'policy_decisions', ['workspace_id', 'request_id', 'action'], unique=True, schema='authz', postgresql_where=sa.text("evaluation_context ->> 'kind' = 'knowledge_source_job_finalization'"))
        op.execute('ALTER TABLE authz.policy_decisions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE authz.policy_decisions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON authz.policy_decisions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('resources',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('resource_type', sa.String(length=100), nullable=False),
        sa.Column('resource_key', sa.String(length=500), nullable=False),
        sa.Column('owner_department_id', sa.Uuid(), nullable=True),
        sa.Column('system_id', sa.Uuid(), nullable=True),
        sa.Column('domain_id', sa.Uuid(), nullable=True),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('lifecycle', sa.String(length=50), nullable=False),
        sa.Column('attributes', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_resources')),
        sa.UniqueConstraint('workspace_id', 'resource_type', 'resource_key', name=op.f('uq_resources_workspace_id_resource_type_resource_key')),
        schema='authz'
        )
        op.create_index('ix_resources_scope', 'resources', ['workspace_id', 'classification', 'system_id', 'domain_id'], unique=False, schema='authz')
        op.execute('ALTER TABLE authz.resources ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE authz.resources FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON authz.resources USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('assets_projection',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('external_urn', sa.Text(), nullable=False),
        sa.Column('urn_hash', sa.String(length=64), nullable=False),
        sa.Column('asset_type', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('description_truncated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('search_vector', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple'::regconfig, coalesce(name, '') || ' ' || coalesce(description, ''))", persisted=True), nullable=False),
        sa.Column('platform', sa.String(length=100), nullable=True),
        sa.Column('database_name', sa.String(length=255), nullable=True),
        sa.Column('schema_name', sa.String(length=255), nullable=True),
        sa.Column('owner_ref', sa.String(length=1000), nullable=True),
        sa.Column('domain_ref', sa.String(length=1000), nullable=True),
        sa.Column('tags', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('tags_truncated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('glossary_terms', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('glossary_terms_truncated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('column_names', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('column_names_truncated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('source_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('domain_id', sa.Uuid(), nullable=True),
        sa.Column('system_id', sa.Uuid(), nullable=True),
        sa.Column('owner_department_id', sa.Uuid(), nullable=True),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('lifecycle', sa.String(length=50), nullable=False),
        sa.Column('source_version', sa.String(length=255), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_sync_id', sa.Uuid(), nullable=True),
        sa.Column('projection_source', sa.String(length=32), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("jsonb_typeof(column_names) = 'array'", name=op.f('ck_assets_projection_column_names_array')),
        sa.CheckConstraint("jsonb_typeof(glossary_terms) = 'array'", name=op.f('ck_assets_projection_glossary_terms_array')),
        sa.CheckConstraint("jsonb_typeof(tags) = 'array'", name=op.f('ck_assets_projection_tags_array')),
        sa.CheckConstraint('NOT jsonb_path_exists(column_names, \'$[*] ? (@.type() != "string")\')', name=op.f('ck_assets_projection_column_names_string_items')),
        sa.CheckConstraint('NOT jsonb_path_exists(glossary_terms, \'$[*] ? (@.type() != "string")\')', name=op.f('ck_assets_projection_glossary_terms_string_items')),
        sa.CheckConstraint('NOT jsonb_path_exists(tags, \'$[*] ? (@.type() != "string")\')', name=op.f('ck_assets_projection_tags_string_items')),
        sa.CheckConstraint('char_length(external_urn) BETWEEN 1 AND 4096', name=op.f('ck_assets_projection_external_urn_bounded')),
        sa.CheckConstraint('description IS NULL OR char_length(description) <= 10000', name=op.f('ck_assets_projection_description_bounded')),
        sa.CheckConstraint('jsonb_array_length(column_names) <= 1000', name=op.f('ck_assets_projection_column_names_bounded')),
        sa.CheckConstraint('jsonb_array_length(glossary_terms) <= 100', name=op.f('ck_assets_projection_glossary_terms_bounded')),
        sa.CheckConstraint('jsonb_array_length(tags) <= 100', name=op.f('ck_assets_projection_tags_bounded')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_assets_projection')),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_assets_projection_workspace_id'),
        sa.UniqueConstraint('workspace_id', 'urn_hash', name=op.f('uq_assets_projection_workspace_id_urn_hash')),
        schema='catalog'
        )
        op.create_index('ix_assets_projection_active_scope_order', 'assets_projection', ['workspace_id', 'classification', 'name', 'id'], unique=False, schema='catalog', postgresql_where=sa.text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"))
        op.create_index('ix_assets_projection_name_lower_prefix_active', 'assets_projection', [sa.literal_column('lower(name)').label('name_lower')], unique=False, schema='catalog', postgresql_ops={'name_lower': 'text_pattern_ops'}, postgresql_where=sa.text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"))
        op.create_index('ix_assets_projection_name_trgm_active', 'assets_projection', ['name'], unique=False, schema='catalog', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'}, postgresql_where=sa.text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"))
        op.create_index('ix_assets_projection_scope', 'assets_projection', ['workspace_id', 'classification', 'system_id', 'domain_id'], unique=False, schema='catalog')
        op.create_index('ix_assets_projection_search_fts_active', 'assets_projection', ['search_vector'], unique=False, schema='catalog', postgresql_using='gin', postgresql_where=sa.text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"))
        op.create_index('ix_assets_projection_tree_active', 'assets_projection', ['workspace_id', 'platform', 'database_name', 'schema_name', 'name', 'id'], unique=False, schema='catalog', postgresql_where=sa.text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"))
        op.execute('ALTER TABLE catalog.assets_projection ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE catalog.assets_projection FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON catalog.assets_projection USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('sync_runs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('sync_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('next_offset', sa.Integer(), nullable=False),
        sa.Column('next_cursor', sa.Text(), nullable=True),
        sa.Column('expected_total', sa.BigInteger(), nullable=True),
        sa.Column('seen_count', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('snapshot_consistent', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('snapshot_evidence_reference', sa.String(length=500), nullable=True),
        sa.Column('snapshot_contract_hash', sa.String(length=64), nullable=True),
        sa.Column('snapshot_provider_version', sa.String(length=128), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(NOT snapshot_consistent AND snapshot_evidence_reference IS NULL AND snapshot_contract_hash IS NULL AND snapshot_provider_version IS NULL) OR (snapshot_consistent AND snapshot_evidence_reference IS NOT NULL AND snapshot_contract_hash IS NOT NULL AND snapshot_provider_version IS NOT NULL AND char_length(snapshot_evidence_reference) BETWEEN 1 AND 500 AND snapshot_contract_hash ~ '^[0-9a-f]{64}$' AND char_length(snapshot_provider_version) BETWEEN 1 AND 128)", name=op.f('ck_sync_runs_snapshot_evidence_bounded')),
        sa.CheckConstraint('expected_total IS NULL OR expected_total >= 0', name=op.f('ck_sync_runs_expected_total_nonnegative')),
        sa.CheckConstraint('next_cursor IS NULL OR char_length(next_cursor) BETWEEN 1 AND 4096', name=op.f('ck_sync_runs_next_cursor_bounded')),
        sa.CheckConstraint('next_offset >= 0', name=op.f('ck_sync_runs_next_offset_nonnegative')),
        sa.CheckConstraint('seen_count >= 0', name=op.f('ck_sync_runs_seen_count_nonnegative')),
        sa.PrimaryKeyConstraint('workspace_id', 'sync_id', name=op.f('pk_sync_runs')),
        schema='catalog'
        )
        op.create_index('ix_catalog_sync_runs_workspace_state', 'sync_runs', ['workspace_id', 'state', 'started_at'], unique=False, schema='catalog')
        op.execute('ALTER TABLE catalog.sync_runs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE catalog.sync_runs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON catalog.sync_runs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('change_requests',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('number', sa.String(length=100), nullable=False),
        sa.Column('request_type', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('requester_department_id', sa.Uuid(), nullable=True),
        sa.Column('current_round_id', sa.Uuid(), nullable=False),
        sa.Column('current_round_number', sa.Integer(), nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('requested_due_date', sa.Date(), nullable=True),
        sa.Column('priority', sa.String(length=16), nullable=True),
        sa.Column('urgency', sa.String(length=16), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("priority IS NULL OR priority IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')", name=op.f('ck_change_requests_priority_vocabulary')),
        sa.CheckConstraint("urgency IS NULL OR urgency IN ('NORMAL', 'URGENT', 'EMERGENCY')", name=op.f('ck_change_requests_urgency_vocabulary')),
        sa.ForeignKeyConstraint(['workspace_id', 'id', 'current_round_id'], ['governance.change_request_rounds.workspace_id', 'governance.change_request_rounds.change_request_id', 'governance.change_request_rounds.id'], name='fk_change_requests_current_round', initially='DEFERRED', deferrable=True, use_alter=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_requests')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_change_requests_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'number', name=op.f('uq_change_requests_workspace_id_number')),
        schema='governance'
        )
        op.create_index('ix_change_requests_workspace_created_id', 'change_requests', ['workspace_id', 'created_at', 'id'], unique=False, schema='governance')
        op.create_index('ix_change_requests_workspace_state', 'change_requests', ['workspace_id', 'state', 'created_at'], unique=False, schema='governance')
        op.create_index('ix_change_requests_workspace_state_created_id', 'change_requests', ['workspace_id', 'state', 'created_at', 'id'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.change_requests ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.change_requests FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.change_requests USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('subjects',
        sa.Column('issuer', sa.String(length=500), nullable=False),
        sa.Column('external_subject', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_login_ip', sa.String(length=64), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_subjects')),
        sa.UniqueConstraint('issuer', 'external_subject', name=op.f('uq_subjects_issuer_external_subject')),
        schema='iam'
        )
        op.create_index('ix_subjects_display_name_lower_id', 'subjects', [sa.literal_column('lower(display_name)'), 'id'], unique=False, schema='iam')
        op.create_table('idempotency_keys',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('operation', sa.String(length=100), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('workspace_id', 'operation', 'key_hash', name=op.f('pk_idempotency_keys')),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.idempotency_keys ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.idempotency_keys FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.idempotency_keys USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('inbox_messages',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('consumer', sa.String(length=100), nullable=False),
        sa.Column('event_id', sa.Uuid(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('result_hash', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('consumer', 'event_id', name=op.f('pk_inbox_messages')),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.inbox_messages ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.inbox_messages FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.inbox_messages USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('object_manifests',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('bucket', sa.String(length=255), nullable=False),
        sa.Column('object_key', sa.Text(), nullable=False),
        sa.Column('display_name', sa.String(length=500), nullable=False),
        sa.Column('multipart_upload_id', sa.Text(), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('mime', sa.String(length=255), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('actual_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('actual_mime', sa.String(length=255), nullable=True),
        sa.Column('actual_sha256', sa.String(length=64), nullable=True),
        sa.Column('processing_lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processing_attempts', sa.Integer(), nullable=False),
        sa.Column('validation_attempts', sa.Integer(), nullable=False),
        sa.Column('last_error_code', sa.String(length=100), nullable=True),
        sa.Column('validation_summary', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('completion_parts', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('content_profile', sa.String(length=100), server_default='FORMAT_ONLY_V1', nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('retention_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("content_profile IN ('FORMAT_ONLY_V1', 'DATASET_DESCRIPTION_CSV_V1', 'DATASET_DESCRIPTION_XLSX_V1', 'CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')", name=op.f('ck_object_manifests_content_profile_allowlist')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_object_manifests')),
        sa.UniqueConstraint('bucket', 'object_key', name=op.f('uq_object_manifests_bucket_object_key')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_object_manifests_workspace_id_id')),
        schema='integration'
        )
        op.create_index('ix_object_manifests_workspace_state', 'object_manifests', ['workspace_id', 'state'], unique=False, schema='integration')
        op.execute('ALTER TABLE integration.object_manifests ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.object_manifests FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.object_manifests USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('outbox_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('aggregate_type', sa.String(length=100), nullable=False),
        sa.Column('aggregate_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=200), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dead_lettered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error_code', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox_events')),
        schema='integration'
        )
        op.create_index('ix_outbox_unpublished', 'outbox_events', ['published_at', 'lease_until', 'created_at'], unique=False, schema='integration')
        op.create_index('ux_outbox_source_analysis_transition', 'outbox_events', ['workspace_id', 'aggregate_id', 'event_type', sa.literal_column("(payload ->> 'version')")], unique=True, schema='integration', postgresql_where=sa.text("aggregate_type = 'knowledge_source_analysis_job'"))
        op.execute('ALTER TABLE integration.outbox_events ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.outbox_events FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.outbox_events USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('seed_runs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('namespace', sa.String(length=200), nullable=False),
        sa.Column('pack_version', sa.String(length=100), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('row_counts', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_seed_runs')),
        sa.UniqueConstraint('workspace_id', 'namespace', 'pack_version', name=op.f('uq_seed_runs_workspace_id_namespace_pack_version')),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.seed_runs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.seed_runs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.seed_runs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('graphs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('graph_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('active_release_id', sa.Uuid(), nullable=True),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'id', 'active_release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.graph_id', 'knowledge.releases.id'], name=op.f('fk_graphs_workspace_id_id_active_release_id_releases'), use_alter=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_graphs')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_graphs_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'slug', name=op.f('uq_graphs_workspace_id_slug')),
        schema='knowledge'
        )
        op.execute('ALTER TABLE knowledge.graphs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.graphs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.graphs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('workspaces',
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('settings', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_workspaces')),
        sa.UniqueConstraint('slug', name=op.f('uq_workspaces_slug')),
        schema='platform'
        )
        op.execute('ALTER TABLE platform.workspaces ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE platform.workspaces FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON platform.workspaces USING (id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('classification_access_generations',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('generation', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('generation >= 0', name=op.f('ck_classification_access_generations_generation_nonnegative')),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_classification_access_generations_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('workspace_id', name=op.f('pk_classification_access_generations')),
        schema='authz'
        )
        op.execute('ALTER TABLE authz.classification_access_generations ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE authz.classification_access_generations FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON authz.classification_access_generations USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('projection_watermarks',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('projection_version', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.CheckConstraint('projection_version >= 0', name=op.f('ck_projection_watermarks_projection_version_nonnegative')),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_projection_watermarks_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('workspace_id', name=op.f('pk_projection_watermarks')),
        schema='catalog'
        )
        op.execute('ALTER TABLE catalog.projection_watermarks ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE catalog.projection_watermarks FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON catalog.projection_watermarks USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('vocabulary_entries',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('provider_ref', sa.String(length=1000), nullable=False),
        sa.Column('display_name', sa.String(length=500), nullable=False),
        sa.Column('lifecycle', sa.String(length=16), nullable=False),
        sa.Column('source_version', sa.String(length=255), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_sync_id', sa.Uuid(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(kind = 'DOMAIN' AND provider_ref LIKE 'urn:li:domain:%') OR (kind = 'TAG' AND provider_ref LIKE 'urn:li:tag:%') OR (kind = 'TERM' AND provider_ref LIKE 'urn:li:glossaryTerm:%')", name=op.f('ck_vocabulary_entries_provider_ref_kind')),
        sa.CheckConstraint("kind IN ('DOMAIN', 'TAG', 'TERM')", name=op.f('ck_vocabulary_entries_kind_vocabulary')),
        sa.CheckConstraint("lifecycle IN ('ACTIVE', 'INACTIVE')", name=op.f('ck_vocabulary_entries_lifecycle_vocabulary')),
        sa.CheckConstraint('char_length(display_name) BETWEEN 1 AND 500 AND display_name = btrim(display_name)', name=op.f('ck_vocabulary_entries_display_name_valid')),
        sa.CheckConstraint('char_length(source_version) BETWEEN 1 AND 255 AND source_version = btrim(source_version)', name=op.f('ck_vocabulary_entries_source_version_valid')),
        sa.CheckConstraint('observed_at <= updated_at', name=op.f('ck_vocabulary_entries_observation_time_order')),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_vocabulary_entries_workspace_id_workspaces'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_vocabulary_entries')),
        sa.UniqueConstraint('workspace_id', 'id', 'kind', name=op.f('uq_vocabulary_entries_workspace_id_id_kind')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_vocabulary_entries_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'kind', 'provider_ref', name='uq_vocabulary_entries_workspace_kind_provider_ref'),
        schema='catalog'
        )
        op.create_index('ix_vocabulary_entries_workspace_kind_lifecycle_name', 'vocabulary_entries', ['workspace_id', 'kind', 'lifecycle', 'display_name', 'id'], unique=False, schema='catalog')
        op.execute('ALTER TABLE catalog.vocabulary_entries ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE catalog.vocabulary_entries FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON catalog.vocabulary_entries USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('vocabulary_sync_runs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('sync_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False),
        sa.Column('next_offset', sa.Integer(), nullable=False),
        sa.Column('next_cursor', sa.Text(), nullable=True),
        sa.Column('expected_total', sa.BigInteger(), nullable=True),
        sa.Column('seen_count', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('snapshot_consistent', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('snapshot_evidence_reference', sa.String(length=500), nullable=True),
        sa.Column('snapshot_contract_hash', sa.String(length=64), nullable=True),
        sa.Column('snapshot_provider_version', sa.String(length=128), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(NOT snapshot_consistent AND snapshot_evidence_reference IS NULL AND snapshot_contract_hash IS NULL AND snapshot_provider_version IS NULL) OR (snapshot_consistent AND snapshot_evidence_reference IS NOT NULL AND snapshot_contract_hash IS NOT NULL AND snapshot_provider_version IS NOT NULL AND char_length(snapshot_evidence_reference) BETWEEN 1 AND 500 AND snapshot_contract_hash ~ '^[0-9a-f]{64}$' AND char_length(snapshot_provider_version) BETWEEN 1 AND 128)", name=op.f('ck_vocabulary_sync_runs_snapshot_evidence_bounded')),
        sa.CheckConstraint("kind IN ('DOMAIN', 'TAG', 'TERM')", name=op.f('ck_vocabulary_sync_runs_kind_vocabulary')),
        sa.CheckConstraint("state IN ('ACTIVE', 'COMPLETED', 'ABANDONED')", name=op.f('ck_vocabulary_sync_runs_state_vocabulary')),
        sa.CheckConstraint('expected_total IS NULL OR expected_total >= 0', name=op.f('ck_vocabulary_sync_runs_expected_total_nonnegative')),
        sa.CheckConstraint('next_cursor IS NULL OR char_length(next_cursor) BETWEEN 1 AND 4096', name=op.f('ck_vocabulary_sync_runs_next_cursor_bounded')),
        sa.CheckConstraint('next_offset >= 0', name=op.f('ck_vocabulary_sync_runs_next_offset_nonnegative')),
        sa.CheckConstraint('seen_count >= 0', name=op.f('ck_vocabulary_sync_runs_seen_count_nonnegative')),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_vocabulary_sync_runs_workspace_id_workspaces'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('workspace_id', 'sync_id', 'kind', name=op.f('pk_vocabulary_sync_runs')),
        schema='catalog'
        )
        op.create_index('ix_vocabulary_sync_runs_workspace_kind_started', 'vocabulary_sync_runs', ['workspace_id', 'kind', 'started_at'], unique=False, schema='catalog')
        op.create_index('uq_vocabulary_sync_runs_active_workspace_kind', 'vocabulary_sync_runs', ['workspace_id', 'kind'], unique=True, schema='catalog', postgresql_where=sa.text("state = 'ACTIVE'"))
        op.execute('ALTER TABLE catalog.vocabulary_sync_runs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE catalog.vocabulary_sync_runs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON catalog.vocabulary_sync_runs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('change_request_rounds',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('round_number', sa.Integer(), nullable=False),
        sa.Column('submitted_by', sa.Uuid(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('evidence_hash', sa.String(length=64), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("evidence_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_change_request_rounds_evidence_hash_valid')),
        sa.CheckConstraint('round_number > 0', name=op.f('ck_change_request_rounds_round_number_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name='fk_change_request_rounds_request', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_request_rounds')),
        sa.UniqueConstraint('workspace_id', 'change_request_id', 'id', name=op.f('uq_change_request_rounds_workspace_id_change_request_id_id')),
        sa.UniqueConstraint('workspace_id', 'change_request_id', 'round_number', name=op.f('uq_change_request_rounds_workspace_id_change_request_id_round_number')),
        schema='governance'
        )
        op.create_index('ix_change_request_rounds_request', 'change_request_rounds', ['workspace_id', 'change_request_id'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.change_request_rounds ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.change_request_rounds FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.change_request_rounds USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('workspace_memberships',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('department_id', sa.Uuid(), nullable=True),
        sa.Column('job_function', sa.String(length=100), nullable=True),
        sa.Column('clearance', sa.Integer(), nullable=False),
        sa.Column('attributes', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('access_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['subject_id'], ['iam.subjects.id'], name=op.f('fk_workspace_memberships_subject_id_subjects'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_workspace_memberships_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('workspace_id', 'subject_id', name=op.f('pk_workspace_memberships')),
        schema='iam'
        )
        op.execute('ALTER TABLE iam.workspace_memberships ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE iam.workspace_memberships FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON iam.workspace_memberships USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('inference_provider_generations',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('generation', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('generation >= 0', name=op.f('ck_inference_provider_generations_generation_nonnegative')),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_inference_provider_generations_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('workspace_id', name=op.f('pk_inference_provider_generations')),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.inference_provider_generations ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.inference_provider_generations FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.inference_provider_generations USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('ontology_versions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.String(length=100), nullable=False),
        sa.Column('schema_document', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('checksum', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id'], ['knowledge.graphs.workspace_id', 'knowledge.graphs.id'], name=op.f('fk_ontology_versions_workspace_id_graph_id_graphs'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ontology_versions')),
        sa.UniqueConstraint('graph_id', 'version', name=op.f('uq_ontology_versions_graph_id_version')),
        sa.UniqueConstraint('workspace_id', 'graph_id', 'id', name=op.f('uq_ontology_versions_workspace_id_graph_id_id')),
        schema='knowledge'
        )
        op.execute('ALTER TABLE knowledge.ontology_versions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.ontology_versions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.ontology_versions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('source_snapshots',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('upload_id', sa.Uuid(), nullable=False),
        sa.Column('bucket', sa.String(length=255), nullable=False),
        sa.Column('object_key', sa.Text(), nullable=False),
        sa.Column('storage_version', sa.String(length=255), nullable=False),
        sa.Column('media_type', sa.String(length=100), nullable=False),
        sa.Column('byte_size', sa.BigInteger(), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_source_snapshots_content_sha256')),
        sa.CheckConstraint("media_type = 'application/pdf'", name=op.f('ck_source_snapshots_pdf_media_type')),
        sa.CheckConstraint("state IN ('PENDING', 'ANALYZED', 'FAILED')", name=op.f('ck_source_snapshots_state_vocabulary')),
        sa.CheckConstraint('byte_size > 0 AND byte_size <= 52428800', name=op.f('ck_source_snapshots_bounded_size')),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id'], ['knowledge.graphs.workspace_id', 'knowledge.graphs.id'], name=op.f('fk_source_snapshots_workspace_id_graph_id_graphs'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id', 'upload_id'], ['integration.object_manifests.workspace_id', 'integration.object_manifests.id'], name=op.f('fk_source_snapshots_workspace_id_upload_id_object_manifests'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_snapshots')),
        sa.UniqueConstraint('workspace_id', 'graph_id', 'upload_id', name=op.f('uq_source_snapshots_workspace_id_graph_id_upload_id')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_source_snapshots_workspace_id_id')),
        schema='knowledge'
        )
        op.create_index('ix_source_snapshots_graph_created', 'source_snapshots', ['graph_id', 'created_at'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.source_snapshots ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.source_snapshots FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.source_snapshots USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('data_systems',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Za-z][A-Za-z0-9_-]{1,99}$'", name=op.f('ck_data_systems_code_shape')),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_data_systems_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_data_systems')),
        sa.UniqueConstraint('workspace_id', 'code', name=op.f('uq_data_systems_workspace_id_code')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_data_systems_workspace_id_id')),
        schema='platform'
        )
        op.create_index('ix_data_systems_workspace_active_name', 'data_systems', ['workspace_id', 'active', 'name'], unique=False, schema='platform')
        op.execute('ALTER TABLE platform.data_systems ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE platform.data_systems FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON platform.data_systems USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('archive_capability_attestations',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('configuration_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('encryption_profile_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('runtime_principal_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('probe_contract_version', sa.String(length=100), nullable=False),
        sa.Column('challenge_hash', sa.String(length=64), nullable=False),
        sa.Column('object_bucket', sa.String(length=63), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('versioning_enabled', sa.Boolean(), nullable=False),
        sa.Column('object_lock_enabled', sa.Boolean(), nullable=False),
        sa.Column('compliance_retention_supported', sa.Boolean(), nullable=False),
        sa.Column('checksum_sha256_supported', sa.Boolean(), nullable=False),
        sa.Column('full_readback_verified', sa.Boolean(), nullable=False),
        sa.Column('retention_shorten_denied', sa.Boolean(), nullable=False),
        sa.Column('retained_version_delete_denied', sa.Boolean(), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('failure_code', sa.String(length=100), nullable=True),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(state = 'VERIFIED' AND failure_code IS NULL AND versioning_enabled AND object_lock_enabled AND compliance_retention_supported AND checksum_sha256_supported AND full_readback_verified AND retention_shorten_denied AND retained_version_delete_denied) OR (state = 'FAILED' AND failure_code IS NOT NULL AND length(btrim(failure_code)) BETWEEN 1 AND 100)", name=op.f('ck_archive_capability_attestations_state_shape')),
        sa.CheckConstraint("challenge_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_archive_capability_attestations_challenge_hash_sha256')),
        sa.CheckConstraint("configuration_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f('ck_archive_capability_attestations_configuration_fingerprint_sha256')),
        sa.CheckConstraint("encryption_profile_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f('ck_archive_capability_attestations_encryption_profile_fingerprint_sha256')),
        sa.CheckConstraint("expires_at > observed_at AND expires_at <= observed_at + INTERVAL '24 hours'", name=op.f('ck_archive_capability_attestations_observation_window')),
        sa.CheckConstraint("object_bucket ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'", name=op.f('ck_archive_capability_attestations_object_bucket')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_archive_capability_attestations_payload_hash_sha256')),
        sa.CheckConstraint("runtime_principal_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f('ck_archive_capability_attestations_runtime_principal_fingerprint_sha256')),
        sa.CheckConstraint("state IN ('VERIFIED', 'FAILED')", name=op.f('ck_archive_capability_attestations_state')),
        sa.CheckConstraint('length(probe_contract_version) BETWEEN 1 AND 100', name=op.f('ck_archive_capability_attestations_probe_contract_version')),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_archive_capability_attestations_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_archive_capability_attestations')),
        sa.UniqueConstraint('workspace_id', 'configuration_fingerprint', 'observed_at', name='uq_archive_capability_attestations_observation'),
        sa.UniqueConstraint('workspace_id', 'id', 'configuration_fingerprint', 'encryption_profile_fingerprint', 'runtime_principal_fingerprint', name='uq_archive_capability_attestations_workspace_id_fingerprint'),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_archive_capability_attestations_workspace_id_id'),
        schema='retention'
        )
        op.create_index('ix_archive_capability_attestations_workspace_observed', 'archive_capability_attestations', ['workspace_id', 'configuration_fingerprint', 'observed_at'], unique=False, schema='retention')
        op.execute('ALTER TABLE retention.archive_capability_attestations ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.archive_capability_attestations FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.archive_capability_attestations USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('api_products',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('current_version_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id'], ['knowledge.graphs.workspace_id', 'knowledge.graphs.id'], name=op.f('fk_api_products_workspace_id_graph_id_graphs')),
        sa.ForeignKeyConstraint(['workspace_id', 'id', 'current_version_id'], ['sharing.api_product_versions.workspace_id', 'sharing.api_product_versions.product_id', 'sharing.api_product_versions.id'], name=op.f('fk_api_products_workspace_id_id_current_version_id_api_product_versions'), use_alter=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_api_products')),
        sa.UniqueConstraint('workspace_id', 'graph_id', 'id', name=op.f('uq_api_products_workspace_id_graph_id_id')),
        sa.UniqueConstraint('workspace_id', 'slug', name=op.f('uq_api_products_workspace_id_slug')),
        schema='sharing'
        )
        op.create_index('ix_api_products_workspace_state', 'api_products', ['workspace_id', 'state', 'updated_at'], unique=False, schema='sharing')
        op.execute('ALTER TABLE sharing.api_products ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE sharing.api_products FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON sharing.api_products USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('classification_access_policy_versions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('policy_number', sa.Integer(), nullable=False),
        sa.Column('required_jurisdiction', sa.String(length=64), nullable=False),
        sa.Column('restricted_search_grant_maximum_days', sa.Integer(), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('request_reason', sa.String(length=4000), nullable=False),
        sa.Column('request_policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('checker_id', sa.Uuid(), nullable=True),
        sa.Column('decision_reason', sa.String(length=4000), nullable=True),
        sa.Column('decision_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('superseded_by', sa.Uuid(), nullable=True),
        sa.Column('supersede_reason', sa.String(length=4000), nullable=True),
        sa.Column('supersede_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'PROPOSED' AND version = 1 AND checker_id IS NULL AND decision_reason IS NULL AND decision_policy_decision_id IS NULL AND decided_at IS NULL AND superseded_by IS NULL AND supersede_reason IS NULL AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR (state IN ('ACTIVE', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND superseded_by IS NULL AND supersede_reason IS NULL AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR (state = 'SUPERSEDED' AND version = 3 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND superseded_by IS NOT NULL AND supersede_reason IS NOT NULL AND supersede_policy_decision_id IS NOT NULL AND superseded_at IS NOT NULL)", name=op.f('ck_classification_access_policy_versions_state_shape')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_classification_access_policy_versions_payload_hash_sha256')),
        sa.CheckConstraint("state IN ('PROPOSED', 'ACTIVE', 'REJECTED', 'SUPERSEDED')", name=op.f('ck_classification_access_policy_versions_state')),
        sa.CheckConstraint('checker_id IS NULL OR checker_id <> requester_id', name=op.f('ck_classification_access_policy_versions_independent_checker')),
        sa.CheckConstraint('length(btrim(request_reason)) > 0 AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND (supersede_reason IS NULL OR length(btrim(supersede_reason)) > 0)', name=op.f('ck_classification_access_policy_versions_reasons_nonempty')),
        sa.CheckConstraint('length(btrim(required_jurisdiction)) BETWEEN 1 AND 64', name=op.f('ck_classification_access_policy_versions_jurisdiction')),
        sa.CheckConstraint('policy_number > 0', name=op.f('ck_classification_access_policy_versions_policy_number_positive')),
        sa.CheckConstraint('restricted_search_grant_maximum_days BETWEEN 1 AND 365', name=op.f('ck_classification_access_policy_versions_grant_maximum_days')),
        sa.CheckConstraint('version > 0', name=op.f('ck_classification_access_policy_versions_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'checker_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_classification_policy_versions_checker_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'requester_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_classification_policy_versions_requester_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'superseded_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_classification_policy_versions_superseder_membership'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_classification_access_policy_versions_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_classification_access_policy_versions')),
        sa.UniqueConstraint('workspace_id', 'id', 'payload_hash', name='uq_classification_policy_versions_exact'),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_classification_policy_versions_workspace_id'),
        sa.UniqueConstraint('workspace_id', 'policy_number', name='uq_classification_policy_versions_number'),
        schema='authz'
        )
        op.create_index('ix_classification_policy_versions_workspace_number', 'classification_access_policy_versions', ['workspace_id', 'policy_number'], unique=False, schema='authz')
        op.create_index('uq_classification_policy_versions_workspace_active', 'classification_access_policy_versions', ['workspace_id'], unique=True, schema='authz', postgresql_where=sa.text("state = 'ACTIVE'"))
        op.execute('ALTER TABLE authz.classification_access_policy_versions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE authz.classification_access_policy_versions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON authz.classification_access_policy_versions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('export_requests',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=False),
        sa.Column('requested_by', sa.Uuid(), nullable=False),
        sa.Column('request_document', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('permission_scope_hash', sa.String(length=64), nullable=False),
        sa.Column('classification_access_hash', sa.String(length=64), nullable=False),
        sa.Column('builtin_policy_version', sa.String(length=100), nullable=False),
        sa.Column('classification_policy_id', sa.Uuid(), nullable=True),
        sa.Column('classification_policy_hash', sa.String(length=64), nullable=True),
        sa.Column('classification_policy_version', sa.Integer(), nullable=True),
        sa.Column('authorization_generation', sa.BigInteger(), nullable=True),
        sa.Column('source_projection_version', sa.BigInteger(), nullable=False),
        sa.Column('classification_ceiling', sa.Integer(), nullable=False),
        sa.Column('csv_safety_version', sa.String(length=32), nullable=False),
        sa.Column('object_bucket', sa.String(length=255), nullable=True),
        sa.Column('object_key', sa.Text(), nullable=True),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('mime', sa.String(length=100), nullable=False),
        sa.Column('row_count', sa.BigInteger(), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('content_sha256', sa.String(length=64), nullable=True),
        sa.Column('provider_checksum', sa.String(length=255), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('access_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("classification_access_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_export_requests_classification_access_hash_sha256')),
        sa.CheckConstraint("content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_export_requests_content_sha256_valid')),
        sa.CheckConstraint("permission_scope_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_export_requests_permission_scope_hash_sha256')),
        sa.CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_export_requests_request_hash_sha256')),
        sa.CheckConstraint('(classification_policy_id IS NULL AND classification_policy_hash IS NULL AND classification_policy_version IS NULL AND authorization_generation IS NULL) OR (classification_policy_id IS NOT NULL AND classification_policy_hash IS NOT NULL AND classification_policy_version IS NOT NULL AND authorization_generation IS NOT NULL)', name=op.f('ck_export_requests_classification_policy_binding_shape')),
        sa.CheckConstraint('(object_bucket IS NULL AND object_key IS NULL AND row_count IS NULL AND size_bytes IS NULL AND content_sha256 IS NULL AND completed_at IS NULL) OR (object_bucket IS NOT NULL AND object_key IS NOT NULL AND row_count IS NOT NULL AND size_bytes IS NOT NULL AND content_sha256 IS NOT NULL AND completed_at IS NOT NULL)', name=op.f('ck_export_requests_artifact_shape')),
        sa.CheckConstraint('classification_ceiling BETWEEN 0 AND 2', name=op.f('ck_export_requests_classification_ceiling_nonrestricted')),
        sa.CheckConstraint('row_count IS NULL OR row_count >= 0', name=op.f('ck_export_requests_row_count_nonnegative')),
        sa.CheckConstraint('size_bytes IS NULL OR size_bytes >= 0', name=op.f('ck_export_requests_size_bytes_nonnegative')),
        sa.CheckConstraint('source_projection_version >= 0', name=op.f('ck_export_requests_source_projection_version_nonnegative')),
        sa.ForeignKeyConstraint(['workspace_id', 'job_id'], ['integration.jobs.workspace_id', 'integration.jobs.id'], name='fk_catalog_export_requests_workspace_job', ondelete='RESTRICT', use_alter=True),
        sa.ForeignKeyConstraint(['workspace_id', 'requested_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name=op.f('fk_export_requests_workspace_id_requested_by_workspace_memberships'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_export_requests')),
        sa.UniqueConstraint('object_bucket', 'object_key', name=op.f('uq_export_requests_object_bucket_object_key')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_export_requests_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'job_id', name=op.f('uq_export_requests_workspace_id_job_id')),
        schema='catalog'
        )
        op.create_index('ix_catalog_exports_owner_time', 'export_requests', ['workspace_id', 'requested_by', 'created_at'], unique=False, schema='catalog')
        op.execute('ALTER TABLE catalog.export_requests ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE catalog.export_requests FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON catalog.export_requests USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.execute("CREATE POLICY catalog_export_owner_select ON catalog.export_requests AS RESTRICTIVE FOR SELECT USING (current_user <> 'datariver_app' OR requested_by = NULLIF(current_setting('app.subject_id', true), '')::uuid)")
        op.create_table('approvals',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('round_id', sa.Uuid(), nullable=False),
        sa.Column('stage', sa.String(length=50), nullable=False),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('authority_snapshot', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("jsonb_typeof(authority_snapshot) = 'array'", name=op.f('ck_approvals_authority_array')),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id', 'round_id'], ['governance.change_request_rounds.workspace_id', 'governance.change_request_rounds.change_request_id', 'governance.change_request_rounds.id'], name='fk_approvals_round', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name=op.f('fk_approvals_workspace_id_change_request_id_change_requests'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals')),
        sa.UniqueConstraint('change_request_id', 'round_id', 'stage', 'actor_id', name=op.f('uq_approvals_change_request_id_round_id_stage_actor_id')),
        schema='governance'
        )
        op.execute('ALTER TABLE governance.approvals ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.approvals FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.approvals USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('change_request_attachment_upload_intents',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('round_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('original_name', sa.String(length=500), nullable=False),
        sa.Column('serial_number', sa.Integer(), nullable=False),
        sa.Column('bucket', sa.String(length=255), nullable=False),
        sa.Column('object_key', sa.Text(), nullable=False),
        sa.Column('content_type', sa.String(length=255), nullable=False),
        sa.Column('expected_size_bytes', sa.Integer(), nullable=False),
        sa.Column('expected_content_sha256', sa.String(length=64), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('content_sha256', sa.String(length=64), nullable=True),
        sa.Column('provider_checksum', sa.String(length=255), nullable=True),
        sa.Column('uploaded_by', sa.Uuid(), nullable=False),
        sa.Column('stored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failure_code', sa.String(length=100), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'STARTED' AND size_bytes IS NULL AND content_sha256 IS NULL AND provider_checksum IS NULL AND stored_at IS NULL AND finalized_at IS NULL AND failed_at IS NULL AND failure_code IS NULL) OR (state = 'STORED' AND size_bytes = expected_size_bytes AND content_sha256 = expected_content_sha256 AND stored_at IS NOT NULL AND finalized_at IS NULL AND failed_at IS NULL AND failure_code IS NULL) OR (state = 'FINALIZED' AND size_bytes = expected_size_bytes AND content_sha256 = expected_content_sha256 AND stored_at IS NOT NULL AND finalized_at IS NOT NULL AND failed_at IS NULL AND failure_code IS NULL) OR (state = 'FAILED' AND size_bytes IS NULL AND content_sha256 IS NULL AND provider_checksum IS NULL AND stored_at IS NULL AND finalized_at IS NULL AND failed_at IS NOT NULL AND failure_code IS NOT NULL)", name=op.f('ck_cr_attachment_intent_shape')),
        sa.CheckConstraint("content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_cr_attachment_intent_sha')),
        sa.CheckConstraint("expected_content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_cr_attachment_intent_expected_sha')),
        sa.CheckConstraint("kind IN ('REQUEST', 'TEST')", name=op.f('ck_cr_attachment_intent_kind')),
        sa.CheckConstraint("state IN ('STARTED', 'STORED', 'FINALIZED', 'FAILED')", name=op.f('ck_cr_attachment_intent_state')),
        sa.CheckConstraint('expected_size_bytes BETWEEN 1 AND 10485760', name=op.f('ck_cr_attachment_intent_expected_size')),
        sa.CheckConstraint('serial_number BETWEEN 1 AND 999999', name=op.f('ck_cr_attachment_intent_serial')),
        sa.CheckConstraint('size_bytes IS NULL OR size_bytes BETWEEN 1 AND 10485760', name=op.f('ck_cr_attachment_intent_size')),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id', 'round_id'], ['governance.change_request_rounds.workspace_id', 'governance.change_request_rounds.change_request_id', 'governance.change_request_rounds.id'], name='fk_change_request_attachment_upload_intents_round', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name='fk_change_request_attachment_upload_intents_request', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id', 'uploaded_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_change_request_attachment_upload_intents_uploader', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_request_attachment_upload_intents')),
        sa.UniqueConstraint('bucket', 'object_key', name='uq_change_request_attachment_upload_intent_object'),
        sa.UniqueConstraint('workspace_id', 'change_request_id', 'kind', 'original_name', 'serial_number', name='uq_change_request_attachment_upload_intent_serial'),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_change_request_attachment_upload_intents_workspace_id_id')),
        schema='governance'
        )
        op.create_index('ix_change_request_attachment_upload_intents_reconcile', 'change_request_attachment_upload_intents', ['state', 'updated_at', 'id'], unique=False, schema='governance')
        op.create_index('ix_change_request_attachment_upload_intents_request', 'change_request_attachment_upload_intents', ['workspace_id', 'change_request_id'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.change_request_attachment_upload_intents ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.change_request_attachment_upload_intents FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.change_request_attachment_upload_intents USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('change_request_attachments',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('round_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('original_name', sa.String(length=500), nullable=False),
        sa.Column('serial_number', sa.Integer(), nullable=False),
        sa.Column('bucket', sa.String(length=255), nullable=False),
        sa.Column('object_key', sa.Text(), nullable=False),
        sa.Column('content_type', sa.String(length=255), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('uploaded_by', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_change_request_attachments_content_sha256_valid')),
        sa.CheckConstraint("kind IN ('REQUEST', 'TEST')", name=op.f('ck_change_request_attachments_kind_vocabulary')),
        sa.CheckConstraint('serial_number BETWEEN 1 AND 999999', name=op.f('ck_change_request_attachments_serial_number_range')),
        sa.CheckConstraint('size_bytes BETWEEN 1 AND 10485760', name=op.f('ck_change_request_attachments_size_bytes_range')),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id', 'round_id'], ['governance.change_request_rounds.workspace_id', 'governance.change_request_rounds.change_request_id', 'governance.change_request_rounds.id'], name='fk_change_request_attachments_round', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name='fk_change_request_attachments_request', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_request_attachments')),
        sa.UniqueConstraint('bucket', 'object_key', name='uq_change_request_attachment_object'),
        sa.UniqueConstraint('workspace_id', 'change_request_id', 'kind', 'original_name', 'serial_number', name='uq_change_request_attachment_serial'),
        sa.UniqueConstraint('workspace_id', 'change_request_id', 'round_id', 'id', name='uq_change_request_attachment_round_identity'),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_change_request_attachments_workspace_id_id')),
        schema='governance'
        )
        op.create_index('ix_change_request_attachments_request', 'change_request_attachments', ['workspace_id', 'change_request_id'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.change_request_attachments ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.change_request_attachments FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.change_request_attachments USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('change_request_items',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('target_type', sa.String(length=100), nullable=False),
        sa.Column('target_ref', sa.Text(), nullable=False),
        sa.Column('aspect_name', sa.String(length=255), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('operation', sa.String(length=50), nullable=False),
        sa.Column('before_hash', sa.String(length=64), nullable=True),
        sa.Column('after_document', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('after_hash', sa.String(length=64), nullable=True),
        sa.Column('target_asset_id', sa.Uuid(), nullable=True),
        sa.Column('target_asset_type', sa.String(length=100), nullable=True),
        sa.Column('target_system_id', sa.Uuid(), nullable=True),
        sa.Column('target_domain_id', sa.Uuid(), nullable=True),
        sa.Column('target_owner_department_id', sa.Uuid(), nullable=True),
        sa.Column('target_classification', sa.Integer(), nullable=True),
        sa.Column('target_lifecycle', sa.String(length=50), nullable=True),
        sa.Column('target_source_version', sa.String(length=255), nullable=True),
        sa.Column('target_observed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('target_binding_hash', sa.String(length=64), nullable=True),
        sa.Column('item_contract_hash', sa.String(length=64), nullable=True),
        sa.Column('routing_system_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("item_contract_hash IS NULL OR item_contract_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_change_request_items_item_contract_hash_sha256')),
        sa.CheckConstraint("target_binding_hash IS NULL OR target_binding_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_change_request_items_target_binding_hash_sha256')),
        sa.CheckConstraint('(target_asset_id IS NULL AND target_asset_type IS NULL AND target_system_id IS NULL AND target_domain_id IS NULL AND target_owner_department_id IS NULL AND target_classification IS NULL AND target_lifecycle IS NULL AND target_source_version IS NULL AND target_observed_at IS NULL AND target_binding_hash IS NULL) OR (target_asset_id IS NOT NULL AND target_asset_type IS NOT NULL AND target_classification IS NOT NULL AND target_lifecycle IS NOT NULL AND target_source_version IS NOT NULL AND target_observed_at IS NOT NULL AND target_binding_hash IS NOT NULL)', name=op.f('ck_change_request_items_target_binding_shape')),
        sa.CheckConstraint('target_classification IS NULL OR target_classification BETWEEN 0 AND 3', name=op.f('ck_change_request_items_target_classification_range')),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name=op.f('fk_change_request_items_workspace_id_change_request_id_change_requests'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id', 'routing_system_id'], ['platform.data_systems.workspace_id', 'platform.data_systems.id'], name='fk_change_items_routing_system', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_request_items')),
        sa.UniqueConstraint('change_request_id', 'ordinal', name=op.f('uq_change_request_items_change_request_id_ordinal')),
        sa.UniqueConstraint('workspace_id', 'change_request_id', 'id', 'aspect_name', 'before_hash', 'after_hash', 'item_contract_hash', name='uq_change_request_items_metadata_contract'),
        sa.UniqueConstraint('workspace_id', 'change_request_id', 'id', name='uq_change_request_item_request_identity'),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_change_request_items_workspace_id_id')),
        schema='governance'
        )
        op.create_index('ix_change_items_request', 'change_request_items', ['change_request_id'], unique=False, schema='governance')
        op.create_index('ix_change_items_target', 'change_request_items', ['workspace_id', 'target_asset_id', 'aspect_name'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.change_request_items ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.change_request_items FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.change_request_items USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('manual_metadata_submissions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('external_urn', sa.Text(), nullable=False),
        sa.Column('source_version', sa.String(length=255), nullable=False),
        sa.Column('provider_source_version', sa.String(length=64), nullable=False),
        sa.Column('serial_number', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('bucket', sa.String(length=255), nullable=False),
        sa.Column('object_key', sa.Text(), nullable=False),
        sa.Column('csv_sha256', sa.String(length=64), nullable=False),
        sa.Column('csv_size_bytes', sa.Integer(), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error_code', sa.String(length=100), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_epoch', sa.Integer(), nullable=False),
        sa.Column('lease_token_hash', sa.String(length=64), nullable=True),
        sa.Column('lease_owner_id', sa.Uuid(), nullable=True),
        sa.Column('lease_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'APPLIED' AND applied_at IS NOT NULL) OR (state <> 'APPLIED' AND applied_at IS NULL)", name=op.f('ck_manual_metadata_submissions_applied_at_shape')),
        sa.CheckConstraint("(state = 'APPLYING' AND lease_token_hash IS NOT NULL AND lease_owner_id IS NOT NULL AND lease_started_at IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_expires_at > lease_started_at) OR (state <> 'APPLYING' AND lease_token_hash IS NULL AND lease_owner_id IS NULL AND lease_started_at IS NULL AND lease_expires_at IS NULL)", name=op.f('ck_manual_metadata_submissions_lease_shape')),
        sa.CheckConstraint("(state = 'QUEUED' AND next_attempt_at IS NOT NULL) OR (state <> 'QUEUED' AND next_attempt_at IS NULL)", name=op.f('ck_manual_metadata_submissions_retry_schedule_shape')),
        sa.CheckConstraint("csv_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_manual_metadata_submissions_csv_sha256_valid')),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f('ck_manual_metadata_submissions_payload_object')),
        sa.CheckConstraint("lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_manual_metadata_submissions_lease_token_hash_valid')),
        sa.CheckConstraint("provider_source_version ~ '^[0-9a-f]{64}$'", name=op.f('ck_manual_metadata_submissions_provider_source_version_valid')),
        sa.CheckConstraint("state IN ('QUEUED', 'APPLYING', 'APPLIED', 'FAILED')", name=op.f('ck_manual_metadata_submissions_state_vocabulary')),
        sa.CheckConstraint('attempts <= 20', name=op.f('ck_manual_metadata_submissions_attempts_maximum')),
        sa.CheckConstraint('attempts >= 0', name=op.f('ck_manual_metadata_submissions_attempts_nonnegative')),
        sa.CheckConstraint('csv_size_bytes > 0', name=op.f('ck_manual_metadata_submissions_csv_size_bytes_positive')),
        sa.CheckConstraint('lease_epoch = attempts', name=op.f('ck_manual_metadata_submissions_lease_epoch_matches_attempts')),
        sa.CheckConstraint('row_count > 0', name=op.f('ck_manual_metadata_submissions_row_count_positive')),
        sa.CheckConstraint('serial_number > 0', name=op.f('ck_manual_metadata_submissions_serial_number_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'asset_id'], ['catalog.assets_projection.workspace_id', 'catalog.assets_projection.id'], name='fk_manual_metadata_submissions_asset', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'lease_owner_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_manual_metadata_submissions_lease_owner', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'requester_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_manual_metadata_submissions_requester', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_manual_metadata_submissions')),
        sa.UniqueConstraint('bucket', 'object_key', name=op.f('uq_manual_metadata_submissions_bucket_object_key')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_manual_metadata_submissions_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'serial_number', name=op.f('uq_manual_metadata_submissions_workspace_id_serial_number')),
        schema='governance'
        )
        op.create_index('ix_manual_metadata_submissions_claim', 'manual_metadata_submissions', ['workspace_id', 'next_attempt_at', 'created_at', 'id'], unique=False, schema='governance', postgresql_where=sa.text("state = 'QUEUED'"))
        op.create_index('ix_manual_metadata_submissions_requester', 'manual_metadata_submissions', ['workspace_id', 'requester_id', 'created_at', 'id'], unique=False, schema='governance')
        op.create_index('ix_manual_metadata_submissions_workspace_state', 'manual_metadata_submissions', ['workspace_id', 'state', 'created_at'], unique=False, schema='governance')
        op.create_index('uq_manual_metadata_submissions_active_asset', 'manual_metadata_submissions', ['workspace_id', 'asset_id'], unique=True, schema='governance', postgresql_where=sa.text("state = 'APPLYING'"))
        op.execute('ALTER TABLE governance.manual_metadata_submissions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.manual_metadata_submissions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.manual_metadata_submissions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('state_transitions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('round_id', sa.Uuid(), nullable=False),
        sa.Column('from_state', sa.String(length=32), nullable=False),
        sa.Column('to_state', sa.String(length=32), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id', 'round_id'], ['governance.change_request_rounds.workspace_id', 'governance.change_request_rounds.change_request_id', 'governance.change_request_rounds.id'], name='fk_state_transitions_round', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name=op.f('fk_state_transitions_workspace_id_change_request_id_change_requests'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_state_transitions')),
        schema='governance'
        )
        op.create_index('ix_state_transitions_request_time', 'state_transitions', ['change_request_id', 'occurred_at'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.state_transitions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.state_transitions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.state_transitions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('access_roles',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('role_key', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('clearance', sa.Integer(), nullable=False),
        sa.Column('groups', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('allowed_actions', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('denied_actions', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('allowed_system_ids', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('allowed_domain_ids', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('updated_by', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("role_key ~ '^[a-z][a-z0-9-]{1,79}$'", name=op.f('ck_access_roles_role_key_shape')),
        sa.CheckConstraint('clearance BETWEEN 0 AND 3', name=op.f('ck_access_roles_clearance_range')),
        sa.ForeignKeyConstraint(['workspace_id', 'updated_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_access_roles_updater', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_access_roles_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_access_roles')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_access_roles_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'role_key', name=op.f('uq_access_roles_workspace_id_role_key')),
        schema='iam'
        )
        op.create_index('ix_access_roles_workspace_active_name', 'access_roles', ['workspace_id', 'active', 'name'], unique=False, schema='iam')
        op.execute('ALTER TABLE iam.access_roles ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE iam.access_roles FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON iam.access_roles USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('admin_access_requests',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('request_reason', sa.String(length=4000), nullable=False),
        sa.Column('request_policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('target_subject_id', sa.Uuid(), nullable=False),
        sa.Column('command_type', sa.String(length=100), nullable=False),
        sa.Column('command_document', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('checker_id', sa.Uuid(), nullable=True),
        sa.Column('consumed_by', sa.Uuid(), nullable=True),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consume_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'PENDING' AND checker_id IS NULL AND consumed_by IS NULL AND consumed_at IS NULL AND consume_policy_decision_id IS NULL) OR (state IN ('APPROVED', 'REJECTED') AND checker_id IS NOT NULL AND consumed_by IS NULL AND consumed_at IS NULL AND consume_policy_decision_id IS NULL) OR (state = 'CONSUMED' AND checker_id IS NOT NULL AND consumed_by = requester_id AND consumed_at IS NOT NULL AND consume_policy_decision_id IS NOT NULL)", name=op.f('ck_admin_access_requests_state_shape')),
        sa.CheckConstraint("command_type = 'WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1'", name=op.f('ck_admin_access_requests_typed_command')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_admin_access_requests_payload_hash_sha256')),
        sa.CheckConstraint("state IN ('PENDING', 'APPROVED', 'REJECTED', 'CONSUMED')", name=op.f('ck_admin_access_requests_state')),
        sa.CheckConstraint('checker_id IS NULL OR (checker_id <> requester_id AND checker_id <> target_subject_id)', name=op.f('ck_admin_access_requests_independent_checker')),
        sa.CheckConstraint('consumed_by IS NULL OR consumed_by = requester_id', name=op.f('ck_admin_access_requests_maker_consumes')),
        sa.CheckConstraint('expires_at > created_at', name=op.f('ck_admin_access_requests_expiry_after_create')),
        sa.CheckConstraint('requester_id <> target_subject_id', name=op.f('ck_admin_access_requests_no_self_benefit')),
        sa.CheckConstraint('version > 0', name=op.f('ck_admin_access_requests_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'checker_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_admin_access_requests_checker_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'requester_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_admin_access_requests_requester_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'target_subject_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_admin_access_requests_target_membership'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_admin_access_requests_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_access_requests')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_admin_access_requests_workspace_id_id')),
        schema='iam'
        )
        op.create_index('ix_admin_access_requests_workspace_state', 'admin_access_requests', ['workspace_id', 'state', 'expires_at'], unique=False, schema='iam')
        op.execute('ALTER TABLE iam.admin_access_requests ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE iam.admin_access_requests FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON iam.admin_access_requests USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('membership_renewal_requests',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('target_subject_id', sa.Uuid(), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('reason', sa.String(length=4000), nullable=False),
        sa.Column('current_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('requested_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('checker_id', sa.Uuid(), nullable=True),
        sa.Column('decision_reason', sa.String(length=4000), nullable=True),
        sa.Column('decision_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'PENDING' AND checker_id IS NULL AND decision_reason IS NULL AND decision_policy_decision_id IS NULL AND decided_at IS NULL) OR (state IN ('APPROVED', 'REJECTED') AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL)", name=op.f('ck_membership_renewal_requests_state_shape')),
        sa.CheckConstraint("state IN ('PENDING', 'APPROVED', 'REJECTED')", name=op.f('ck_membership_renewal_requests_state')),
        sa.CheckConstraint('checker_id IS NULL OR checker_id <> target_subject_id', name=op.f('ck_membership_renewal_requests_independent_checker')),
        sa.CheckConstraint('requested_expires_at > current_expires_at', name=op.f('ck_membership_renewal_requests_extension_positive')),
        sa.CheckConstraint('requester_id = target_subject_id', name=op.f('ck_membership_renewal_requests_self_request')),
        sa.ForeignKeyConstraint(['workspace_id', 'checker_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_membership_renewals_checker_membership', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'requester_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_membership_renewals_requester_membership', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'target_subject_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_membership_renewals_target_membership', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_membership_renewal_requests_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_renewal_requests')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_membership_renewal_requests_workspace_id_id')),
        schema='iam'
        )
        op.create_index('ix_membership_renewals_workspace_state_created', 'membership_renewal_requests', ['workspace_id', 'state', 'created_at'], unique=False, schema='iam')
        op.create_index('uq_membership_renewals_pending_subject', 'membership_renewal_requests', ['workspace_id', 'target_subject_id'], unique=True, schema='iam', postgresql_where=sa.text("state = 'PENDING'"))
        op.execute('ALTER TABLE iam.membership_renewal_requests ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE iam.membership_renewal_requests FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON iam.membership_renewal_requests USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('inference_provider_profile_versions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('profile_key', sa.String(length=128), nullable=False),
        sa.Column('profile_version', sa.Integer(), nullable=False),
        sa.Column('server_route_key', sa.String(length=128), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('provider_identity', sa.String(length=256), nullable=False),
        sa.Column('model_identity', sa.String(length=256), nullable=False),
        sa.Column('deployment_identity', sa.String(length=256), nullable=False),
        sa.Column('jurisdiction', sa.String(length=64), nullable=False),
        sa.Column('region', sa.String(length=64), nullable=False),
        sa.Column('maximum_classification', sa.Integer(), nullable=False),
        sa.Column('residency_attestation_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('residency_attestation_observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('residency_attestation_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('zero_retention_attestation_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('zero_retention_attestation_observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('zero_retention_attestation_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('maker_id', sa.Uuid(), nullable=False),
        sa.Column('proposal_reason', sa.String(length=1000), nullable=False),
        sa.Column('proposal_policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('proposed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('checker_id', sa.Uuid(), nullable=True),
        sa.Column('decision_reason', sa.String(length=1000), nullable=True),
        sa.Column('decision_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by', sa.Uuid(), nullable=True),
        sa.Column('revocation_reason', sa.String(length=1000), nullable=True),
        sa.Column('revocation_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'PROPOSED' AND version = 1 AND checker_id IS NULL AND decision_reason IS NULL AND decision_policy_decision_id IS NULL AND decided_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR (state IN ('APPROVED', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND revoked_by IS NULL AND revocation_reason IS NULL AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR (state = 'REVOKED' AND version = 3 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL AND revocation_policy_decision_id IS NOT NULL AND revoked_at IS NOT NULL)", name=op.f('ck_inference_provider_profile_versions_state_shape')),
        sa.CheckConstraint("kind <> 'EXTERNAL' OR maximum_classification <= 1", name=op.f('ck_inference_provider_profile_versions_external_classification_floor')),
        sa.CheckConstraint("kind IN ('INTERNAL', 'EXTERNAL')", name=op.f('ck_inference_provider_profile_versions_kind')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_inference_provider_profile_versions_payload_hash_sha256')),
        sa.CheckConstraint("profile_key !~ '://' AND server_route_key !~ '://' AND provider_identity !~ '://' AND model_identity !~ '://' AND deployment_identity !~ '://'", name=op.f('ck_inference_provider_profile_versions_no_endpoint_values')),
        sa.CheckConstraint("residency_attestation_fingerprint ~ '^[0-9a-f]{64}$' AND zero_retention_attestation_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f('ck_inference_provider_profile_versions_attestation_hashes')),
        sa.CheckConstraint("state IN ('PROPOSED', 'APPROVED', 'REJECTED', 'REVOKED')", name=op.f('ck_inference_provider_profile_versions_state')),
        sa.CheckConstraint('checker_id IS NULL OR checker_id <> maker_id', name=op.f('ck_inference_provider_profile_versions_independent_checker')),
        sa.CheckConstraint('length(btrim(proposal_reason)) > 0 AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND (revocation_reason IS NULL OR length(btrim(revocation_reason)) > 0)', name=op.f('ck_inference_provider_profile_versions_reasons_nonempty')),
        sa.CheckConstraint('maximum_classification BETWEEN 0 AND 2', name=op.f('ck_inference_provider_profile_versions_classification')),
        sa.CheckConstraint('profile_version > 0', name=op.f('ck_inference_provider_profile_versions_profile_version_positive')),
        sa.CheckConstraint('residency_attestation_expires_at > residency_attestation_observed_at AND zero_retention_attestation_expires_at > zero_retention_attestation_observed_at', name=op.f('ck_inference_provider_profile_versions_attestation_windows')),
        sa.CheckConstraint('version > 0', name=op.f('ck_inference_provider_profile_versions_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'checker_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_inference_profile_versions_checker_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'maker_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_inference_profile_versions_maker_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'revoked_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_inference_profile_versions_revoker_membership'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_inference_provider_profile_versions_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inference_provider_profile_versions')),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_inference_profile_versions_workspace_id'),
        sa.UniqueConstraint('workspace_id', 'profile_key', 'profile_version', name='uq_inference_profile_versions_key_version'),
        schema='integration'
        )
        op.create_index('ix_inference_profile_versions_workspace_order', 'inference_provider_profile_versions', ['workspace_id', 'profile_key', sa.literal_column('profile_version DESC'), 'id'], unique=False, schema='integration')
        op.create_index('ix_inference_profile_versions_workspace_state', 'inference_provider_profile_versions', ['workspace_id', 'state', 'profile_key'], unique=False, schema='integration')
        op.execute('ALTER TABLE integration.inference_provider_profile_versions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.inference_provider_profile_versions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.inference_provider_profile_versions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('jobs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('job_type', sa.String(length=100), nullable=False),
        sa.Column('causation_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('requested_by', sa.Uuid(), nullable=False),
        sa.Column('progress', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('result_ref', sa.Text(), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('attempt_cycle', sa.Integer(), server_default='1', nullable=False),
        sa.Column('cycle_attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('lease_token_hash', sa.String(length=64), nullable=True),
        sa.Column('lease_owner_id', sa.Uuid(), nullable=True),
        sa.Column('last_error_code', sa.String(length=100), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("job_type <> 'DATAHUB_CHANGE_APPLY' OR ((state = 'RUNNING' AND lease_token_hash IS NOT NULL AND lease_owner_id IS NOT NULL AND lease_until IS NOT NULL) OR (state <> 'RUNNING' AND lease_token_hash IS NULL AND lease_owner_id IS NULL))", name=op.f('ck_jobs_governance_apply_lease_shape')),
        sa.CheckConstraint("lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_jobs_lease_token_hash_valid')),
        sa.CheckConstraint('attempt_cycle > 0 AND cycle_attempts >= 0 AND attempts >= cycle_attempts', name=op.f('ck_jobs_attempt_counters_valid')),
        sa.ForeignKeyConstraint(['workspace_id', 'lease_owner_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_jobs_workspace_lease_owner', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs')),
        sa.UniqueConstraint('job_type', 'causation_id', name=op.f('uq_jobs_job_type_causation_id')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_jobs_workspace_id_id')),
        schema='integration'
        )
        op.create_index('ix_jobs_workspace_state', 'jobs', ['workspace_id', 'state', 'created_at'], unique=False, schema='integration')
        op.execute('ALTER TABLE integration.jobs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.jobs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.jobs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('registration_worker_call_receipts',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('operation', sa.String(length=100), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('worker_subject_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('work_kind', sa.String(length=16), nullable=True),
        sa.Column('work_id', sa.Uuid(), nullable=True),
        sa.Column('claim_attempt', sa.Integer(), nullable=True),
        sa.Column('claim_token_hash', sa.String(length=64), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed', sa.Boolean(), nullable=True),
        sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(state = 'RUNNING' AND processed IS NULL AND result IS NULL AND work_kind IN ('MANUAL', 'BULK') AND work_id IS NOT NULL AND claim_attempt IS NOT NULL AND claim_attempt > 0 AND claim_token_hash IS NOT NULL AND lease_expires_at IS NOT NULL) OR (state = 'COMPLETED' AND processed IS NOT NULL AND result IS NOT NULL AND claim_token_hash IS NULL AND lease_expires_at IS NULL)", name=op.f('ck_registration_worker_call_receipts_state_shape')),
        sa.CheckConstraint("claim_token_hash IS NULL OR claim_token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_registration_worker_call_receipts_claim_token_hash_valid')),
        sa.CheckConstraint("operation IN ('registration.manual-metadata.apply-run.v1', 'registration.bulk-preparation.execute-run.v1')", name=op.f('ck_registration_worker_call_receipts_operation_allowlist')),
        sa.CheckConstraint("request_hash ~ '^[0-9a-f]{64}$' AND key_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_registration_worker_call_receipts_identity_hashes_valid')),
        sa.CheckConstraint("state IN ('RUNNING', 'COMPLETED')", name=op.f('ck_registration_worker_call_receipts_state_allowlist')),
        sa.ForeignKeyConstraint(['workspace_id', 'worker_subject_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_registration_worker_call_receipts_subject', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('workspace_id', 'operation', 'key_hash', name=op.f('pk_registration_worker_call_receipts')),
        schema='integration'
        )
        op.create_index('ix_registration_worker_call_receipts_running_lease', 'registration_worker_call_receipts', ['lease_expires_at'], unique=False, schema='integration', postgresql_where=sa.text("state = 'RUNNING'"))
        op.execute('ALTER TABLE integration.registration_worker_call_receipts ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.registration_worker_call_receipts FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.registration_worker_call_receipts USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('upload_preparation_jobs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('upload_id', sa.Uuid(), nullable=False),
        sa.Column('requested_by', sa.Uuid(), nullable=False),
        sa.Column('content_profile', sa.String(length=100), nullable=False),
        sa.Column('source_manifest_version', sa.Integer(), nullable=False),
        sa.Column('source_sha256', sa.String(length=64), nullable=False),
        sa.Column('configuration_hash', sa.String(length=64), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_token', sa.Uuid(), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('rows_processed', sa.BigInteger(), nullable=False),
        sa.Column('total_rows', sa.BigInteger(), nullable=True),
        sa.Column('last_error_code', sa.String(length=100), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'PREPARING' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR (state <> 'PREPARING' AND lease_token IS NULL AND lease_until IS NULL)", name=op.f('ck_upload_preparation_jobs_lease_shape')),
        sa.CheckConstraint("(state = 'QUEUED' AND next_attempt_at IS NOT NULL) OR (state <> 'QUEUED' AND next_attempt_at IS NULL)", name=op.f('ck_upload_preparation_jobs_retry_schedule_shape')),
        sa.CheckConstraint("configuration_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_jobs_configuration_hash_valid')),
        sa.CheckConstraint("content_profile IN ('DATASET_DESCRIPTION_CSV_V1', 'DATASET_DESCRIPTION_XLSX_V1', 'CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')", name=op.f('ck_upload_preparation_jobs_typed_profile_allowlist')),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_jobs_source_sha256_valid')),
        sa.CheckConstraint("state IN ('QUEUED', 'PREPARING', 'READY', 'FAILED', 'CANCELLED', 'STALE')", name=op.f('ck_upload_preparation_jobs_state_allowlist')),
        sa.CheckConstraint('attempts >= 0', name=op.f('ck_upload_preparation_jobs_attempts_nonnegative')),
        sa.CheckConstraint('rows_processed >= 0', name=op.f('ck_upload_preparation_jobs_rows_processed_nonnegative')),
        sa.CheckConstraint('source_manifest_version > 0', name=op.f('ck_upload_preparation_jobs_source_manifest_version_positive')),
        sa.CheckConstraint('total_rows IS NULL OR total_rows >= rows_processed', name=op.f('ck_upload_preparation_jobs_total_rows_bounds')),
        sa.ForeignKeyConstraint(['workspace_id', 'requested_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_upload_prep_jobs_workspace_requester', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'upload_id'], ['integration.object_manifests.workspace_id', 'integration.object_manifests.id'], name='fk_upload_prep_jobs_workspace_upload', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_preparation_jobs')),
        sa.UniqueConstraint('workspace_id', 'id', 'upload_id', 'source_manifest_version', 'source_sha256', 'content_profile', 'configuration_hash', name='uq_upload_preparation_job_source_evidence'),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_upload_preparation_jobs_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'upload_id', 'source_manifest_version', 'content_profile', 'configuration_hash', name='uq_upload_preparation_job_source_configuration'),
        schema='integration'
        )
        op.create_index('ix_upload_preparation_jobs_claim', 'upload_preparation_jobs', ['state', 'next_attempt_at', 'lease_until', 'created_at'], unique=False, schema='integration')
        op.execute('ALTER TABLE integration.upload_preparation_jobs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.upload_preparation_jobs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.upload_preparation_jobs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('changesets',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('base_release_id', sa.Uuid(), nullable=True),
        sa.Column('ontology_version_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('author_id', sa.Uuid(), nullable=False),
        sa.Column('source_analysis_job_id', sa.Uuid(), nullable=True),
        sa.Column('reviewed_by', sa.Uuid(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_reason', sa.Text(), nullable=True),
        sa.Column('published_release_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'base_release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.graph_id', 'knowledge.releases.id'], name=op.f('fk_changesets_workspace_id_graph_id_base_release_id_releases'), use_alter=True),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'ontology_version_id'], ['knowledge.ontology_versions.workspace_id', 'knowledge.ontology_versions.graph_id', 'knowledge.ontology_versions.id'], name=op.f('fk_changesets_workspace_id_graph_id_ontology_version_id_ontology_versions')),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'published_release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.graph_id', 'knowledge.releases.id'], name=op.f('fk_changesets_workspace_id_graph_id_published_release_id_releases'), use_alter=True),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id'], ['knowledge.graphs.workspace_id', 'knowledge.graphs.id'], name=op.f('fk_changesets_workspace_id_graph_id_graphs'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id', 'source_analysis_job_id'], ['knowledge.source_analysis_jobs.workspace_id', 'knowledge.source_analysis_jobs.id'], name=op.f('fk_changesets_workspace_id_source_analysis_job_id_source_analysis_jobs'), ondelete='RESTRICT', use_alter=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_changesets')),
        sa.UniqueConstraint('workspace_id', 'graph_id', 'id', name=op.f('uq_changesets_workspace_id_graph_id_id')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_changesets_workspace_id_id')),
        schema='knowledge'
        )
        op.create_index('ix_changesets_graph_state', 'changesets', ['graph_id', 'state', 'created_at'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.changesets ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.changesets FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.changesets USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('releases',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('release_no', sa.Integer(), nullable=False),
        sa.Column('ontology_version_id', sa.Uuid(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('node_count', sa.Integer(), nullable=False),
        sa.Column('edge_count', sa.Integer(), nullable=False),
        sa.Column('manifest_ref', sa.Text(), nullable=True),
        sa.Column('published_by', sa.Uuid(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deprecated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'ontology_version_id'], ['knowledge.ontology_versions.workspace_id', 'knowledge.ontology_versions.graph_id', 'knowledge.ontology_versions.id'], name=op.f('fk_releases_workspace_id_graph_id_ontology_version_id_ontology_versions')),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id'], ['knowledge.graphs.workspace_id', 'knowledge.graphs.id'], name=op.f('fk_releases_workspace_id_graph_id_graphs'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_releases')),
        sa.UniqueConstraint('graph_id', 'content_hash', name=op.f('uq_releases_graph_id_content_hash')),
        sa.UniqueConstraint('graph_id', 'release_no', name=op.f('uq_releases_graph_id_release_no')),
        sa.UniqueConstraint('workspace_id', 'graph_id', 'id', name=op.f('uq_releases_workspace_id_graph_id_id')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_releases_workspace_id_id')),
        schema='knowledge'
        )
        op.execute('ALTER TABLE knowledge.releases ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.releases FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.releases USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('source_analysis_jobs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('source_snapshot_id', sa.Uuid(), nullable=False),
        sa.Column('requested_by', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('requester_authorization_hash', sa.String(length=64), nullable=False),
        sa.Column('source_storage_version', sa.String(length=255), nullable=False),
        sa.Column('source_content_sha256', sa.String(length=64), nullable=False),
        sa.Column('source_classification', sa.Integer(), nullable=False),
        sa.Column('graph_version', sa.Integer(), nullable=False),
        sa.Column('base_kind', sa.String(length=20), nullable=False),
        sa.Column('base_release_id', sa.Uuid(), nullable=True),
        sa.Column('base_release_hash', sa.String(length=64), nullable=True),
        sa.Column('ontology_version_id', sa.Uuid(), nullable=False),
        sa.Column('ontology_checksum', sa.String(length=64), nullable=False),
        sa.Column('parser_config_hash', sa.String(length=64), nullable=False),
        sa.Column('embedding_binding', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('embedding_binding_hash', sa.String(length=64), nullable=False),
        sa.Column('extraction_binding', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('extraction_binding_hash', sa.String(length=64), nullable=False),
        sa.Column('pin_hash', sa.String(length=64), nullable=False),
        sa.Column('prepared_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('stage', sa.String(length=32), nullable=False),
        sa.Column('progress', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('maximum_attempts', sa.Integer(), nullable=False),
        sa.Column('lease_epoch', sa.Integer(), nullable=False),
        sa.Column('lease_token_hash', sa.String(length=64), nullable=True),
        sa.Column('lease_owner_fingerprint', sa.String(length=255), nullable=True),
        sa.Column('lease_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_requested_by', sa.Uuid(), nullable=True),
        sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_reason', sa.String(length=1000), nullable=True),
        sa.Column('result_changeset_id', sa.Uuid(), nullable=True),
        sa.Column('result_evidence_hash', sa.String(length=64), nullable=True),
        sa.Column('last_failure_code', sa.String(length=100), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("((state = 'SUCCEEDED') AND result_changeset_id IS NOT NULL AND result_evidence_hash ~ '^[0-9a-f]{64}$' AND completed_at IS NOT NULL AND last_failure_code IS NULL) OR ((state <> 'SUCCEEDED') AND result_changeset_id IS NULL AND result_evidence_hash IS NULL) ", name=op.f('ck_source_analysis_jobs_result_shape')),
        sa.CheckConstraint("((state IN ('CANCEL_REQUESTED', 'CANCELLED')) AND cancel_requested_by IS NOT NULL AND cancel_requested_at IS NOT NULL AND cancel_reason IS NOT NULL) OR ((state NOT IN ('CANCEL_REQUESTED', 'CANCELLED')) AND cancel_requested_by IS NULL AND cancel_requested_at IS NULL AND cancel_reason IS NULL)", name=op.f('ck_source_analysis_jobs_cancel_shape')),
        sa.CheckConstraint("((state IN ('FAILED', 'STALE')) AND last_failure_code IS NOT NULL AND completed_at IS NOT NULL) OR (state = 'RETRY_WAIT' AND last_failure_code IS NOT NULL AND completed_at IS NULL) OR ((state NOT IN ('FAILED', 'STALE', 'RETRY_WAIT')) AND last_failure_code IS NULL)", name=op.f('ck_source_analysis_jobs_failure_shape')),
        sa.CheckConstraint("(state IN ('QUEUED', 'RETRY_WAIT') AND stage = 'QUEUED') OR (state IN ('RUNNING', 'CANCEL_REQUESTED') AND stage IN ('SOURCE_READ', 'PARSED', 'EMBEDDED', 'EXTRACTED', 'FINALIZING')) OR (state IN ('SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED') AND stage = 'COMPLETED')", name=op.f('ck_source_analysis_jobs_execution_stage_shape')),
        sa.CheckConstraint("(state IN ('RUNNING', 'CANCEL_REQUESTED') AND lease_token_hash IS NOT NULL AND lease_owner_fingerprint IS NOT NULL AND lease_started_at IS NOT NULL AND lease_expires_at IS NOT NULL) OR (state NOT IN ('RUNNING', 'CANCEL_REQUESTED') AND lease_token_hash IS NULL AND lease_owner_fingerprint IS NULL AND lease_started_at IS NULL AND lease_expires_at IS NULL)", name=op.f('ck_source_analysis_jobs_lease_shape')),
        sa.CheckConstraint("(state IN ('SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')) = (completed_at IS NOT NULL)", name=op.f('ck_source_analysis_jobs_terminal_completion')),
        sa.CheckConstraint("(state IN ('SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')) = (stage = 'COMPLETED')", name=op.f('ck_source_analysis_jobs_terminal_stage')),
        sa.CheckConstraint("base_kind IN ('EMPTY', 'RELEASE') AND ((base_kind = 'EMPTY' AND base_release_id IS NULL AND base_release_hash IS NULL) OR (base_kind = 'RELEASE' AND base_release_id IS NOT NULL AND base_release_hash ~ '^[0-9a-f]{64}$'))", name=op.f('ck_source_analysis_jobs_base_binding_shape')),
        sa.CheckConstraint("lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_source_analysis_jobs_lease_token_hash')),
        sa.CheckConstraint("source_content_sha256 ~ '^[0-9a-f]{64}$' AND ontology_checksum ~ '^[0-9a-f]{64}$' AND parser_config_hash ~ '^[0-9a-f]{64}$' AND embedding_binding_hash ~ '^[0-9a-f]{64}$' AND extraction_binding_hash ~ '^[0-9a-f]{64}$' AND pin_hash ~ '^[0-9a-f]{64}$' AND request_hash ~ '^[0-9a-f]{64}$' AND requester_authorization_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_source_analysis_jobs_evidence_hashes')),
        sa.CheckConstraint("stage IN ('QUEUED', 'SOURCE_READ', 'PARSED', 'EMBEDDED', 'EXTRACTED', 'FINALIZING', 'COMPLETED')", name=op.f('ck_source_analysis_jobs_stage_vocabulary')),
        sa.CheckConstraint("state IN ('QUEUED', 'RUNNING', 'RETRY_WAIT', 'CANCEL_REQUESTED', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')", name=op.f('ck_source_analysis_jobs_state_vocabulary')),
        sa.CheckConstraint('graph_version > 0 AND attempt_count >= 0 AND maximum_attempts > 0 AND attempt_count <= maximum_attempts AND lease_epoch >= 0', name=op.f('ck_source_analysis_jobs_counters')),
        sa.CheckConstraint('source_classification BETWEEN 0 AND 1', name=op.f('ck_source_analysis_jobs_inference_classification')),
        sa.ForeignKeyConstraint(['workspace_id', 'cancel_requested_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name=op.f('fk_source_analysis_jobs_workspace_id_cancel_requested_by_workspace_memberships'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'base_release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.graph_id', 'knowledge.releases.id'], name=op.f('fk_source_analysis_jobs_workspace_id_graph_id_base_release_id_releases'), ondelete='RESTRICT', use_alter=True),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'ontology_version_id'], ['knowledge.ontology_versions.workspace_id', 'knowledge.ontology_versions.graph_id', 'knowledge.ontology_versions.id'], name=op.f('fk_source_analysis_jobs_workspace_id_graph_id_ontology_version_id_ontology_versions'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'result_changeset_id'], ['knowledge.changesets.workspace_id', 'knowledge.changesets.graph_id', 'knowledge.changesets.id'], name=op.f('fk_source_analysis_jobs_workspace_id_graph_id_result_changeset_id_changesets'), ondelete='RESTRICT', use_alter=True),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id'], ['knowledge.graphs.workspace_id', 'knowledge.graphs.id'], name=op.f('fk_source_analysis_jobs_workspace_id_graph_id_graphs'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'requested_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name=op.f('fk_source_analysis_jobs_workspace_id_requested_by_workspace_memberships'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'source_snapshot_id'], ['knowledge.source_snapshots.workspace_id', 'knowledge.source_snapshots.id'], name=op.f('fk_source_analysis_jobs_workspace_id_source_snapshot_id_source_snapshots'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_analysis_jobs')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_source_analysis_jobs_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'source_snapshot_id', name=op.f('uq_source_analysis_jobs_workspace_id_source_snapshot_id')),
        schema='knowledge'
        )
        op.create_index('ix_source_analysis_jobs_claim', 'source_analysis_jobs', ['workspace_id', 'next_attempt_at', 'created_at', 'id'], unique=False, schema='knowledge', postgresql_where=sa.text("state IN ('QUEUED', 'RETRY_WAIT')"))
        op.create_index('ix_source_analysis_jobs_expired', 'source_analysis_jobs', ['workspace_id', 'lease_expires_at', 'id'], unique=False, schema='knowledge', postgresql_where=sa.text("state IN ('RUNNING', 'CANCEL_REQUESTED')"))
        op.create_index('ix_source_analysis_jobs_graph_created', 'source_analysis_jobs', ['workspace_id', 'graph_id', 'created_at', 'id'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.source_analysis_jobs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.source_analysis_jobs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.source_analysis_jobs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.execute("CREATE POLICY source_analysis_job_owner_select ON knowledge.source_analysis_jobs AS RESTRICTIVE FOR SELECT TO datariver_app USING (requested_by = NULLIF(current_setting('app.subject_id', true), '')::uuid)")
        op.create_table('source_pages',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('source_snapshot_id', sa.Uuid(), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_source_pages_content_sha256')),
        sa.CheckConstraint('page_number > 0', name=op.f('ck_source_pages_page_number_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'source_snapshot_id'], ['knowledge.source_snapshots.workspace_id', 'knowledge.source_snapshots.id'], name=op.f('fk_source_pages_workspace_id_source_snapshot_id_source_snapshots'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('workspace_id', 'source_snapshot_id', 'page_number', name=op.f('pk_source_pages')),
        schema='knowledge'
        )
        op.execute('ALTER TABLE knowledge.source_pages ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.source_pages FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.source_pages USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('external_service_profiles',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('service_key', sa.String(length=32), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('endpoint_url', sa.String(length=2048), nullable=True),
        sa.Column('auth_principal', sa.String(length=255), nullable=True),
        sa.Column('secret_reference', sa.String(length=512), nullable=True),
        sa.Column('configuration_yaml', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('activated_version', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("endpoint_url ~ '^(https?|redis|rediss)://'", name=op.f('ck_external_service_profiles_endpoint_url_scheme')),
        sa.CheckConstraint("service_key IN ('DATAHUB', 'DATAHUB_FRONTEND', 'AIRFLOW', 'REDIS_CACHE', 'REDIS_DELIVERY', 'S3_STORAGE', 'LLM_CHAT_MODEL', 'LLM_EMBEDDING', 'LLM_RERANKER', 'NEO4J', 'PROMETHEUS', 'GRAFANA_DASHBOARD')", name=op.f('ck_external_service_profiles_service_key_vocabulary')),
        sa.CheckConstraint('activated_version IS NULL OR (activated_version > 0 AND activated_version <= version)', name=op.f('ck_external_service_profiles_activated_version_range')),
        sa.CheckConstraint('secret_reference IS NULL OR length(trim(secret_reference)) > 0', name=op.f('ck_external_service_profiles_secret_reference_present')),
        sa.ForeignKeyConstraint(['workspace_id', 'updated_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_external_service_profiles_updater', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_external_service_profiles_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_external_service_profiles')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_external_service_profiles_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'service_key', name=op.f('uq_external_service_profiles_workspace_id_service_key')),
        schema='platform'
        )
        op.create_index('ix_external_service_profiles_workspace_active', 'external_service_profiles', ['workspace_id', 'active'], unique=False, schema='platform')
        op.execute('ALTER TABLE platform.external_service_profiles ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE platform.external_service_profiles FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON platform.external_service_profiles USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('system_assignees',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('system_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('responsibility', sa.String(length=32), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("responsibility IN ('DEVELOPER', 'DATA_STEWARD')", name=op.f('ck_system_assignees_responsibility_vocabulary')),
        sa.CheckConstraint('priority BETWEEN 1 AND 999', name=op.f('ck_system_assignees_priority_range')),
        sa.ForeignKeyConstraint(['workspace_id', 'subject_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_system_assignees_membership', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'system_id'], ['platform.data_systems.workspace_id', 'platform.data_systems.id'], name='fk_system_assignees_system', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_system_assignees')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_system_assignees_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'system_id', 'subject_id', 'responsibility', name=op.f('uq_system_assignees_workspace_id_system_id_subject_id_responsibility')),
        schema='platform'
        )
        op.create_index('ix_system_assignees_workspace_system_id', 'system_assignees', ['workspace_id', 'system_id', 'id'], unique=False, schema='platform')
        op.create_index('ix_system_assignees_workspace_system_priority', 'system_assignees', ['workspace_id', 'system_id', 'priority'], unique=False, schema='platform')
        op.execute('ALTER TABLE platform.system_assignees ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE platform.system_assignees FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON platform.system_assignees USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('system_schema_scopes',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('system_id', sa.Uuid(), nullable=False),
        sa.Column('platform', sa.String(length=100), nullable=False),
        sa.Column('database_name', sa.String(length=255), nullable=False),
        sa.Column('schema_name', sa.String(length=255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint('length(trim(database_name)) > 0', name=op.f('ck_system_schema_scopes_database_present')),
        sa.CheckConstraint('length(trim(platform)) > 0', name=op.f('ck_system_schema_scopes_platform_present')),
        sa.CheckConstraint('length(trim(schema_name)) > 0', name=op.f('ck_system_schema_scopes_schema_present')),
        sa.ForeignKeyConstraint(['workspace_id', 'system_id'], ['platform.data_systems.workspace_id', 'platform.data_systems.id'], name='fk_system_schema_scopes_system', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_system_schema_scopes')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_system_schema_scopes_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'platform', 'database_name', 'schema_name', name=op.f('uq_system_schema_scopes_workspace_id_platform_database_name_schema_name')),
        schema='platform'
        )
        op.create_index('ix_system_schema_scopes_workspace_system', 'system_schema_scopes', ['workspace_id', 'system_id'], unique=False, schema='platform')
        op.execute('ALTER TABLE platform.system_schema_scopes ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE platform.system_schema_scopes FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON platform.system_schema_scopes USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('legal_holds',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('data_class', sa.String(length=32), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('scope_id', sa.Uuid(), nullable=True),
        sa.Column('reason', sa.String(length=4000), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('create_policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False),
        sa.Column('release_requested_by', sa.Uuid(), nullable=True),
        sa.Column('release_request_reason', sa.String(length=4000), nullable=True),
        sa.Column('release_request_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('release_checker_id', sa.Uuid(), nullable=True),
        sa.Column('release_decision_reason', sa.String(length=4000), nullable=True),
        sa.Column('release_decision_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(scope = 'WORKSPACE' AND scope_id IS NULL) OR (scope IN ('SUBJECT', 'RESOURCE') AND scope_id IS NOT NULL)", name=op.f('ck_legal_holds_scope_shape')),
        sa.CheckConstraint("(state = 'ACTIVE' AND release_requested_by IS NULL AND release_request_reason IS NULL AND release_request_policy_decision_id IS NULL AND release_checker_id IS NULL AND release_decision_reason IS NULL AND release_decision_policy_decision_id IS NULL AND released_at IS NULL) OR (state = 'RELEASE_REQUESTED' AND release_requested_by IS NOT NULL AND release_request_reason IS NOT NULL AND release_request_policy_decision_id IS NOT NULL AND release_checker_id IS NULL AND release_decision_reason IS NULL AND release_decision_policy_decision_id IS NULL AND released_at IS NULL) OR (state = 'RELEASE_REJECTED' AND release_requested_by IS NOT NULL AND release_request_reason IS NOT NULL AND release_request_policy_decision_id IS NOT NULL AND release_checker_id IS NOT NULL AND release_decision_reason IS NOT NULL AND release_decision_policy_decision_id IS NOT NULL AND released_at IS NULL) OR (state = 'RELEASED' AND release_requested_by IS NOT NULL AND release_request_reason IS NOT NULL AND release_request_policy_decision_id IS NOT NULL AND release_checker_id IS NOT NULL AND release_decision_reason IS NOT NULL AND release_decision_policy_decision_id IS NOT NULL AND released_at IS NOT NULL)", name=op.f('ck_legal_holds_state_shape')),
        sa.CheckConstraint("data_class IN ('COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA')", name=op.f('ck_legal_holds_data_class')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_legal_holds_payload_hash_sha256')),
        sa.CheckConstraint("scope <> 'SUBJECT' OR release_checker_id IS NULL OR release_checker_id <> scope_id", name=op.f('ck_legal_holds_subject_cannot_release_own_hold')),
        sa.CheckConstraint("scope IN ('WORKSPACE', 'SUBJECT', 'RESOURCE')", name=op.f('ck_legal_holds_scope')),
        sa.CheckConstraint("state IN ('ACTIVE', 'RELEASE_REQUESTED', 'RELEASE_REJECTED', 'RELEASED')", name=op.f('ck_legal_holds_state')),
        sa.CheckConstraint('length(btrim(reason)) > 0', name=op.f('ck_legal_holds_reason_nonempty')),
        sa.CheckConstraint('release_checker_id IS NULL OR release_checker_id <> release_requested_by', name=op.f('ck_legal_holds_independent_release_checker')),
        sa.CheckConstraint('version > 0', name=op.f('ck_legal_holds_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'created_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_legal_holds_creator_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'release_checker_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_legal_holds_release_checker_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'release_requested_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_legal_holds_release_requester_membership'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_legal_holds_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_legal_holds')),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_legal_holds_workspace_id_id'),
        schema='retention'
        )
        op.create_index('ix_legal_holds_workspace_blocking_scope', 'legal_holds', ['workspace_id', 'data_class', 'scope', 'scope_id'], unique=False, schema='retention', postgresql_where=sa.text("state <> 'RELEASED'"))
        op.create_index('ix_legal_holds_workspace_created_id', 'legal_holds', ['workspace_id', sa.literal_column('created_at DESC'), 'id'], unique=False, schema='retention')
        op.create_index('ix_legal_holds_workspace_state', 'legal_holds', ['workspace_id', 'state', 'updated_at'], unique=False, schema='retention')
        op.execute('ALTER TABLE retention.legal_holds ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.legal_holds FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.legal_holds USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('policy_versions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('policy_number', sa.Integer(), nullable=False),
        sa.Column('completed_operation_days', sa.Integer(), nullable=False),
        sa.Column('chat_content_days', sa.Integer(), nullable=False),
        sa.Column('audit_online_months', sa.Integer(), nullable=False),
        sa.Column('immutable_archive_years', sa.Integer(), nullable=False),
        sa.Column('contract_version', sa.String(length=32), server_default=sa.text("'SINGLE_DEADLINE_V1'"), nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('effective_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('execution_authorization_hours', sa.Integer(), nullable=True),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('request_reason', sa.String(length=4000), nullable=False),
        sa.Column('request_policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('checker_id', sa.Uuid(), nullable=True),
        sa.Column('decision_reason', sa.String(length=4000), nullable=True),
        sa.Column('decision_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('superseded_by', sa.Uuid(), nullable=True),
        sa.Column('supersede_reason', sa.String(length=4000), nullable=True),
        sa.Column('supersede_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(contract_version = 'SINGLE_DEADLINE_V1' AND effective_from IS NULL AND effective_until IS NULL AND execution_authorization_hours IS NULL) OR (contract_version = 'POLICY_BOOK_V2' AND effective_from IS NOT NULL AND (effective_until IS NULL OR effective_until > effective_from) AND execution_authorization_hours BETWEEN 1 AND 168)", name=op.f('ck_policy_versions_contract_shape')),
        sa.CheckConstraint("(state = 'DRAFT' AND checker_id IS NULL AND decision_reason IS NULL AND decision_policy_decision_id IS NULL AND decided_at IS NULL AND superseded_by IS NULL AND supersede_reason IS NULL AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR (state IN ('ACTIVE', 'REJECTED') AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND superseded_by IS NULL AND supersede_reason IS NULL AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR (state = 'SUPERSEDED' AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND superseded_by IS NOT NULL AND supersede_reason IS NOT NULL AND supersede_policy_decision_id IS NOT NULL AND superseded_at IS NOT NULL)", name=op.f('ck_policy_versions_state_shape')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_policy_versions_payload_hash_sha256')),
        sa.CheckConstraint("state IN ('DRAFT', 'ACTIVE', 'REJECTED', 'SUPERSEDED')", name=op.f('ck_policy_versions_state')),
        sa.CheckConstraint('checker_id IS NULL OR checker_id <> requester_id', name=op.f('ck_policy_versions_independent_checker')),
        sa.CheckConstraint('completed_operation_days BETWEEN 1 AND 3650 AND chat_content_days BETWEEN 1 AND 3650 AND audit_online_months BETWEEN 1 AND 120 AND immutable_archive_years BETWEEN 1 AND 100', name=op.f('ck_policy_versions_rules_supported_bounds')),
        sa.CheckConstraint('length(btrim(request_reason)) > 0 AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND (supersede_reason IS NULL OR length(btrim(supersede_reason)) > 0)', name=op.f('ck_policy_versions_reasons_nonempty')),
        sa.CheckConstraint('policy_number > 0', name=op.f('ck_policy_versions_policy_number_positive')),
        sa.CheckConstraint('version > 0', name=op.f('ck_policy_versions_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'checker_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_retention_policy_versions_checker_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'requester_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_retention_policy_versions_requester_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'superseded_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_retention_policy_versions_superseder_membership'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_policy_versions_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_policy_versions')),
        sa.UniqueConstraint('workspace_id', 'id', 'payload_hash', 'policy_number', name='uq_retention_policy_versions_workspace_id_hash_number'),
        sa.UniqueConstraint('workspace_id', 'id', 'payload_hash', name='uq_retention_policy_versions_workspace_id_hash'),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_retention_policy_versions_workspace_id_id'),
        sa.UniqueConstraint('workspace_id', 'policy_number', name='uq_retention_policy_versions_workspace_number'),
        schema='retention'
        )
        op.create_index('ix_retention_policy_versions_workspace_number', 'policy_versions', ['workspace_id', 'policy_number'], unique=False, schema='retention')
        op.create_index('uq_retention_policy_versions_workspace_active', 'policy_versions', ['workspace_id'], unique=True, schema='retention', postgresql_where=sa.text("state = 'ACTIVE'"))
        op.execute('ALTER TABLE retention.policy_versions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.policy_versions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.policy_versions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('chat_sessions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('scope', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('retention_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retention_policy_id', sa.Uuid(), nullable=True),
        sa.Column('retention_policy_hash', sa.String(length=64), nullable=True),
        sa.Column('retention_basis_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retention_binding_version', sa.String(length=32), server_default=sa.text("'ACTIVE_POLICY_V1'"), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(retention_binding_version = 'LEGACY_UNBOUND_V1' AND retention_policy_id IS NULL AND retention_policy_hash IS NULL AND retention_basis_at IS NULL) OR (retention_binding_version = 'ACTIVE_POLICY_V1' AND retention_policy_id IS NOT NULL AND retention_policy_hash IS NOT NULL AND retention_basis_at IS NOT NULL AND retention_until IS NOT NULL)", name=op.f('ck_chat_sessions_retention_binding_shape')),
        sa.CheckConstraint("retention_binding_version IN ('LEGACY_UNBOUND_V1', 'ACTIVE_POLICY_V1')", name=op.f('ck_chat_sessions_retention_binding_version_allowlist')),
        sa.CheckConstraint("retention_policy_hash IS NULL OR retention_policy_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_chat_sessions_retention_policy_hash_sha256')),
        sa.CheckConstraint('retention_until IS NULL OR retention_basis_at IS NULL OR retention_until > retention_basis_at', name=op.f('ck_chat_sessions_retention_window')),
        sa.ForeignKeyConstraint(['workspace_id', 'retention_policy_id', 'retention_policy_hash'], ['retention.policy_versions.workspace_id', 'retention.policy_versions.id', 'retention.policy_versions.payload_hash'], name='fk_chat_sessions_retention_policy_binding', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_sessions')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_chat_sessions_workspace_id_id')),
        schema='assistant'
        )
        op.create_index('ix_chat_sessions_owner', 'chat_sessions', ['workspace_id', 'owner_id', 'updated_at'], unique=False, schema='assistant')
        op.execute('ALTER TABLE assistant.chat_sessions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE assistant.chat_sessions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON assistant.chat_sessions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('classification_access_policy_rules',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('policy_id', sa.Uuid(), nullable=False),
        sa.Column('policy_hash', sa.String(length=64), nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('search_mode', sa.String(length=30), nullable=False),
        sa.Column('chat_mode', sa.String(length=30), nullable=False),
        sa.Column('provider_profile_version_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(chat_mode = 'DENY' AND provider_profile_version_id IS NULL) OR (chat_mode <> 'DENY' AND provider_profile_version_id IS NOT NULL)", name=op.f('ck_classification_access_policy_rules_provider_binding')),
        sa.CheckConstraint("(classification = 3 AND search_mode IN ('DENY', 'EXPLICIT_GRANT_ONLY') AND chat_mode = 'DENY') OR (classification <> 3 AND search_mode <> 'EXPLICIT_GRANT_ONLY')", name=op.f('ck_classification_access_policy_rules_restricted_floor')),
        sa.CheckConstraint("chat_mode IN ('DENY', 'INTERNAL_APPROVED_ONLY', 'APPROVED_PROVIDER_ONLY')", name=op.f('ck_classification_access_policy_rules_chat_mode')),
        sa.CheckConstraint("classification <> 2 OR chat_mode IN ('DENY', 'INTERNAL_APPROVED_ONLY')", name=op.f('ck_classification_access_policy_rules_confidential_chat_floor')),
        sa.CheckConstraint("search_mode IN ('ABAC', 'DENY', 'EXPLICIT_GRANT_ONLY')", name=op.f('ck_classification_access_policy_rules_search_mode')),
        sa.CheckConstraint('classification BETWEEN 0 AND 3', name=op.f('ck_classification_access_policy_rules_classification')),
        sa.ForeignKeyConstraint(['workspace_id', 'policy_id', 'policy_hash'], ['authz.classification_access_policy_versions.workspace_id', 'authz.classification_access_policy_versions.id', 'authz.classification_access_policy_versions.payload_hash'], name='fk_classification_policy_rules_policy'),
        sa.ForeignKeyConstraint(['workspace_id', 'provider_profile_version_id'], ['integration.inference_provider_profile_versions.workspace_id', 'integration.inference_provider_profile_versions.id'], name='fk_classification_policy_rules_provider_profile'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_classification_access_policy_rules_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_classification_access_policy_rules')),
        sa.UniqueConstraint('workspace_id', 'policy_id', 'classification', name='uq_classification_policy_rules_classification'),
        schema='authz'
        )
        op.create_index('ix_classification_policy_rules_policy', 'classification_access_policy_rules', ['workspace_id', 'policy_id'], unique=False, schema='authz')
        op.execute('ALTER TABLE authz.classification_access_policy_rules ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE authz.classification_access_policy_rules FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON authz.classification_access_policy_rules USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('restricted_search_grants',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('classification_policy_id', sa.Uuid(), nullable=False),
        sa.Column('classification_policy_hash', sa.String(length=64), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('scope_id', sa.Uuid(), nullable=False),
        sa.Column('purpose', sa.String(length=4000), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('request_reason', sa.String(length=4000), nullable=False),
        sa.Column('request_policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('checker_id', sa.Uuid(), nullable=True),
        sa.Column('decision_reason', sa.String(length=4000), nullable=True),
        sa.Column('decision_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by', sa.Uuid(), nullable=True),
        sa.Column('revocation_reason', sa.String(length=4000), nullable=True),
        sa.Column('revocation_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'PENDING' AND version = 1 AND checker_id IS NULL AND decision_reason IS NULL AND decision_policy_decision_id IS NULL AND decided_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR (state IN ('ACTIVE', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND revoked_by IS NULL AND revocation_reason IS NULL AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR (state = 'REVOKED' AND version = 3 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL AND revocation_policy_decision_id IS NOT NULL AND revoked_at IS NOT NULL)", name=op.f('ck_restricted_search_grants_state_shape')),
        sa.CheckConstraint("classification_policy_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_restricted_search_grants_policy_hash_sha256')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_restricted_search_grants_payload_hash_sha256')),
        sa.CheckConstraint("scope IN ('RESOURCE', 'SYSTEM', 'DOMAIN')", name=op.f('ck_restricted_search_grants_scope')),
        sa.CheckConstraint("state IN ('PENDING', 'ACTIVE', 'REJECTED', 'REVOKED')", name=op.f('ck_restricted_search_grants_state')),
        sa.CheckConstraint('checker_id IS NULL OR checker_id <> requester_id', name=op.f('ck_restricted_search_grants_independent_checker')),
        sa.CheckConstraint('checker_id IS NULL OR checker_id <> subject_id', name=op.f('ck_restricted_search_grants_subject_cannot_check')),
        sa.CheckConstraint('expires_at > valid_from', name=op.f('ck_restricted_search_grants_validity_window')),
        sa.CheckConstraint('length(btrim(purpose)) > 0 AND length(btrim(request_reason)) > 0 AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND (revocation_reason IS NULL OR length(btrim(revocation_reason)) > 0)', name=op.f('ck_restricted_search_grants_reasons_nonempty')),
        sa.CheckConstraint('version > 0', name=op.f('ck_restricted_search_grants_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'checker_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_restricted_search_grants_checker_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'classification_policy_id', 'classification_policy_hash'], ['authz.classification_access_policy_versions.workspace_id', 'authz.classification_access_policy_versions.id', 'authz.classification_access_policy_versions.payload_hash'], name='fk_restricted_search_grants_policy'),
        sa.ForeignKeyConstraint(['workspace_id', 'requester_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_restricted_search_grants_requester_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'revoked_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_restricted_search_grants_revoker_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'subject_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_restricted_search_grants_subject_membership'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_restricted_search_grants_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_restricted_search_grants')),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_restricted_search_grants_workspace_id'),
        schema='authz'
        )
        op.create_index('ix_restricted_search_grants_scope_active', 'restricted_search_grants', ['workspace_id', 'scope', 'scope_id', 'state', 'expires_at'], unique=False, schema='authz')
        op.create_index('ix_restricted_search_grants_subject_active', 'restricted_search_grants', ['workspace_id', 'subject_id', 'state', 'expires_at'], unique=False, schema='authz')
        op.create_index('ix_restricted_search_grants_workspace_created_id', 'restricted_search_grants', ['workspace_id', sa.literal_column('created_at DESC'), 'id'], unique=False, schema='authz')
        op.execute('ALTER TABLE authz.restricted_search_grants ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE authz.restricted_search_grants FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON authz.restricted_search_grants USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('change_test_runs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('round_id', sa.Uuid(), nullable=False),
        sa.Column('system_id', sa.Uuid(), nullable=False),
        sa.Column('attachment_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False),
        sa.Column('plan_hash', sa.String(length=64), nullable=False),
        sa.Column('result_hash', sa.String(length=64), nullable=False),
        sa.Column('bounded_summary', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('recorded_by', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("jsonb_typeof(bounded_summary) = 'object'", name=op.f('ck_change_test_runs_summary_object')),
        sa.CheckConstraint("plan_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_change_test_runs_plan_hash_valid')),
        sa.CheckConstraint("result_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_change_test_runs_result_hash_valid')),
        sa.CheckConstraint("state IN ('PASSED', 'FAILED')", name=op.f('ck_change_test_runs_state_vocabulary')),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id', 'round_id', 'attachment_id'], ['governance.change_request_attachments.workspace_id', 'governance.change_request_attachments.change_request_id', 'governance.change_request_attachments.round_id', 'governance.change_request_attachments.id'], name='fk_change_test_runs_attachment', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id', 'round_id'], ['governance.change_request_rounds.workspace_id', 'governance.change_request_rounds.change_request_id', 'governance.change_request_rounds.id'], name='fk_change_test_runs_round', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'system_id'], ['platform.data_systems.workspace_id', 'platform.data_systems.id'], name='fk_change_test_runs_system', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_test_runs')),
        sa.UniqueConstraint('workspace_id', 'change_request_id', 'round_id', 'id', name=op.f('uq_change_test_runs_workspace_id_change_request_id_round_id_id')),
        schema='governance'
        )
        op.create_index('ix_change_test_runs_round_system', 'change_test_runs', ['workspace_id', 'change_request_id', 'round_id', 'system_id'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.change_test_runs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.change_test_runs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.change_test_runs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('manual_metadata_apply_attempts',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('submission_id', sa.Uuid(), nullable=False),
        sa.Column('attempt_no', sa.Integer(), nullable=False),
        sa.Column('lease_epoch', sa.Integer(), nullable=False),
        sa.Column('lease_token_hash', sa.String(length=64), nullable=False),
        sa.Column('worker_subject_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('failure_code', sa.String(length=100), nullable=True),
        sa.Column('report_root_hash', sa.String(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(state = 'RUNNING' AND finished_at IS NULL AND report_root_hash IS NULL AND failure_code IS NULL) OR (state <> 'RUNNING' AND finished_at IS NOT NULL AND finished_at >= started_at AND report_root_hash ~ '^[0-9a-f]{64}$' AND ((state = 'APPLIED' AND failure_code IS NULL) OR (state <> 'APPLIED' AND failure_code IS NOT NULL)))", name=op.f('ck_manual_metadata_apply_attempts_terminal_shape')),
        sa.CheckConstraint("lease_token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_manual_metadata_apply_attempts_lease_token_hash_valid')),
        sa.CheckConstraint("state IN ('RUNNING', 'APPLIED', 'RETRY_WAIT', 'FAILED', 'SUPERSEDED')", name=op.f('ck_manual_metadata_apply_attempts_state_vocabulary')),
        sa.CheckConstraint('attempt_no > 0 AND lease_epoch > 0', name=op.f('ck_manual_metadata_apply_attempts_attempt_fence_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'submission_id'], ['governance.manual_metadata_submissions.workspace_id', 'governance.manual_metadata_submissions.id'], name='fk_manual_apply_attempts_submission', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'worker_subject_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_manual_apply_attempts_worker', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_manual_metadata_apply_attempts')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_manual_metadata_apply_attempts_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'submission_id', 'attempt_no', name=op.f('uq_manual_metadata_apply_attempts_workspace_id_submission_id_attempt_no')),
        sa.UniqueConstraint('workspace_id', 'submission_id', 'id', name=op.f('uq_manual_metadata_apply_attempts_workspace_id_submission_id_id')),
        sa.UniqueConstraint('workspace_id', 'submission_id', 'lease_epoch', name=op.f('uq_manual_metadata_apply_attempts_workspace_id_submission_id_lease_epoch')),
        schema='governance'
        )
        op.create_index('ix_manual_apply_attempts_submission', 'manual_metadata_apply_attempts', ['workspace_id', 'submission_id', 'attempt_no'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.manual_metadata_apply_attempts ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.manual_metadata_apply_attempts FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.manual_metadata_apply_attempts USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('access_role_assignment_events',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=20), nullable=False),
        sa.Column('previous_role_id', sa.Uuid(), nullable=True),
        sa.Column('previous_role_version', sa.Integer(), nullable=True),
        sa.Column('role_id', sa.Uuid(), nullable=True),
        sa.Column('role_version', sa.Integer(), nullable=True),
        sa.Column('membership_version', sa.Integer(), nullable=False),
        sa.Column('access_payload_hash', sa.String(length=64), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(event_type = 'ASSIGNED' AND previous_role_id IS NULL AND previous_role_version IS NULL AND role_id IS NOT NULL AND role_version IS NOT NULL) OR (event_type = 'REASSIGNED' AND previous_role_id IS NOT NULL AND previous_role_version IS NOT NULL AND role_id IS NOT NULL AND role_version IS NOT NULL) OR (event_type = 'REMOVED' AND previous_role_id IS NOT NULL AND previous_role_version IS NOT NULL AND role_id IS NULL AND role_version IS NULL)", name=op.f('ck_access_role_assignment_events_state_shape')),
        sa.CheckConstraint("access_payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_access_role_assignment_events_payload_hash_sha256')),
        sa.CheckConstraint("event_type IN ('ASSIGNED', 'REASSIGNED', 'REMOVED')", name=op.f('ck_access_role_assignment_events_event_type')),
        sa.CheckConstraint('(previous_role_version IS NULL OR previous_role_version > 0) AND (role_version IS NULL OR role_version > 0)', name=op.f('ck_access_role_assignment_events_role_versions_positive')),
        sa.CheckConstraint('membership_version > 0', name=op.f('ck_access_role_assignment_events_membership_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'actor_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_access_role_assignment_events_actor', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'previous_role_id'], ['iam.access_roles.workspace_id', 'iam.access_roles.id'], name='fk_access_role_assignment_events_previous_role', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'role_id'], ['iam.access_roles.workspace_id', 'iam.access_roles.id'], name='fk_access_role_assignment_events_role', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'subject_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_access_role_assignment_events_membership', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_access_role_assignment_events_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_access_role_assignment_events')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_access_role_assignment_events_workspace_id_id')),
        schema='iam'
        )
        op.create_index('ix_access_role_assignment_events_workspace_subject_occurred', 'access_role_assignment_events', ['workspace_id', 'subject_id', 'occurred_at'], unique=False, schema='iam')
        op.execute('ALTER TABLE iam.access_role_assignment_events ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE iam.access_role_assignment_events FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON iam.access_role_assignment_events USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('access_role_assignments',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column('role_version', sa.Integer(), nullable=False),
        sa.Column('membership_version', sa.Integer(), nullable=False),
        sa.Column('access_payload_hash', sa.String(length=64), nullable=False),
        sa.Column('assigned_by', sa.Uuid(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("access_payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_access_role_assignments_payload_hash_sha256')),
        sa.CheckConstraint('membership_version > 0', name=op.f('ck_access_role_assignments_membership_version_positive')),
        sa.CheckConstraint('role_version > 0', name=op.f('ck_access_role_assignments_role_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'assigned_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_access_role_assignments_actor', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'role_id'], ['iam.access_roles.workspace_id', 'iam.access_roles.id'], name='fk_access_role_assignments_role', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'subject_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_access_role_assignments_membership', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_access_role_assignments_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_access_role_assignments')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_access_role_assignments_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'subject_id', name=op.f('uq_access_role_assignments_workspace_id_subject_id')),
        schema='iam'
        )
        op.create_index('ix_access_role_assignments_workspace_role', 'access_role_assignments', ['workspace_id', 'role_id', 'active'], unique=False, schema='iam')
        op.execute('ALTER TABLE iam.access_role_assignments ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE iam.access_role_assignments FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON iam.access_role_assignments USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('access_role_data_rules',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('role_id', sa.Uuid(), nullable=False),
        sa.Column('role_version', sa.Integer(), nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('access_level', sa.String(length=24), nullable=False),
        sa.Column('partial_treatment', sa.String(length=24), nullable=True),
        sa.Column('allowed_residency_regions', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('allowed_processing_purposes', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("(access_level = 'NO_ACCESS' AND jsonb_array_length(allowed_residency_regions) = 0 AND jsonb_array_length(allowed_processing_purposes) = 0) OR (access_level <> 'NO_ACCESS' AND jsonb_array_length(allowed_residency_regions) > 0 AND jsonb_array_length(allowed_processing_purposes) > 0)", name=op.f('ck_access_role_data_rules_access_scope_shape')),
        sa.CheckConstraint("(access_level = 'PARTIAL_ACCESS' AND partial_treatment IS NOT NULL) OR (access_level <> 'PARTIAL_ACCESS' AND partial_treatment IS NULL)", name=op.f('ck_access_role_data_rules_access_treatment_shape')),
        sa.CheckConstraint("access_level IN ('NO_ACCESS', 'PARTIAL_ACCESS', 'FULL_ACCESS')", name=op.f('ck_access_role_data_rules_access_level_vocabulary')),
        sa.CheckConstraint("jsonb_typeof(allowed_residency_regions) = 'array' AND jsonb_typeof(allowed_processing_purposes) = 'array'", name=op.f('ck_access_role_data_rules_scope_arrays')),
        sa.CheckConstraint("partial_treatment IS NULL OR partial_treatment IN ('MASK', 'REDACT', 'TOKENIZE')", name=op.f('ck_access_role_data_rules_partial_treatment_vocabulary')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_access_role_data_rules_payload_hash_sha256')),
        sa.CheckConstraint('classification BETWEEN 0 AND 3', name=op.f('ck_access_role_data_rules_classification_range')),
        sa.CheckConstraint('jsonb_array_length(jsonb_path_query_array(allowed_residency_regions, \'$[*] ? (@.type() == "string" && @ like_regex "^[A-Z0-9][A-Z0-9._:-]{0,63}$")\')) = jsonb_array_length(allowed_residency_regions) AND allowed_processing_purposes <@ \'["METADATA_READ", "DATA_READ", "EXPORT", "ANALYTICS", "MODEL_TRAINING"]\'::jsonb', name=op.f('ck_access_role_data_rules_scope_item_vocabulary')),
        sa.CheckConstraint('role_version > 0', name=op.f('ck_access_role_data_rules_role_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'created_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_access_role_data_rules_creator', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'role_id'], ['iam.access_roles.workspace_id', 'iam.access_roles.id'], name='fk_access_role_data_rules_role', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_access_role_data_rules_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_access_role_data_rules')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_access_role_data_rules_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'role_id', 'role_version', 'classification', name=op.f('uq_access_role_data_rules_workspace_id_role_id_role_version_classification')),
        schema='iam',
        comment='Missing classification rule resolves to ROLE_DATA_RULE_MISSING (deny)'
        )
        op.create_index('ix_access_role_data_rules_workspace_role_version', 'access_role_data_rules', ['workspace_id', 'role_id', 'role_version'], unique=False, schema='iam')
        op.execute('ALTER TABLE iam.access_role_data_rules ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE iam.access_role_data_rules FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON iam.access_role_data_rules USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('admin_access_approvals',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('access_request_id', sa.Uuid(), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.String(length=4000), nullable=False),
        sa.Column('policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('request_version', sa.Integer(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("decision IN ('APPROVED', 'REJECTED')", name=op.f('ck_admin_access_approvals_decision')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_admin_access_approvals_payload_hash_sha256')),
        sa.CheckConstraint('request_version > 0', name=op.f('ck_admin_access_approvals_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'access_request_id'], ['iam.admin_access_requests.workspace_id', 'iam.admin_access_requests.id'], name='fk_admin_access_approvals_request', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id', 'actor_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_admin_access_approvals_actor_membership'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_admin_access_approvals_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_access_approvals')),
        sa.UniqueConstraint('workspace_id', 'access_request_id', 'actor_id', name='uq_admin_access_approvals_request_actor'),
        schema='iam'
        )
        op.create_index('ix_admin_access_approvals_workspace_request', 'admin_access_approvals', ['workspace_id', 'access_request_id'], unique=False, schema='iam')
        op.execute('ALTER TABLE iam.admin_access_approvals ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE iam.admin_access_approvals FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON iam.admin_access_approvals USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('job_attempts',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=False),
        sa.Column('attempt_no', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.String(length=255), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('error_class', sa.String(length=100), nullable=True),
        sa.Column('external_response_hash', sa.String(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'job_id'], ['integration.jobs.workspace_id', 'integration.jobs.id'], name=op.f('fk_job_attempts_workspace_id_job_id_jobs'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_job_attempts')),
        sa.UniqueConstraint('job_id', 'attempt_no', name=op.f('uq_job_attempts_job_id_attempt_no')),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.job_attempts ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.job_attempts FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.job_attempts USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('upload_preparation_receipts',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('preparation_job_id', sa.Uuid(), nullable=False),
        sa.Column('upload_id', sa.Uuid(), nullable=False),
        sa.Column('manifest_version', sa.Integer(), nullable=False),
        sa.Column('source_sha256', sa.String(length=64), nullable=False),
        sa.Column('accepted_sha256', sa.String(length=64), nullable=False),
        sa.Column('object_locator_hash', sa.String(length=64), nullable=False),
        sa.Column('accepted_etag', sa.String(length=512), nullable=True),
        sa.Column('accepted_version_id', sa.String(length=1024), nullable=True),
        sa.Column('content_profile', sa.String(length=100), nullable=False),
        sa.Column('parser_version', sa.String(length=100), nullable=False),
        sa.Column('scanner_version', sa.String(length=100), nullable=False),
        sa.Column('schema_version', sa.String(length=100), nullable=False),
        sa.Column('configuration_hash', sa.String(length=64), nullable=False),
        sa.Column('item_count', sa.BigInteger(), nullable=False),
        sa.Column('rejected_count', sa.BigInteger(), nullable=False),
        sa.Column('candidate_root_hash', sa.String(length=64), nullable=False),
        sa.Column('receipt_hash', sa.String(length=64), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("accepted_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_receipts_accepted_sha256_valid')),
        sa.CheckConstraint("candidate_root_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_receipts_candidate_root_hash_valid')),
        sa.CheckConstraint("configuration_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_receipts_configuration_hash_valid')),
        sa.CheckConstraint("content_profile IN ('DATASET_DESCRIPTION_CSV_V1', 'DATASET_DESCRIPTION_XLSX_V1', 'CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')", name=op.f('ck_upload_preparation_receipts_typed_profile_allowlist')),
        sa.CheckConstraint("object_locator_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_receipts_object_locator_hash_valid')),
        sa.CheckConstraint("receipt_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_receipts_receipt_hash_valid')),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_receipts_source_sha256_valid')),
        sa.CheckConstraint('accepted_sha256 = source_sha256', name=op.f('ck_upload_preparation_receipts_accepted_source_sha256_equal')),
        sa.CheckConstraint('item_count >= 0 AND rejected_count >= 0', name=op.f('ck_upload_preparation_receipts_row_counts_nonnegative')),
        sa.CheckConstraint('manifest_version > 0', name=op.f('ck_upload_preparation_receipts_manifest_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'preparation_job_id', 'upload_id', 'manifest_version', 'source_sha256', 'content_profile', 'configuration_hash'], ['integration.upload_preparation_jobs.workspace_id', 'integration.upload_preparation_jobs.id', 'integration.upload_preparation_jobs.upload_id', 'integration.upload_preparation_jobs.source_manifest_version', 'integration.upload_preparation_jobs.source_sha256', 'integration.upload_preparation_jobs.content_profile', 'integration.upload_preparation_jobs.configuration_hash'], name='fk_upload_prep_receipts_source_evidence', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'upload_id'], ['integration.object_manifests.workspace_id', 'integration.object_manifests.id'], name='fk_upload_prep_receipts_workspace_upload', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_preparation_receipts')),
        sa.UniqueConstraint('workspace_id', 'id', 'content_profile', name='uq_upload_preparation_receipts_profile_identity'),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_upload_preparation_receipts_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'preparation_job_id', name=op.f('uq_upload_preparation_receipts_workspace_id_preparation_job_id')),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.upload_preparation_receipts ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.upload_preparation_receipts FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.upload_preparation_receipts USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('change_operations',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('changeset_id', sa.Uuid(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('operation', sa.String(length=50), nullable=False),
        sa.Column('entity_kind', sa.String(length=20), nullable=False),
        sa.Column('stable_entity_id', sa.Uuid(), nullable=False),
        sa.Column('document', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('provenance', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'changeset_id'], ['knowledge.changesets.workspace_id', 'knowledge.changesets.id'], name=op.f('fk_change_operations_workspace_id_changeset_id_changesets'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_operations')),
        sa.UniqueConstraint('changeset_id', 'sequence', name=op.f('uq_change_operations_changeset_id_sequence')),
        schema='knowledge'
        )
        op.execute('ALTER TABLE knowledge.change_operations ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.change_operations FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.change_operations USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('graphrag_audits',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('release_id', sa.Uuid(), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('request_id', sa.String(length=100), nullable=False),
        sa.Column('question_sha256', sa.String(length=64), nullable=False),
        sa.Column('evidence_ids', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('cited_evidence_ids', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('model_identity', sa.String(length=200), nullable=False),
        sa.Column('prompt_version', sa.String(length=200), nullable=False),
        sa.Column('tool_schema_version', sa.String(length=200), nullable=False),
        sa.Column('configuration_source', sa.String(length=32), nullable=True),
        sa.Column('configuration_version', sa.Integer(), nullable=True),
        sa.Column('configuration_hash', sa.String(length=64), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("(configuration_source IS NULL AND configuration_version IS NULL AND configuration_hash IS NULL) OR (configuration_source = 'SYSTEM_CONFIGURATION' AND configuration_version > 0 AND configuration_hash ~ '^[0-9a-f]{64}$') OR (configuration_source = 'DEPLOYMENT' AND configuration_version IS NULL AND configuration_hash ~ '^[0-9a-f]{64}$')", name=op.f('ck_graphrag_audits_configuration_evidence_shape')),
        sa.CheckConstraint("question_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_graphrag_audits_question_sha256')),
        sa.CheckConstraint('input_tokens IS NULL OR input_tokens >= 0', name=op.f('ck_graphrag_audits_input_tokens_nonnegative')),
        sa.CheckConstraint('output_tokens IS NULL OR output_tokens >= 0', name=op.f('ck_graphrag_audits_output_tokens_nonnegative')),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.graph_id', 'knowledge.releases.id'], name=op.f('fk_graphrag_audits_workspace_id_graph_id_release_id_releases'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_graphrag_audits')),
        sa.UniqueConstraint('workspace_id', 'request_id', name=op.f('uq_graphrag_audits_workspace_id_request_id')),
        schema='knowledge'
        )
        op.create_index('ix_graphrag_audits_release_created', 'graphrag_audits', ['release_id', 'created_at'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.graphrag_audits ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.graphrag_audits FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.graphrag_audits USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('projection_deployments',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('release_id', sa.Uuid(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=True),
        sa.Column('adapter', sa.String(length=100), nullable=False),
        sa.Column('target_ref', sa.String(length=500), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('verification_hash', sa.String(length=64), nullable=True),
        sa.Column('node_count', sa.Integer(), nullable=True),
        sa.Column('edge_count', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.graph_id', 'knowledge.releases.id'], name=op.f('fk_projection_deployments_workspace_id_graph_id_release_id_releases'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_projection_deployments')),
        schema='knowledge'
        )
        op.create_index('ix_projection_deployments_release', 'projection_deployments', ['release_id', 'adapter'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.projection_deployments ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.projection_deployments FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.projection_deployments USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('release_edges',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('release_id', sa.Uuid(), nullable=False),
        sa.Column('edge_id', sa.Uuid(), nullable=False),
        sa.Column('source_entity_id', sa.Uuid(), nullable=False),
        sa.Column('target_entity_id', sa.Uuid(), nullable=False),
        sa.Column('edge_type', sa.String(length=100), nullable=False),
        sa.Column('properties', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('provenance', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.id'], name=op.f('fk_release_edges_workspace_id_release_id_releases'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('release_id', 'edge_id', name=op.f('pk_release_edges')),
        schema='knowledge'
        )
        op.create_index('ix_release_edges_source', 'release_edges', ['release_id', 'source_entity_id', 'edge_type'], unique=False, schema='knowledge')
        op.create_index('ix_release_edges_target', 'release_edges', ['release_id', 'target_entity_id', 'edge_type'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.release_edges ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.release_edges FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.release_edges USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('release_nodes',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('release_id', sa.Uuid(), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=False),
        sa.Column('properties', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('provenance', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.id'], name=op.f('fk_release_nodes_workspace_id_release_id_releases'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('release_id', 'entity_id', name=op.f('pk_release_nodes')),
        schema='knowledge'
        )
        op.execute('ALTER TABLE knowledge.release_nodes ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.release_nodes FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.release_nodes USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('source_analysis_attempts',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=False),
        sa.Column('attempt_no', sa.Integer(), nullable=False),
        sa.Column('lease_epoch', sa.Integer(), nullable=False),
        sa.Column('lease_token_hash', sa.String(length=64), nullable=False),
        sa.Column('worker_fingerprint', sa.String(length=255), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('stage', sa.String(length=32), nullable=False),
        sa.Column('input_hash', sa.String(length=64), nullable=False),
        sa.Column('output_hash', sa.String(length=64), nullable=True),
        sa.Column('external_response_hash', sa.String(length=64), nullable=True),
        sa.Column('retryable', sa.Boolean(), nullable=False),
        sa.Column('failure_code', sa.String(length=100), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(state = 'RUNNING' AND finished_at IS NULL) OR (state <> 'RUNNING' AND finished_at IS NOT NULL)", name=op.f('ck_source_analysis_attempts_terminal_shape')),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$' AND (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$') AND (external_response_hash IS NULL OR external_response_hash ~ '^[0-9a-f]{64}$')", name=op.f('ck_source_analysis_attempts_evidence_hashes')),
        sa.CheckConstraint("lease_token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_source_analysis_attempts_lease_token_hash')),
        sa.CheckConstraint("stage IN ('SOURCE_READ', 'PARSED', 'EMBEDDED', 'EXTRACTED', 'FINALIZING', 'COMPLETED')", name=op.f('ck_source_analysis_attempts_stage_vocabulary')),
        sa.CheckConstraint("state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED', 'SUPERSEDED')", name=op.f('ck_source_analysis_attempts_state_vocabulary')),
        sa.CheckConstraint('attempt_no > 0 AND lease_epoch > 0', name=op.f('ck_source_analysis_attempts_counters')),
        sa.ForeignKeyConstraint(['workspace_id', 'job_id'], ['knowledge.source_analysis_jobs.workspace_id', 'knowledge.source_analysis_jobs.id'], name=op.f('fk_source_analysis_attempts_workspace_id_job_id_source_analysis_jobs'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_analysis_attempts')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_source_analysis_attempts_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'job_id', 'attempt_no', name=op.f('uq_source_analysis_attempts_workspace_id_job_id_attempt_no')),
        sa.UniqueConstraint('workspace_id', 'job_id', 'lease_epoch', name=op.f('uq_source_analysis_attempts_workspace_id_job_id_lease_epoch')),
        schema='knowledge'
        )
        op.create_index('ix_source_analysis_attempts_job', 'source_analysis_attempts', ['workspace_id', 'job_id', 'attempt_no'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.source_analysis_attempts ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.source_analysis_attempts FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.source_analysis_attempts USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('source_page_embeddings',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('source_snapshot_id', sa.Uuid(), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('model_identity', sa.String(length=200), nullable=False),
        sa.Column('dimension', sa.Integer(), nullable=False),
        sa.Column('embedding', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_source_page_embeddings_content_sha256')),
        sa.CheckConstraint('dimension > 0 AND dimension <= 16384', name=op.f('ck_source_page_embeddings_bounded_dimension')),
        sa.ForeignKeyConstraint(['workspace_id', 'source_snapshot_id', 'page_number'], ['knowledge.source_pages.workspace_id', 'knowledge.source_pages.source_snapshot_id', 'knowledge.source_pages.page_number'], name=op.f('fk_source_page_embeddings_workspace_id_source_snapshot_id_page_number_source_pages'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_page_embeddings')),
        sa.UniqueConstraint('source_snapshot_id', 'page_number', 'provider', 'model_identity', name=op.f('uq_source_page_embeddings_source_snapshot_id_page_number_provider_model_identity')),
        schema='knowledge'
        )
        op.create_index('ix_source_page_embeddings_source', 'source_page_embeddings', ['source_snapshot_id', 'page_number'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.source_page_embeddings ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.source_page_embeddings FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.source_page_embeddings USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('validation_results',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('changeset_id', sa.Uuid(), nullable=False),
        sa.Column('validator', sa.String(length=100), nullable=False),
        sa.Column('validator_version', sa.String(length=100), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('location', sa.Text(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'changeset_id'], ['knowledge.changesets.workspace_id', 'knowledge.changesets.id'], name=op.f('fk_validation_results_workspace_id_changeset_id_changesets'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_validation_results')),
        schema='knowledge'
        )
        op.create_index('ix_validation_results_changeset', 'validation_results', ['changeset_id', 'severity'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.validation_results ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.validation_results FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.validation_results USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('external_service_profile_versions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('profile_id', sa.Uuid(), nullable=False),
        sa.Column('configuration_version', sa.Integer(), nullable=False),
        sa.Column('configuration_hash', sa.String(length=64), nullable=False),
        sa.Column('configuration_yaml', sa.Text(), nullable=False),
        sa.Column('endpoint_url', sa.String(length=2048), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('test_status', sa.String(length=32), nullable=True),
        sa.Column('test_scope', sa.String(length=32), nullable=True),
        sa.Column('test_latency_ms', sa.Integer(), nullable=True),
        sa.Column('tested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('tested_by', sa.Uuid(), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('activated_by', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("(activated_at IS NULL AND activated_by IS NULL) OR (activated_at IS NOT NULL AND activated_by IS NOT NULL AND test_status = 'AVAILABLE')", name=op.f('ck_external_service_profile_versions_activation_evidence_shape')),
        sa.CheckConstraint("configuration_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_external_service_profile_versions_configuration_hash_sha256')),
        sa.CheckConstraint("test_scope IS NULL OR test_scope IN ('HTTP_HEALTH', 'MODEL_DISCOVERY', 'MODEL_INFERENCE', 'EMBEDDING_INFERENCE', 'RERANKING_INFERENCE', 'AUTHENTICATED_QUERY', 'REDIS_PING', 'REDIS_POLICY', 'S3_HEAD_BUCKET')", name=op.f('ck_external_service_profile_versions_test_scope_vocabulary')),
        sa.CheckConstraint("test_status IS NULL OR test_status IN ('AVAILABLE', 'AUTHENTICATION_REQUIRED', 'UNAVAILABLE')", name=op.f('ck_external_service_profile_versions_test_status_vocabulary')),
        sa.CheckConstraint('(test_status IS NULL AND test_scope IS NULL AND test_latency_ms IS NULL AND tested_at IS NULL AND tested_by IS NULL) OR (test_status IS NOT NULL AND test_scope IS NOT NULL AND test_latency_ms IS NOT NULL AND tested_at IS NOT NULL AND tested_by IS NOT NULL)', name=op.f('ck_external_service_profile_versions_test_evidence_shape')),
        sa.CheckConstraint('configuration_version > 0', name=op.f('ck_external_service_profile_versions_configuration_version_positive')),
        sa.CheckConstraint('test_latency_ms IS NULL OR test_latency_ms >= 0', name=op.f('ck_external_service_profile_versions_latency_non_negative')),
        sa.ForeignKeyConstraint(['workspace_id', 'activated_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_external_service_profile_versions_activator', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'created_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_external_service_profile_versions_creator', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'profile_id'], ['platform.external_service_profiles.workspace_id', 'platform.external_service_profiles.id'], name='fk_external_service_profile_versions_profile', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id', 'tested_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_external_service_profile_versions_tester', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_external_service_profile_versions_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_external_service_profile_versions')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_external_service_profile_versions_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'profile_id', 'configuration_version', name=op.f('uq_external_service_profile_versions_workspace_id_profile_id_configuration_version')),
        schema='platform'
        )
        op.create_index('ix_external_service_profile_versions_workspace_profile', 'external_service_profile_versions', ['workspace_id', 'profile_id', 'configuration_version'], unique=False, schema='platform')
        op.execute('ALTER TABLE platform.external_service_profile_versions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE platform.external_service_profile_versions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON platform.external_service_profile_versions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('erasure_requests',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False),
        sa.Column('target_id', sa.Uuid(), nullable=False),
        sa.Column('target_version', sa.Integer(), nullable=False),
        sa.Column('target_owner_id', sa.Uuid(), nullable=True),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('retention_policy_id', sa.Uuid(), nullable=False),
        sa.Column('retention_policy_hash', sa.String(length=64), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('request_reason', sa.String(length=4000), nullable=False),
        sa.Column('request_policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('checker_id', sa.Uuid(), nullable=True),
        sa.Column('decision_reason', sa.String(length=4000), nullable=True),
        sa.Column('decision_policy_decision_id', sa.Uuid(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'PENDING' AND version = 1 AND checker_id IS NULL AND decision_reason IS NULL AND decision_policy_decision_id IS NULL AND decided_at IS NULL) OR (state IN ('APPROVED', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL)", name=op.f('ck_erasure_requests_state_shape')),
        sa.CheckConstraint("expires_at > created_at AND expires_at <= created_at + INTERVAL '7 days' AND (decided_at IS NULL OR decided_at >= created_at) AND (state <> 'APPROVED' OR decided_at < expires_at)", name=op.f('ck_erasure_requests_review_window')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_erasure_requests_payload_hash_sha256')),
        sa.CheckConstraint("retention_policy_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_erasure_requests_retention_policy_hash_sha256')),
        sa.CheckConstraint("state IN ('PENDING', 'APPROVED', 'REJECTED')", name=op.f('ck_erasure_requests_state')),
        sa.CheckConstraint("target_type <> 'SUBJECT_DATA' OR checker_id IS NULL OR checker_id <> target_id", name=op.f('ck_erasure_requests_subject_cannot_check_own_erasure')),
        sa.CheckConstraint("target_type IN ('SUBJECT_DATA', 'CHAT_SESSION', 'UPLOAD_OBJECT')", name=op.f('ck_erasure_requests_target_type')),
        sa.CheckConstraint('checker_id IS NULL OR checker_id <> requester_id', name=op.f('ck_erasure_requests_independent_checker')),
        sa.CheckConstraint('checker_id IS NULL OR target_owner_id IS NULL OR checker_id <> target_owner_id', name=op.f('ck_erasure_requests_target_owner_cannot_check')),
        sa.CheckConstraint('classification BETWEEN 0 AND 3', name=op.f('ck_erasure_requests_classification_range')),
        sa.CheckConstraint('length(btrim(request_reason)) > 0 AND (decision_reason IS NULL OR length(btrim(decision_reason)) > 0)', name=op.f('ck_erasure_requests_reasons_nonempty')),
        sa.CheckConstraint('target_version > 0', name=op.f('ck_erasure_requests_target_version_positive')),
        sa.CheckConstraint('version > 0', name=op.f('ck_erasure_requests_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'checker_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_erasure_requests_checker_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'requester_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_erasure_requests_requester_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'retention_policy_id', 'retention_policy_hash'], ['retention.policy_versions.workspace_id', 'retention.policy_versions.id', 'retention.policy_versions.payload_hash'], name='fk_erasure_requests_retention_policy'),
        sa.ForeignKeyConstraint(['workspace_id', 'target_owner_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_erasure_requests_target_owner_membership'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_erasure_requests_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_erasure_requests')),
        sa.UniqueConstraint('workspace_id', 'id', 'version', 'payload_hash', name='uq_erasure_requests_workspace_id_version_hash'),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_erasure_requests_workspace_id_id'),
        sa.UniqueConstraint('workspace_id', 'requester_id', 'payload_hash', name='uq_erasure_requests_idempotent_payload'),
        schema='retention'
        )
        op.create_index('ix_erasure_requests_workspace_created_id', 'erasure_requests', ['workspace_id', sa.literal_column('created_at DESC'), 'id'], unique=False, schema='retention')
        op.create_index('ix_erasure_requests_workspace_state_expiry', 'erasure_requests', ['workspace_id', 'state', 'expires_at'], unique=False, schema='retention')
        op.create_index('ix_erasure_requests_workspace_target', 'erasure_requests', ['workspace_id', 'target_type', 'target_id', 'created_at'], unique=False, schema='retention')
        op.execute('ALTER TABLE retention.erasure_requests ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.erasure_requests FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.erasure_requests USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('immutable_archive_receipts',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('source_partition', sa.String(length=64), nullable=False),
        sa.Column('source_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('retention_policy_id', sa.Uuid(), nullable=False),
        sa.Column('retention_policy_hash', sa.String(length=64), nullable=False),
        sa.Column('row_count', sa.BigInteger(), nullable=False),
        sa.Column('byte_count', sa.BigInteger(), nullable=False),
        sa.Column('manifest_hash', sa.String(length=64), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('provider_checksum', sa.String(length=512), nullable=False),
        sa.Column('provider_checksum_algorithm', sa.String(length=20), nullable=False),
        sa.Column('provider_checksum_encoding', sa.String(length=20), nullable=False),
        sa.Column('provider_checksum_type', sa.String(length=30), nullable=False),
        sa.Column('provider_checksum_normalized_sha256', sa.String(length=64), nullable=False),
        sa.Column('readback_sha256', sa.String(length=64), nullable=False),
        sa.Column('readback_byte_count', sa.BigInteger(), nullable=False),
        sa.Column('object_bucket', sa.String(length=63), nullable=False),
        sa.Column('object_key', sa.String(length=1024), nullable=False),
        sa.Column('object_version_id', sa.String(length=1024), nullable=False),
        sa.Column('retention_mode', sa.String(length=20), nullable=False),
        sa.Column('retention_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('requested_retention_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('readback_retention_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('legal_hold', sa.Boolean(), nullable=False),
        sa.Column('written_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('content_verified_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('retention_verified_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('canonicalization_version', sa.String(length=100), nullable=False),
        sa.Column('media_type', sa.String(length=255), nullable=False),
        sa.Column('media_type_version', sa.String(length=100), nullable=False),
        sa.Column('compression', sa.String(length=50), nullable=False),
        sa.Column('compression_version', sa.String(length=100), nullable=False),
        sa.Column('worker_principal_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('correlation_id', sa.String(length=100), nullable=False),
        sa.Column('capability_attestation_id', sa.Uuid(), nullable=False),
        sa.Column('capability_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('encryption_profile_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("capability_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f('ck_immutable_archive_receipts_capability_fingerprint_sha256')),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_immutable_archive_receipts_content_sha256')),
        sa.CheckConstraint("encryption_profile_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f('ck_immutable_archive_receipts_encryption_profile_fingerprint_sha256')),
        sa.CheckConstraint("length(object_key) BETWEEN 1 AND 1024 AND object_key !~ '^/'", name=op.f('ck_immutable_archive_receipts_object_key')),
        sa.CheckConstraint("length(object_version_id) BETWEEN 1 AND 1024 AND lower(btrim(object_version_id)) <> 'null'", name=op.f('ck_immutable_archive_receipts_object_version_id')),
        sa.CheckConstraint("manifest_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_immutable_archive_receipts_manifest_hash_sha256')),
        sa.CheckConstraint("object_bucket ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'", name=op.f('ck_immutable_archive_receipts_object_bucket')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_immutable_archive_receipts_payload_hash_sha256')),
        sa.CheckConstraint("provider_checksum_algorithm = 'SHA256'", name=op.f('ck_immutable_archive_receipts_checksum_algorithm')),
        sa.CheckConstraint("provider_checksum_encoding IN ('HEX', 'BASE64')", name=op.f('ck_immutable_archive_receipts_checksum_encoding')),
        sa.CheckConstraint("provider_checksum_normalized_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_immutable_archive_receipts_provider_checksum_normalized_sha256')),
        sa.CheckConstraint("provider_checksum_type = 'FULL_OBJECT'", name=op.f('ck_immutable_archive_receipts_checksum_type')),
        sa.CheckConstraint("readback_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_immutable_archive_receipts_readback_sha256')),
        sa.CheckConstraint("retention_mode = 'COMPLIANCE'", name=op.f('ck_immutable_archive_receipts_retention_mode')),
        sa.CheckConstraint("retention_policy_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_immutable_archive_receipts_retention_policy_hash_sha256')),
        sa.CheckConstraint("source IN ('OUTBOX_EVENTS', 'INBOX_MESSAGES', 'POLICY_DECISIONS', 'ASSISTANT_RUNS', 'ERASURE_EXECUTION_EVIDENCE')", name=op.f('ck_immutable_archive_receipts_source')),
        sa.CheckConstraint("source_partition ~ '^[a-z][a-z0-9_]{1,49}_[0-9]{4}_[0-9]{2}$'", name=op.f('ck_immutable_archive_receipts_source_partition')),
        sa.CheckConstraint("worker_principal_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f('ck_immutable_archive_receipts_worker_principal_fingerprint_sha256')),
        sa.CheckConstraint('byte_count > 0', name=op.f('ck_immutable_archive_receipts_byte_count_positive')),
        sa.CheckConstraint('content_sha256 = readback_sha256 AND content_sha256 = provider_checksum_normalized_sha256 AND byte_count = readback_byte_count', name=op.f('ck_immutable_archive_receipts_content_readback_match')),
        sa.CheckConstraint('length(canonicalization_version) BETWEEN 1 AND 100 AND length(media_type) BETWEEN 1 AND 255 AND length(media_type_version) BETWEEN 1 AND 100 AND length(compression) BETWEEN 1 AND 50 AND length(compression_version) BETWEEN 1 AND 100', name=op.f('ck_immutable_archive_receipts_format_metadata')),
        sa.CheckConstraint('length(correlation_id) BETWEEN 1 AND 100', name=op.f('ck_immutable_archive_receipts_correlation_id')),
        sa.CheckConstraint('length(provider_checksum) BETWEEN 1 AND 512', name=op.f('ck_immutable_archive_receipts_provider_checksum')),
        sa.CheckConstraint('readback_byte_count > 0', name=op.f('ck_immutable_archive_receipts_readback_byte_count_positive')),
        sa.CheckConstraint('retention_until = requested_retention_until AND retention_until = readback_retention_until AND retention_until > verified_at', name=op.f('ck_immutable_archive_receipts_retention_readback_match')),
        sa.CheckConstraint('row_count > 0', name=op.f('ck_immutable_archive_receipts_row_count_positive')),
        sa.CheckConstraint('source_end > source_start', name=op.f('ck_immutable_archive_receipts_source_range')),
        sa.CheckConstraint('written_at <= content_verified_at AND written_at <= retention_verified_at AND content_verified_at <= verified_at AND retention_verified_at <= verified_at', name=op.f('ck_immutable_archive_receipts_verification_timeline')),
        sa.ForeignKeyConstraint(['workspace_id', 'capability_attestation_id', 'capability_fingerprint', 'encryption_profile_fingerprint', 'worker_principal_fingerprint'], ['retention.archive_capability_attestations.workspace_id', 'retention.archive_capability_attestations.id', 'retention.archive_capability_attestations.configuration_fingerprint', 'retention.archive_capability_attestations.encryption_profile_fingerprint', 'retention.archive_capability_attestations.runtime_principal_fingerprint'], name='fk_immutable_archive_receipts_capability_attestation'),
        sa.ForeignKeyConstraint(['workspace_id', 'retention_policy_id', 'retention_policy_hash'], ['retention.policy_versions.workspace_id', 'retention.policy_versions.id', 'retention.policy_versions.payload_hash'], name='fk_immutable_archive_receipts_retention_policy'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_immutable_archive_receipts_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_immutable_archive_receipts')),
        sa.UniqueConstraint('object_bucket', 'object_key', 'object_version_id', name='uq_immutable_archive_receipts_object_version'),
        sa.UniqueConstraint('workspace_id', 'id', 'manifest_hash', name='uq_immutable_archive_receipts_workspace_id_manifest'),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_immutable_archive_receipts_workspace_id_id'),
        sa.UniqueConstraint('workspace_id', 'source', 'source_start', 'source_end', 'manifest_hash', name='uq_immutable_archive_receipts_source_manifest'),
        schema='retention'
        )
        op.create_index('ix_immutable_archive_receipts_workspace_source', 'immutable_archive_receipts', ['workspace_id', 'source', 'source_partition'], unique=False, schema='retention')
        op.create_index('ix_immutable_archive_receipts_workspace_verified', 'immutable_archive_receipts', ['workspace_id', 'verified_at'], unique=False, schema='retention')
        op.execute('ALTER TABLE retention.immutable_archive_receipts ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.immutable_archive_receipts FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.immutable_archive_receipts USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('legal_hold_events',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('hold_id', sa.Uuid(), nullable=False),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('reason', sa.String(length=4000), nullable=False),
        sa.Column('policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('hold_version', sa.Integer(), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(action = 'PLACED' AND hold_version = 1) OR (action <> 'PLACED' AND hold_version > 1)", name=op.f('ck_legal_hold_events_action_version_shape')),
        sa.CheckConstraint("action IN ('PLACED', 'RELEASE_REQUESTED', 'RELEASE_APPROVED', 'RELEASE_REJECTED')", name=op.f('ck_legal_hold_events_action')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_legal_hold_events_payload_hash_sha256')),
        sa.CheckConstraint('hold_version > 0', name=op.f('ck_legal_hold_events_hold_version_positive')),
        sa.CheckConstraint('length(btrim(reason)) > 0', name=op.f('ck_legal_hold_events_reason_nonempty')),
        sa.ForeignKeyConstraint(['workspace_id', 'actor_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_legal_hold_events_actor_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'hold_id'], ['retention.legal_holds.workspace_id', 'retention.legal_holds.id'], name='fk_legal_hold_events_hold'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_legal_hold_events_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_legal_hold_events')),
        sa.UniqueConstraint('workspace_id', 'hold_id', 'hold_version', name='uq_legal_hold_events_hold_version'),
        schema='retention'
        )
        op.create_index('ix_legal_hold_events_workspace_hold_time', 'legal_hold_events', ['workspace_id', 'hold_id', 'occurred_at'], unique=False, schema='retention')
        op.execute('ALTER TABLE retention.legal_hold_events ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.legal_hold_events FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.legal_hold_events USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('policy_class_rules',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('policy_id', sa.Uuid(), nullable=False),
        sa.Column('policy_hash', sa.String(length=64), nullable=False),
        sa.Column('policy_number', sa.Integer(), nullable=False),
        sa.Column('data_class', sa.String(length=32), nullable=False),
        sa.Column('unit', sa.String(length=16), nullable=False),
        sa.Column('minimum_value', sa.Integer(), nullable=False),
        sa.Column('maximum_value', sa.Integer(), nullable=False),
        sa.Column('archive_disposition', sa.String(length=24), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("archive_disposition IN ('NO_ARCHIVE', 'EVIDENCE_ONLY', 'CONTENT_WORM')", name=op.f('ck_policy_class_rules_archive_disposition')),
        sa.CheckConstraint("data_class IN ('COMPLETED_OPERATIONS', 'CHAT_CONTENT', 'AUDIT_EVIDENCE', 'OBJECT_DATA')", name=op.f('ck_policy_class_rules_data_class')),
        sa.CheckConstraint("minimum_value >= 0 AND maximum_value >= 1 AND minimum_value <= maximum_value AND ((unit = 'DAYS' AND maximum_value <= 36500) OR (unit = 'MONTHS' AND maximum_value <= 1200) OR (unit = 'YEARS' AND maximum_value <= 100))", name=op.f('ck_policy_class_rules_bounds')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_policy_class_rules_payload_hash_sha256')),
        sa.CheckConstraint("unit IN ('DAYS', 'MONTHS', 'YEARS')", name=op.f('ck_policy_class_rules_unit')),
        sa.ForeignKeyConstraint(['workspace_id', 'policy_id', 'policy_hash', 'policy_number'], ['retention.policy_versions.workspace_id', 'retention.policy_versions.id', 'retention.policy_versions.payload_hash', 'retention.policy_versions.policy_number'], name='fk_retention_policy_class_rules_policy', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_policy_class_rules_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_policy_class_rules')),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_retention_policy_class_rules_workspace_id_id'),
        sa.UniqueConstraint('workspace_id', 'policy_id', 'data_class', name='uq_retention_policy_class_rules_workspace_policy_class'),
        schema='retention'
        )
        op.create_index('ix_retention_policy_class_rules_workspace_policy', 'policy_class_rules', ['workspace_id', 'policy_id', 'data_class'], unique=False, schema='retention')
        op.execute('ALTER TABLE retention.policy_class_rules ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.policy_class_rules FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.policy_class_rules USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('api_product_versions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('release_id', sa.Uuid(), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('surface', sa.String(length=32), nullable=False),
        sa.Column('contract_document', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('maximum_hops', sa.Integer(), nullable=False),
        sa.Column('maximum_nodes', sa.Integer(), nullable=False),
        sa.Column('timeout_ms', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('published_by', sa.Uuid(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'product_id'], ['sharing.api_products.workspace_id', 'sharing.api_products.graph_id', 'sharing.api_products.id'], name=op.f('fk_api_product_versions_workspace_id_graph_id_product_id_api_products'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id', 'release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.graph_id', 'knowledge.releases.id'], name=op.f('fk_api_product_versions_workspace_id_graph_id_release_id_releases')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_api_product_versions')),
        sa.UniqueConstraint('workspace_id', 'product_id', 'id', name=op.f('uq_api_product_versions_workspace_id_product_id_id')),
        sa.UniqueConstraint('workspace_id', 'product_id', 'version_no', name=op.f('uq_api_product_versions_workspace_id_product_id_version_no')),
        schema='sharing'
        )
        op.create_index('ix_api_product_versions_product_state', 'api_product_versions', ['product_id', 'state', 'version_no'], unique=False, schema='sharing')
        op.execute('ALTER TABLE sharing.api_product_versions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE sharing.api_product_versions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON sharing.api_product_versions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('chat_messages',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('session_id', sa.Uuid(), nullable=False),
        sa.Column('actor', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('content_ref', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'session_id'], ['assistant.chat_sessions.workspace_id', 'assistant.chat_sessions.id'], name=op.f('fk_chat_messages_workspace_id_session_id_chat_sessions'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_messages')),
        sa.UniqueConstraint('workspace_id', 'session_id', 'id', name=op.f('uq_chat_messages_workspace_id_session_id_id')),
        schema='assistant'
        )
        op.create_index('ix_chat_messages_session_time', 'chat_messages', ['session_id', 'created_at'], unique=False, schema='assistant')
        op.execute('ALTER TABLE assistant.chat_messages ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE assistant.chat_messages FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON assistant.chat_messages USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('restricted_search_grant_events',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('grant_id', sa.Uuid(), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('reason', sa.String(length=4000), nullable=False),
        sa.Column('policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('grant_version', sa.Integer(), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("action IN ('PROPOSED', 'APPROVED', 'REJECTED', 'REVOKED')", name=op.f('ck_restricted_search_grant_events_action')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_restricted_search_grant_events_payload_hash_sha256')),
        sa.CheckConstraint('grant_version BETWEEN 1 AND 3', name=op.f('ck_restricted_search_grant_events_grant_version')),
        sa.CheckConstraint('length(btrim(reason)) > 0', name=op.f('ck_restricted_search_grant_events_reason_nonempty')),
        sa.ForeignKeyConstraint(['workspace_id', 'actor_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_restricted_search_grant_events_actor_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'grant_id'], ['authz.restricted_search_grants.workspace_id', 'authz.restricted_search_grants.id'], name='fk_restricted_search_grant_events_grant'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_restricted_search_grant_events_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_restricted_search_grant_events')),
        sa.UniqueConstraint('workspace_id', 'grant_id', 'grant_version', name='uq_grant_events_version'),
        schema='authz'
        )
        op.create_index('ix_restricted_search_grant_events_grant', 'restricted_search_grant_events', ['workspace_id', 'grant_id', 'occurred_at'], unique=False, schema='authz')
        op.execute('ALTER TABLE authz.restricted_search_grant_events ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE authz.restricted_search_grant_events FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON authz.restricted_search_grant_events USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('manual_metadata_aspect_reports',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('submission_id', sa.Uuid(), nullable=False),
        sa.Column('attempt_id', sa.Uuid(), nullable=False),
        sa.Column('aspect_name', sa.String(length=64), nullable=False),
        sa.Column('aspect_ordinal', sa.Integer(), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('before_hash', sa.String(length=64), nullable=True),
        sa.Column('expected_hash', sa.String(length=64), nullable=True),
        sa.Column('observed_hash', sa.String(length=64), nullable=True),
        sa.Column('write_attempted', sa.Boolean(), nullable=False),
        sa.Column('failure_code', sa.String(length=100), nullable=True),
        sa.Column('provider_operation_id_hash', sa.String(length=64), nullable=True),
        sa.Column('provider_version', sa.String(length=255), nullable=True),
        sa.Column('provider_response_hash', sa.String(length=64), nullable=True),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(aspect_name = 'datasetProperties' AND aspect_ordinal = 1) OR (aspect_name = 'domains' AND aspect_ordinal = 2) OR (aspect_name = 'globalTags' AND aspect_ordinal = 3) OR (aspect_name = 'glossaryTerms' AND aspect_ordinal = 4) OR (aspect_name = 'schemaMetadata' AND aspect_ordinal = 5)", name=op.f('ck_manual_metadata_aspect_reports_aspect_ordinal_contract')),
        sa.CheckConstraint("(before_hash IS NULL OR before_hash ~ '^[0-9a-f]{64}$') AND (expected_hash IS NULL OR expected_hash ~ '^[0-9a-f]{64}$') AND (observed_hash IS NULL OR observed_hash ~ '^[0-9a-f]{64}$') AND (failure_code IS NULL OR char_length(failure_code) BETWEEN 1 AND 100)", name=op.f('ck_manual_metadata_aspect_reports_content_hashes_valid')),
        sa.CheckConstraint("(outcome = 'ALREADY_MATCHED' AND write_attempted = false AND before_hash = expected_hash AND expected_hash = observed_hash AND failure_code IS NULL AND provider_operation_id_hash IS NULL AND provider_version IS NULL AND provider_response_hash IS NULL) OR (outcome = 'APPLIED_VERIFIED' AND write_attempted = true AND expected_hash = observed_hash AND failure_code IS NULL AND provider_operation_id_hash ~ '^[0-9a-f]{64}$' AND char_length(provider_version) BETWEEN 1 AND 255 AND provider_response_hash ~ '^[0-9a-f]{64}$') OR (outcome = 'FAILED_BEFORE_WRITE' AND write_attempted = false AND before_hash IS NULL AND expected_hash IS NULL AND observed_hash IS NULL AND failure_code IS NOT NULL AND provider_operation_id_hash IS NULL AND provider_version IS NULL AND provider_response_hash IS NULL) OR (outcome = 'WRITE_REJECTED' AND write_attempted = true AND before_hash IS NOT NULL AND expected_hash IS NOT NULL AND observed_hash IS NULL AND failure_code IS NOT NULL AND provider_operation_id_hash IS NULL AND provider_version IS NULL AND provider_response_hash IS NULL) OR (outcome = 'READBACK_FAILED' AND write_attempted = true AND before_hash IS NOT NULL AND expected_hash IS NOT NULL AND observed_hash IS NULL AND failure_code IS NOT NULL AND provider_operation_id_hash ~ '^[0-9a-f]{64}$' AND char_length(provider_version) BETWEEN 1 AND 255 AND provider_response_hash ~ '^[0-9a-f]{64}$') OR (outcome = 'READBACK_MISMATCH' AND write_attempted = true AND before_hash IS NOT NULL AND expected_hash IS NOT NULL AND observed_hash IS NOT NULL AND expected_hash <> observed_hash AND failure_code IS NOT NULL AND provider_operation_id_hash ~ '^[0-9a-f]{64}$' AND char_length(provider_version) BETWEEN 1 AND 255 AND provider_response_hash ~ '^[0-9a-f]{64}$')", name=op.f('ck_manual_metadata_aspect_reports_verified_outcome_shape')),
        sa.CheckConstraint("outcome IN ('ALREADY_MATCHED', 'APPLIED_VERIFIED', 'FAILED_BEFORE_WRITE', 'WRITE_REJECTED', 'READBACK_FAILED', 'READBACK_MISMATCH')", name=op.f('ck_manual_metadata_aspect_reports_outcome_vocabulary')),
        sa.ForeignKeyConstraint(['workspace_id', 'submission_id', 'attempt_id'], ['governance.manual_metadata_apply_attempts.workspace_id', 'governance.manual_metadata_apply_attempts.submission_id', 'governance.manual_metadata_apply_attempts.id'], name='fk_manual_aspect_reports_attempt', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'submission_id'], ['governance.manual_metadata_submissions.workspace_id', 'governance.manual_metadata_submissions.id'], name='fk_manual_aspect_reports_submission', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_manual_metadata_aspect_reports')),
        sa.UniqueConstraint('workspace_id', 'attempt_id', 'aspect_name', name=op.f('uq_manual_metadata_aspect_reports_workspace_id_attempt_id_aspect_name')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_manual_metadata_aspect_reports_workspace_id_id')),
        schema='governance'
        )
        op.create_index('ix_manual_aspect_reports_attempt', 'manual_metadata_aspect_reports', ['workspace_id', 'attempt_id', 'aspect_ordinal'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.manual_metadata_aspect_reports ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.manual_metadata_aspect_reports FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.manual_metadata_aspect_reports USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('catalog_metadata_candidates',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('receipt_id', sa.Uuid(), nullable=False),
        sa.Column('candidate_ordinal', sa.BigInteger(), nullable=False),
        sa.Column('content_profile', sa.String(length=100), nullable=False),
        sa.Column('record_kind', sa.String(length=64), nullable=False),
        sa.Column('candidate_kind', sa.String(length=100), nullable=False),
        sa.Column('evidence_version', sa.String(length=100), nullable=False),
        sa.Column('target_asset_id', sa.Uuid(), nullable=False),
        sa.Column('aspect_name', sa.String(length=64), nullable=False),
        sa.Column('submitted_identity_hash', sa.String(length=64), nullable=False),
        sa.Column('row_count', sa.BigInteger(), nullable=False),
        sa.Column('first_row_ordinal', sa.BigInteger(), nullable=False),
        sa.Column('last_row_ordinal', sa.BigInteger(), nullable=False),
        sa.Column('row_root_hash', sa.String(length=64), nullable=False),
        sa.Column('candidate_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(record_kind = 'TABLE_DESCRIPTION' AND candidate_kind = 'TABLE_DESCRIPTION_UPDATE' AND aspect_name = 'datasetProperties') OR (record_kind = 'COLUMN_DESCRIPTION' AND candidate_kind = 'COLUMN_DESCRIPTION_UPDATE' AND aspect_name = 'schemaMetadata') OR (record_kind = 'DATASET_DOMAIN' AND candidate_kind = 'DATASET_DOMAIN_UPDATE' AND aspect_name = 'domains') OR (record_kind = 'DATASET_TERM' AND candidate_kind = 'DATASET_TERM_ADD' AND aspect_name = 'glossaryTerms') OR (record_kind = 'DATASET_TAG' AND candidate_kind = 'DATASET_TAG_ADD' AND aspect_name = 'globalTags')", name=op.f('ck_catalog_metadata_candidates_record_candidate_aspect_contract')),
        sa.CheckConstraint("content_profile IN ('CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')", name=op.f('ck_catalog_metadata_candidates_content_profile_allowlist')),
        sa.CheckConstraint("evidence_version = 'CATALOG_METADATA_CANDIDATE_V3'", name=op.f('ck_catalog_metadata_candidates_evidence_version_contract')),
        sa.CheckConstraint("submitted_identity_hash ~ '^[0-9a-f]{64}$' AND row_root_hash ~ '^[0-9a-f]{64}$' AND candidate_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_catalog_metadata_candidates_evidence_hashes_valid')),
        sa.CheckConstraint('candidate_ordinal BETWEEN 1 AND 10000', name=op.f('ck_catalog_metadata_candidates_candidate_ordinal_range')),
        sa.CheckConstraint('row_count BETWEEN 1 AND 10000 AND first_row_ordinal BETWEEN 1 AND 10000 AND last_row_ordinal BETWEEN first_row_ordinal AND 10000', name=op.f('ck_catalog_metadata_candidates_ordered_row_span')),
        sa.ForeignKeyConstraint(['workspace_id', 'receipt_id', 'content_profile'], ['integration.upload_preparation_receipts.workspace_id', 'integration.upload_preparation_receipts.id', 'integration.upload_preparation_receipts.content_profile'], name='fk_catalog_metadata_candidates_receipt_profile', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_catalog_metadata_candidates')),
        sa.UniqueConstraint('workspace_id', 'id', 'content_profile', 'candidate_kind', 'aspect_name', 'candidate_hash', name='uq_catalog_metadata_candidates_binding_content'),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_catalog_metadata_candidates_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'candidate_ordinal', name=op.f('uq_catalog_metadata_candidates_workspace_id_receipt_id_candidate_ordinal')),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'id', 'content_profile', 'candidate_hash', name='uq_catalog_metadata_candidates_membership_content'),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'target_asset_id', 'aspect_name', name='uq_catalog_metadata_candidates_target_aspect'),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.catalog_metadata_candidates ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.catalog_metadata_candidates FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.catalog_metadata_candidates USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('catalog_metadata_rows',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('receipt_id', sa.Uuid(), nullable=False),
        sa.Column('ordinal', sa.BigInteger(), nullable=False),
        sa.Column('content_profile', sa.String(length=100), nullable=False),
        sa.Column('evidence_version', sa.String(length=100), nullable=False),
        sa.Column('record_kind', sa.String(length=64), nullable=False),
        sa.Column('aspect_name', sa.String(length=64), nullable=False),
        sa.Column('target_asset_id', sa.Uuid(), nullable=False),
        sa.Column('submitted_platform', sa.String(length=100), nullable=False),
        sa.Column('submitted_database_name', sa.String(length=255), nullable=False),
        sa.Column('submitted_schema_name', sa.String(length=255), nullable=False),
        sa.Column('submitted_table_name', sa.String(length=500), nullable=False),
        sa.Column('field_path', sa.String(length=2000), nullable=True),
        sa.Column('operation', sa.String(length=16), nullable=False),
        sa.Column('value_text', sa.Text(), nullable=True),
        sa.Column('controlled_ref_id', sa.Uuid(), nullable=True),
        sa.Column('controlled_kind', sa.String(length=16), nullable=True),
        sa.Column('submitted_identity_hash', sa.String(length=64), nullable=False),
        sa.Column('semantic_target_hash', sa.String(length=64), nullable=False),
        sa.Column('row_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(record_kind = 'TABLE_DESCRIPTION' AND aspect_name = 'datasetProperties') OR (record_kind = 'COLUMN_DESCRIPTION' AND aspect_name = 'schemaMetadata') OR (record_kind = 'DATASET_DOMAIN' AND aspect_name = 'domains') OR (record_kind = 'DATASET_TERM' AND aspect_name = 'glossaryTerms') OR (record_kind = 'DATASET_TAG' AND aspect_name = 'globalTags')", name=op.f('ck_catalog_metadata_rows_record_kind_aspect_contract')),
        sa.CheckConstraint("(record_kind = 'TABLE_DESCRIPTION' AND field_path IS NULL AND controlled_ref_id IS NULL AND controlled_kind IS NULL AND ((operation = 'SET' AND value_text IS NOT NULL) OR (operation = 'CLEAR' AND value_text IS NULL))) OR (record_kind = 'COLUMN_DESCRIPTION' AND field_path IS NOT NULL AND controlled_ref_id IS NULL AND controlled_kind IS NULL AND ((operation = 'SET' AND value_text IS NOT NULL) OR (operation = 'CLEAR' AND value_text IS NULL))) OR (record_kind = 'DATASET_DOMAIN' AND field_path IS NULL AND value_text IS NULL AND ((operation = 'SET' AND controlled_ref_id IS NOT NULL AND controlled_kind = 'DOMAIN') OR (operation = 'CLEAR' AND controlled_ref_id IS NULL AND controlled_kind IS NULL))) OR (record_kind = 'DATASET_TERM' AND operation = 'ADD' AND field_path IS NULL AND value_text IS NULL AND controlled_ref_id IS NOT NULL AND controlled_kind = 'TERM') OR (record_kind = 'DATASET_TAG' AND operation = 'ADD' AND field_path IS NULL AND value_text IS NULL AND controlled_ref_id IS NOT NULL AND controlled_kind = 'TAG')", name=op.f('ck_catalog_metadata_rows_typed_detail_xor')),
        sa.CheckConstraint("content_profile IN ('CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')", name=op.f('ck_catalog_metadata_rows_content_profile_allowlist')),
        sa.CheckConstraint("controlled_kind IS NULL OR controlled_kind IN ('DOMAIN', 'TAG', 'TERM')", name=op.f('ck_catalog_metadata_rows_controlled_kind_vocabulary')),
        sa.CheckConstraint("evidence_version = 'CATALOG_METADATA_CANDIDATE_V3'", name=op.f('ck_catalog_metadata_rows_evidence_version_contract')),
        sa.CheckConstraint("operation IN ('SET', 'CLEAR', 'ADD')", name=op.f('ck_catalog_metadata_rows_operation_allowlist')),
        sa.CheckConstraint("record_kind IN ('TABLE_DESCRIPTION', 'COLUMN_DESCRIPTION', 'DATASET_DOMAIN', 'DATASET_TERM', 'DATASET_TAG')", name=op.f('ck_catalog_metadata_rows_record_kind_allowlist')),
        sa.CheckConstraint("submitted_identity_hash ~ '^[0-9a-f]{64}$' AND semantic_target_hash ~ '^[0-9a-f]{64}$' AND row_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_catalog_metadata_rows_evidence_hashes_valid')),
        sa.CheckConstraint('char_length(submitted_database_name) BETWEEN 1 AND 255 AND submitted_database_name = btrim(submitted_database_name)', name=op.f('ck_catalog_metadata_rows_submitted_database_name_valid')),
        sa.CheckConstraint('char_length(submitted_platform) BETWEEN 1 AND 100 AND submitted_platform = btrim(submitted_platform)', name=op.f('ck_catalog_metadata_rows_submitted_platform_valid')),
        sa.CheckConstraint('char_length(submitted_schema_name) BETWEEN 1 AND 255 AND submitted_schema_name = btrim(submitted_schema_name)', name=op.f('ck_catalog_metadata_rows_submitted_schema_name_valid')),
        sa.CheckConstraint('char_length(submitted_table_name) BETWEEN 1 AND 500 AND submitted_table_name = btrim(submitted_table_name)', name=op.f('ck_catalog_metadata_rows_submitted_table_name_valid')),
        sa.CheckConstraint('field_path IS NULL OR (char_length(field_path) BETWEEN 1 AND 2000 AND field_path = btrim(field_path))', name=op.f('ck_catalog_metadata_rows_field_path_valid')),
        sa.CheckConstraint('ordinal BETWEEN 1 AND 10000', name=op.f('ck_catalog_metadata_rows_ordinal_range')),
        sa.CheckConstraint('value_text IS NULL OR char_length(value_text) BETWEEN 1 AND 10000', name=op.f('ck_catalog_metadata_rows_value_text_valid')),
        sa.ForeignKeyConstraint(['workspace_id', 'controlled_ref_id', 'controlled_kind'], ['catalog.vocabulary_entries.workspace_id', 'catalog.vocabulary_entries.id', 'catalog.vocabulary_entries.kind'], name='fk_catalog_metadata_rows_vocabulary', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'receipt_id', 'content_profile'], ['integration.upload_preparation_receipts.workspace_id', 'integration.upload_preparation_receipts.id', 'integration.upload_preparation_receipts.content_profile'], name='fk_catalog_metadata_rows_receipt_profile', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_catalog_metadata_rows')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_catalog_metadata_rows_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'id', 'content_profile', 'row_hash', name='uq_catalog_metadata_rows_content'),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'ordinal', name=op.f('uq_catalog_metadata_rows_workspace_id_receipt_id_ordinal')),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'semantic_target_hash', name='uq_catalog_metadata_rows_semantic_target'),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.catalog_metadata_rows ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.catalog_metadata_rows FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.catalog_metadata_rows USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('upload_registration_candidates',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('receipt_id', sa.Uuid(), nullable=False),
        sa.Column('ordinal', sa.BigInteger(), nullable=False),
        sa.Column('target_asset_id', sa.Uuid(), nullable=False),
        sa.Column('candidate_kind', sa.String(length=100), nullable=False),
        sa.Column('proposed_description', sa.Text(), nullable=False),
        sa.Column('evidence_version', sa.String(length=100), server_default='DATASET_DESCRIPTION_CANDIDATE_V2', nullable=False),
        sa.Column('submitted_platform', sa.String(length=100), nullable=True),
        sa.Column('submitted_database_name', sa.String(length=255), nullable=True),
        sa.Column('submitted_schema_name', sa.String(length=255), nullable=True),
        sa.Column('submitted_table_name', sa.String(length=500), nullable=True),
        sa.Column('submitted_identity_hash', sa.String(length=64), nullable=True),
        sa.Column('candidate_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(evidence_version = 'LEGACY_V1' AND submitted_platform IS NULL AND submitted_database_name IS NULL AND submitted_schema_name IS NULL AND submitted_table_name IS NULL AND submitted_identity_hash IS NULL) OR (evidence_version = 'DATASET_DESCRIPTION_CANDIDATE_V2' AND submitted_platform IS NOT NULL AND submitted_database_name IS NOT NULL AND submitted_schema_name IS NOT NULL AND submitted_table_name IS NOT NULL AND submitted_identity_hash ~ '^[0-9a-f]{64}$')", name=op.f('ck_upload_registration_candidates_submitted_identity_evidence_shape')),
        sa.CheckConstraint("candidate_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_registration_candidates_candidate_hash_valid')),
        sa.CheckConstraint("candidate_kind = 'DATASET_DESCRIPTION_UPDATE'", name=op.f('ck_upload_registration_candidates_candidate_kind_allowlist')),
        sa.CheckConstraint("evidence_version IN ('LEGACY_V1', 'DATASET_DESCRIPTION_CANDIDATE_V2')", name=op.f('ck_upload_registration_candidates_evidence_version_allowlist')),
        sa.CheckConstraint('char_length(proposed_description) <= 10000', name=op.f('ck_upload_registration_candidates_description_length')),
        sa.CheckConstraint('ordinal > 0', name=op.f('ck_upload_registration_candidates_ordinal_positive')),
        sa.CheckConstraint('submitted_database_name IS NULL OR (char_length(submitted_database_name) BETWEEN 1 AND 255 AND submitted_database_name = btrim(submitted_database_name))', name=op.f('ck_upload_registration_candidates_submitted_database_name_valid')),
        sa.CheckConstraint('submitted_platform IS NULL OR (char_length(submitted_platform) BETWEEN 1 AND 100 AND submitted_platform = btrim(submitted_platform))', name=op.f('ck_upload_registration_candidates_submitted_platform_valid')),
        sa.CheckConstraint('submitted_schema_name IS NULL OR (char_length(submitted_schema_name) BETWEEN 1 AND 255 AND submitted_schema_name = btrim(submitted_schema_name))', name=op.f('ck_upload_registration_candidates_submitted_schema_name_valid')),
        sa.CheckConstraint('submitted_table_name IS NULL OR (char_length(submitted_table_name) BETWEEN 1 AND 500 AND submitted_table_name = btrim(submitted_table_name))', name=op.f('ck_upload_registration_candidates_submitted_table_name_valid')),
        sa.ForeignKeyConstraint(['workspace_id', 'receipt_id'], ['integration.upload_preparation_receipts.workspace_id', 'integration.upload_preparation_receipts.id'], name='fk_upload_reg_candidates_workspace_receipt', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_registration_candidates')),
        sa.UniqueConstraint('workspace_id', 'id', 'candidate_hash', name='uq_upload_registration_candidate_content'),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_upload_registration_candidates_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'ordinal', name=op.f('uq_upload_registration_candidates_workspace_id_receipt_id_ordinal')),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'target_asset_id', name=op.f('uq_upload_registration_candidates_workspace_id_receipt_id_target_asset_id')),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.upload_registration_candidates ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.upload_registration_candidates FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.upload_registration_candidates USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('extraction_runs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('graph_id', sa.Uuid(), nullable=False),
        sa.Column('source_snapshot_id', sa.Uuid(), nullable=False),
        sa.Column('proposed_changeset_id', sa.Uuid(), nullable=False),
        sa.Column('source_analysis_job_id', sa.Uuid(), nullable=True),
        sa.Column('source_analysis_attempt_id', sa.Uuid(), nullable=True),
        sa.Column('contract_version', sa.String(length=32), server_default='LEGACY_SYNC_V1', nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('parser_config_hash', sa.String(length=64), nullable=False),
        sa.Column('embedding_binding', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('extraction_binding', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('input_hash', sa.String(length=64), nullable=False),
        sa.Column('output_hash', sa.String(length=64), nullable=False),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("contract_version IN ('LEGACY_SYNC_V1', 'DURABLE_SOURCE_V1') AND ((contract_version = 'LEGACY_SYNC_V1' AND source_analysis_job_id IS NULL AND source_analysis_attempt_id IS NULL) OR (contract_version = 'DURABLE_SOURCE_V1' AND source_analysis_job_id IS NOT NULL AND source_analysis_attempt_id IS NOT NULL))", name=op.f('ck_extraction_runs_contract_shape')),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_extraction_runs_input_hash')),
        sa.CheckConstraint("output_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_extraction_runs_output_hash')),
        sa.CheckConstraint("state IN ('SUCCEEDED', 'FAILED')", name=op.f('ck_extraction_runs_state_vocabulary')),
        sa.ForeignKeyConstraint(['workspace_id', 'graph_id'], ['knowledge.graphs.workspace_id', 'knowledge.graphs.id'], name=op.f('fk_extraction_runs_workspace_id_graph_id_graphs'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id', 'proposed_changeset_id'], ['knowledge.changesets.workspace_id', 'knowledge.changesets.id'], name=op.f('fk_extraction_runs_workspace_id_proposed_changeset_id_changesets'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'source_analysis_attempt_id'], ['knowledge.source_analysis_attempts.workspace_id', 'knowledge.source_analysis_attempts.id'], name=op.f('fk_extraction_runs_workspace_id_source_analysis_attempt_id_source_analysis_attempts'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'source_analysis_job_id'], ['knowledge.source_analysis_jobs.workspace_id', 'knowledge.source_analysis_jobs.id'], name=op.f('fk_extraction_runs_workspace_id_source_analysis_job_id_source_analysis_jobs'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'source_snapshot_id'], ['knowledge.source_snapshots.workspace_id', 'knowledge.source_snapshots.id'], name=op.f('fk_extraction_runs_workspace_id_source_snapshot_id_source_snapshots'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_extraction_runs')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_extraction_runs_workspace_id_id')),
        schema='knowledge'
        )
        op.create_index('ix_extraction_runs_graph_created', 'extraction_runs', ['graph_id', 'created_at'], unique=False, schema='knowledge')
        op.execute('ALTER TABLE knowledge.extraction_runs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.extraction_runs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.extraction_runs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('source_analysis_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('attempt_id', sa.Uuid(), nullable=True),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('actor_ref', sa.String(length=255), nullable=False),
        sa.Column('reason_code', sa.String(length=100), nullable=True),
        sa.Column('evidence_hash', sa.String(length=64), nullable=False),
        sa.Column('details', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("evidence_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_source_analysis_events_evidence_hash')),
        sa.CheckConstraint('sequence > 0', name=op.f('ck_source_analysis_events_sequence_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'attempt_id'], ['knowledge.source_analysis_attempts.workspace_id', 'knowledge.source_analysis_attempts.id'], name=op.f('fk_source_analysis_events_workspace_id_attempt_id_source_analysis_attempts'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'job_id'], ['knowledge.source_analysis_jobs.workspace_id', 'knowledge.source_analysis_jobs.id'], name=op.f('fk_source_analysis_events_workspace_id_job_id_source_analysis_jobs'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_analysis_events')),
        sa.UniqueConstraint('workspace_id', 'job_id', 'sequence', name=op.f('uq_source_analysis_events_workspace_id_job_id_sequence')),
        schema='knowledge'
        )
        op.create_index('ix_source_analysis_events_job', 'source_analysis_events', ['workspace_id', 'job_id', 'sequence'], unique=False, schema='knowledge')
        op.create_index('ux_source_analysis_events_transition_evidence', 'source_analysis_events', ['workspace_id', 'job_id', 'event_type', 'occurred_at'], unique=True, schema='knowledge')
        op.execute('ALTER TABLE knowledge.source_analysis_events ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE knowledge.source_analysis_events FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON knowledge.source_analysis_events USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.execute("CREATE POLICY source_analysis_event_owner_select ON knowledge.source_analysis_events AS RESTRICTIVE FOR SELECT TO datariver_app USING (EXISTS (SELECT 1 FROM knowledge.source_analysis_jobs AS job WHERE job.workspace_id = source_analysis_events.workspace_id AND job.id = source_analysis_events.job_id AND job.requested_by = NULLIF(current_setting('app.subject_id', true), '')::uuid))")
        op.create_table('erasure_request_events',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('erasure_request_id', sa.Uuid(), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('reason', sa.String(length=4000), nullable=False),
        sa.Column('policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('request_version', sa.Integer(), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(action = 'CREATED' AND request_version = 1) OR (action IN ('APPROVED', 'REJECTED') AND request_version = 2)", name=op.f('ck_erasure_request_events_action_version_shape')),
        sa.CheckConstraint("action IN ('CREATED', 'APPROVED', 'REJECTED')", name=op.f('ck_erasure_request_events_action')),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_erasure_request_events_payload_hash_sha256')),
        sa.CheckConstraint('length(btrim(reason)) > 0', name=op.f('ck_erasure_request_events_reason_nonempty')),
        sa.CheckConstraint('request_version > 0', name=op.f('ck_erasure_request_events_request_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'actor_id'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_erasure_request_events_actor_membership'),
        sa.ForeignKeyConstraint(['workspace_id', 'erasure_request_id'], ['retention.erasure_requests.workspace_id', 'retention.erasure_requests.id'], name='fk_erasure_request_events_request'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_erasure_request_events_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_erasure_request_events')),
        sa.UniqueConstraint('workspace_id', 'erasure_request_id', 'request_version', name='uq_erasure_request_events_request_version'),
        schema='retention'
        )
        op.create_index('ix_erasure_request_events_workspace_request_time', 'erasure_request_events', ['workspace_id', 'erasure_request_id', 'occurred_at'], unique=False, schema='retention')
        op.execute('ALTER TABLE retention.erasure_request_events ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.erasure_request_events FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.erasure_request_events USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('execution_jobs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('erasure_request_id', sa.Uuid(), nullable=False),
        sa.Column('erasure_request_version', sa.Integer(), nullable=False),
        sa.Column('erasure_request_payload_hash', sa.String(length=64), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False),
        sa.Column('target_id', sa.Uuid(), nullable=False),
        sa.Column('target_version', sa.Integer(), nullable=False),
        sa.Column('target_owner_id', sa.Uuid(), nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('target_snapshot_hash', sa.String(length=64), nullable=False),
        sa.Column('retention_policy_id', sa.Uuid(), nullable=False),
        sa.Column('retention_policy_hash', sa.String(length=64), nullable=False),
        sa.Column('policy_number', sa.Integer(), nullable=False),
        sa.Column('requester_id', sa.Uuid(), nullable=False),
        sa.Column('checker_id', sa.Uuid(), nullable=False),
        sa.Column('executor_id', sa.Uuid(), nullable=False),
        sa.Column('execution_authorization_valid_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archive_disposition', sa.String(length=24), nullable=False),
        sa.Column('archive_configuration_hash', sa.String(length=64), nullable=False),
        sa.Column('command_hash', sa.String(length=64), nullable=False),
        sa.Column('archive_retain_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(length=48), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('maximum_attempts', sa.Integer(), nullable=False),
        sa.Column('lease_epoch', sa.Integer(), nullable=False),
        sa.Column('lease_token_hash', sa.String(length=64), nullable=True),
        sa.Column('lease_owner_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archive_receipt_id', sa.Uuid(), nullable=True),
        sa.Column('archive_manifest_hash', sa.String(length=64), nullable=True),
        sa.Column('last_failure_code', sa.String(length=100), nullable=True),
        sa.Column('destructive_state', sa.String(length=32), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("(state = 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED' AND archive_receipt_id IS NOT NULL AND archive_manifest_hash IS NOT NULL) OR (state = 'BLOCKED' AND (last_failure_code = 'KILL_SWITCH_DISABLED_AFTER_WRITE' OR last_failure_code LIKE 'POST_WRITE_RECEIPT_%') AND archive_receipt_id IS NOT NULL AND archive_manifest_hash IS NOT NULL) OR (state <> 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED' AND COALESCE(last_failure_code, '') <> 'KILL_SWITCH_DISABLED_AFTER_WRITE' AND COALESCE(last_failure_code, '') NOT LIKE 'POST_WRITE_RECEIPT_%' AND archive_receipt_id IS NULL AND archive_manifest_hash IS NULL)", name=op.f('ck_execution_jobs_archive_receipt_shape')),
        sa.CheckConstraint("(state = 'LEASED' AND lease_token_hash IS NOT NULL AND lease_owner_fingerprint IS NOT NULL AND lease_until IS NOT NULL) OR (state <> 'LEASED' AND lease_token_hash IS NULL AND lease_owner_fingerprint IS NULL AND lease_until IS NULL)", name=op.f('ck_execution_jobs_lease_shape')),
        sa.CheckConstraint("archive_disposition = 'EVIDENCE_ONLY'", name=op.f('ck_execution_jobs_archive_disposition')),
        sa.CheckConstraint("command_hash ~ '^[0-9a-f]{64}$' AND erasure_request_payload_hash ~ '^[0-9a-f]{64}$' AND retention_policy_hash ~ '^[0-9a-f]{64}$' AND archive_configuration_hash ~ '^[0-9a-f]{64}$' AND (archive_manifest_hash IS NULL OR archive_manifest_hash ~ '^[0-9a-f]{64}$')", name=op.f('ck_execution_jobs_hashes_sha256')),
        sa.CheckConstraint("destructive_state = 'DISABLED_NOT_READY'", name=op.f('ck_execution_jobs_destructive_disabled')),
        sa.CheckConstraint("kind = 'EXPLICIT_ERASURE_EVIDENCE'", name=op.f('ck_execution_jobs_kind')),
        sa.CheckConstraint("lease_owner_fingerprint IS NULL OR lease_owner_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f('ck_execution_jobs_lease_owner_fingerprint_sha256')),
        sa.CheckConstraint("lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_execution_jobs_lease_token_hash_sha256')),
        sa.CheckConstraint("state IN ('PLANNED', 'LEASED', 'RETRY_WAIT', 'BLOCKED', 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED')", name=op.f('ck_execution_jobs_state')),
        sa.CheckConstraint("target_type = 'CHAT_SESSION' AND target_version > 0 AND target_owner_id IS NOT NULL AND classification BETWEEN 0 AND 3 AND target_snapshot_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_execution_jobs_target_shape')),
        sa.CheckConstraint('archive_retain_until > created_at', name=op.f('ck_execution_jobs_archive_retention_deadline')),
        sa.CheckConstraint('attempt_count >= 0 AND attempt_count <= maximum_attempts AND maximum_attempts BETWEEN 1 AND 20 AND lease_epoch >= 0 AND version > 0', name=op.f('ck_execution_jobs_counters')),
        sa.CheckConstraint('last_failure_code IS NULL OR length(last_failure_code) BETWEEN 1 AND 100', name=op.f('ck_execution_jobs_failure_code')),
        sa.CheckConstraint('requester_id <> checker_id AND checker_id <> target_owner_id AND executor_id <> requester_id AND executor_id <> checker_id AND executor_id <> target_owner_id', name=op.f('ck_execution_jobs_separation_of_duties')),
        sa.ForeignKeyConstraint(['executor_id'], ['iam.subjects.id'], name='fk_retention_execution_jobs_executor', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'archive_receipt_id', 'archive_manifest_hash'], ['retention.immutable_archive_receipts.workspace_id', 'retention.immutable_archive_receipts.id', 'retention.immutable_archive_receipts.manifest_hash'], name='fk_retention_execution_jobs_archive_receipt', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'erasure_request_id', 'erasure_request_version', 'erasure_request_payload_hash'], ['retention.erasure_requests.workspace_id', 'retention.erasure_requests.id', 'retention.erasure_requests.version', 'retention.erasure_requests.payload_hash'], name='fk_retention_execution_jobs_erasure_request', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'retention_policy_id', 'retention_policy_hash', 'policy_number'], ['retention.policy_versions.workspace_id', 'retention.policy_versions.id', 'retention.policy_versions.payload_hash', 'retention.policy_versions.policy_number'], name='fk_retention_execution_jobs_policy', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_execution_jobs_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_execution_jobs')),
        sa.UniqueConstraint('workspace_id', 'command_hash', name='uq_retention_execution_jobs_command_hash'),
        sa.UniqueConstraint('workspace_id', 'erasure_request_id', name='uq_retention_execution_jobs_erasure_request'),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_retention_execution_jobs_workspace_id_id'),
        schema='retention'
        )
        op.create_index('ix_retention_execution_jobs_claim', 'execution_jobs', ['workspace_id', 'next_attempt_at', 'created_at', 'id'], unique=False, schema='retention', postgresql_where=sa.text("state IN ('PLANNED', 'RETRY_WAIT')"))
        op.create_index('ix_retention_execution_jobs_expired_lease', 'execution_jobs', ['workspace_id', 'lease_until', 'id'], unique=False, schema='retention', postgresql_where=sa.text("state = 'LEASED'"))
        op.execute('ALTER TABLE retention.execution_jobs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.execution_jobs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.execution_jobs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('consumer_grants',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('product_version_id', sa.Uuid(), nullable=False),
        sa.Column('consumer_client_id', sa.String(length=255), nullable=False),
        sa.Column('scopes', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('maximum_classification', sa.Integer(), nullable=False),
        sa.Column('requests_per_minute', sa.Integer(), nullable=False),
        sa.Column('monthly_quota', sa.Integer(), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('revoked_by', sa.Uuid(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'product_id', 'product_version_id'], ['sharing.api_product_versions.workspace_id', 'sharing.api_product_versions.product_id', 'sharing.api_product_versions.id'], name=op.f('fk_consumer_grants_workspace_id_product_id_product_version_id_api_product_versions'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_consumer_grants')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_consumer_grants_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'product_version_id', 'consumer_client_id', name=op.f('uq_consumer_grants_workspace_id_product_version_id_consumer_client_id')),
        schema='sharing'
        )
        op.create_index('ix_consumer_grants_client_state', 'consumer_grants', ['workspace_id', 'consumer_client_id', 'state'], unique=False, schema='sharing')
        op.execute('ALTER TABLE sharing.consumer_grants ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE sharing.consumer_grants FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON sharing.consumer_grants USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('assistant_runs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('session_id', sa.Uuid(), nullable=False),
        sa.Column('request_message_id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=255), nullable=False),
        sa.Column('prompt_template_version', sa.String(length=100), nullable=False),
        sa.Column('policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('metrics', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'session_id', 'request_message_id'], ['assistant.chat_messages.workspace_id', 'assistant.chat_messages.session_id', 'assistant.chat_messages.id'], name=op.f('fk_assistant_runs_workspace_id_session_id_request_message_id_chat_messages')),
        sa.ForeignKeyConstraint(['workspace_id', 'session_id'], ['assistant.chat_sessions.workspace_id', 'assistant.chat_sessions.id'], name=op.f('fk_assistant_runs_workspace_id_session_id_chat_sessions'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_assistant_runs')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_assistant_runs_workspace_id_id')),
        schema='assistant'
        )
        op.create_index('ix_assistant_runs_session', 'assistant_runs', ['session_id', 'started_at'], unique=False, schema='assistant')
        op.execute('ALTER TABLE assistant.assistant_runs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE assistant.assistant_runs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON assistant.assistant_runs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('registration_content_bindings',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('candidate_id', sa.Uuid(), nullable=False),
        sa.Column('candidate_hash', sa.String(length=64), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('change_item_id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("candidate_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_registration_content_bindings_candidate_hash_valid')),
        sa.ForeignKeyConstraint(['workspace_id', 'candidate_id', 'candidate_hash'], ['integration.upload_registration_candidates.workspace_id', 'integration.upload_registration_candidates.id', 'integration.upload_registration_candidates.candidate_hash'], name='fk_reg_content_bindings_candidate_content', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id', 'change_item_id'], ['governance.change_request_items.workspace_id', 'governance.change_request_items.change_request_id', 'governance.change_request_items.id'], name='fk_reg_content_bindings_request_item', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name='fk_reg_content_bindings_workspace_request', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'created_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_reg_content_bindings_workspace_creator', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_registration_content_bindings')),
        sa.UniqueConstraint('workspace_id', 'candidate_id', name=op.f('uq_registration_content_bindings_workspace_id_candidate_id')),
        sa.UniqueConstraint('workspace_id', 'change_item_id', name=op.f('uq_registration_content_bindings_workspace_id_change_item_id')),
        sa.UniqueConstraint('workspace_id', 'change_request_id', name=op.f('uq_registration_content_bindings_workspace_id_change_request_id')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_registration_content_bindings_workspace_id_id')),
        schema='governance'
        )
        op.execute('ALTER TABLE governance.registration_content_bindings ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.registration_content_bindings FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.registration_content_bindings USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('registration_metadata_content_bindings',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('candidate_id', sa.Uuid(), nullable=False),
        sa.Column('candidate_hash', sa.String(length=64), nullable=False),
        sa.Column('content_profile', sa.String(length=100), nullable=False),
        sa.Column('candidate_kind', sa.String(length=100), nullable=False),
        sa.Column('aspect_name', sa.String(length=64), nullable=False),
        sa.Column('before_hash', sa.String(length=64), nullable=False),
        sa.Column('after_hash', sa.String(length=64), nullable=False),
        sa.Column('item_contract_hash', sa.String(length=64), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('change_item_id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("(candidate_kind = 'TABLE_DESCRIPTION_UPDATE' AND aspect_name = 'datasetProperties') OR (candidate_kind = 'COLUMN_DESCRIPTION_UPDATE' AND aspect_name = 'schemaMetadata') OR (candidate_kind = 'DATASET_DOMAIN_UPDATE' AND aspect_name = 'domains') OR (candidate_kind = 'DATASET_TERM_ADD' AND aspect_name = 'glossaryTerms') OR (candidate_kind = 'DATASET_TAG_ADD' AND aspect_name = 'globalTags')", name=op.f('ck_registration_metadata_content_bindings_candidate_aspect')),
        sa.CheckConstraint("candidate_hash ~ '^[0-9a-f]{64}$' AND before_hash ~ '^[0-9a-f]{64}$' AND after_hash ~ '^[0-9a-f]{64}$' AND item_contract_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_registration_metadata_content_bindings_content_hashes_valid')),
        sa.CheckConstraint("content_profile IN ('CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')", name=op.f('ck_registration_metadata_content_bindings_content_profile_allowlist')),
        sa.ForeignKeyConstraint(['workspace_id', 'candidate_id', 'content_profile', 'candidate_kind', 'aspect_name', 'candidate_hash'], ['integration.catalog_metadata_candidates.workspace_id', 'integration.catalog_metadata_candidates.id', 'integration.catalog_metadata_candidates.content_profile', 'integration.catalog_metadata_candidates.candidate_kind', 'integration.catalog_metadata_candidates.aspect_name', 'integration.catalog_metadata_candidates.candidate_hash'], name='fk_registration_metadata_bindings_candidate_content', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id', 'change_item_id', 'aspect_name', 'before_hash', 'after_hash', 'item_contract_hash'], ['governance.change_request_items.workspace_id', 'governance.change_request_items.change_request_id', 'governance.change_request_items.id', 'governance.change_request_items.aspect_name', 'governance.change_request_items.before_hash', 'governance.change_request_items.after_hash', 'governance.change_request_items.item_contract_hash'], name='fk_registration_metadata_bindings_request_item', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name='fk_registration_metadata_bindings_request', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'created_by'], ['iam.workspace_memberships.workspace_id', 'iam.workspace_memberships.subject_id'], name='fk_registration_metadata_bindings_creator', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_registration_metadata_content_bindings')),
        sa.UniqueConstraint('workspace_id', 'candidate_id', name=op.f('uq_registration_metadata_content_bindings_workspace_id_candidate_id')),
        sa.UniqueConstraint('workspace_id', 'change_item_id', name=op.f('uq_registration_metadata_content_bindings_workspace_id_change_item_id')),
        sa.UniqueConstraint('workspace_id', 'change_request_id', name=op.f('uq_registration_metadata_content_bindings_workspace_id_change_request_id')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_registration_metadata_content_bindings_workspace_id_id')),
        schema='governance'
        )
        op.execute('ALTER TABLE governance.registration_metadata_content_bindings ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.registration_metadata_content_bindings FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.registration_metadata_content_bindings USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('catalog_metadata_candidate_rows',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('receipt_id', sa.Uuid(), nullable=False),
        sa.Column('candidate_id', sa.Uuid(), nullable=False),
        sa.Column('row_id', sa.Uuid(), nullable=False),
        sa.Column('content_profile', sa.String(length=100), nullable=False),
        sa.Column('candidate_hash', sa.String(length=64), nullable=False),
        sa.Column('row_hash', sa.String(length=64), nullable=False),
        sa.Column('member_ordinal', sa.BigInteger(), nullable=False),
        sa.Column('source_ordinal', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("candidate_hash ~ '^[0-9a-f]{64}$' AND row_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_catalog_metadata_candidate_rows_content_hashes_valid')),
        sa.CheckConstraint("content_profile IN ('CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')", name=op.f('ck_catalog_metadata_candidate_rows_content_profile_allowlist')),
        sa.CheckConstraint('member_ordinal BETWEEN 1 AND 10000 AND source_ordinal BETWEEN 1 AND 10000', name=op.f('ck_catalog_metadata_candidate_rows_ordinal_range')),
        sa.ForeignKeyConstraint(['workspace_id', 'receipt_id', 'candidate_id', 'content_profile', 'candidate_hash'], ['integration.catalog_metadata_candidates.workspace_id', 'integration.catalog_metadata_candidates.receipt_id', 'integration.catalog_metadata_candidates.id', 'integration.catalog_metadata_candidates.content_profile', 'integration.catalog_metadata_candidates.candidate_hash'], name='fk_catalog_metadata_candidate_rows_candidate', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'receipt_id', 'row_id', 'content_profile', 'row_hash'], ['integration.catalog_metadata_rows.workspace_id', 'integration.catalog_metadata_rows.receipt_id', 'integration.catalog_metadata_rows.id', 'integration.catalog_metadata_rows.content_profile', 'integration.catalog_metadata_rows.row_hash'], name='fk_catalog_metadata_candidate_rows_row', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('workspace_id', 'receipt_id', 'candidate_id', 'row_id', name=op.f('pk_catalog_metadata_candidate_rows')),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'candidate_id', 'member_ordinal', name='uq_catalog_metadata_candidate_rows_member'),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'candidate_id', 'source_ordinal', name='uq_catalog_metadata_candidate_rows_source_ordinal'),
        sa.UniqueConstraint('workspace_id', 'receipt_id', 'row_id', name='uq_catalog_metadata_candidate_rows_row'),
        schema='integration'
        )
        op.execute('ALTER TABLE integration.catalog_metadata_candidate_rows ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.catalog_metadata_candidate_rows FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.catalog_metadata_candidate_rows USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('execution_attempts',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('execution_job_id', sa.Uuid(), nullable=False),
        sa.Column('attempt_no', sa.Integer(), nullable=False),
        sa.Column('lease_epoch', sa.Integer(), nullable=False),
        sa.Column('lease_token_hash', sa.String(length=64), nullable=False),
        sa.Column('worker_principal_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('correlation_id', sa.String(length=100), nullable=False),
        sa.Column('state', sa.String(length=48), nullable=False),
        sa.Column('stage', sa.String(length=40), nullable=False),
        sa.Column('evidence_hash', sa.String(length=64), nullable=False),
        sa.Column('external_response_hash', sa.String(length=64), nullable=True),
        sa.Column('failure_code', sa.String(length=100), nullable=True),
        sa.Column('destructive_effect_count', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("evidence_hash ~ '^[0-9a-f]{64}$' AND (external_response_hash IS NULL OR external_response_hash ~ '^[0-9a-f]{64}$')", name=op.f('ck_execution_attempts_evidence_hashes')),
        sa.CheckConstraint("lease_token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_execution_attempts_lease_token_hash')),
        sa.CheckConstraint("state IN ('RUNNING', 'RETRY_WAIT', 'BLOCKED', 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED', 'SUPERSEDED')", name=op.f('ck_execution_attempts_state')),
        sa.CheckConstraint("worker_principal_fingerprint ~ '^[0-9a-f]{64}$'", name=op.f('ck_execution_attempts_worker_principal_fingerprint_sha256')),
        sa.CheckConstraint('attempt_no > 0 AND lease_epoch > 0', name=op.f('ck_execution_attempts_positive_fence')),
        sa.CheckConstraint('destructive_effect_count = 0', name=op.f('ck_execution_attempts_destructive_effect_zero')),
        sa.CheckConstraint('finished_at IS NULL OR finished_at >= started_at', name=op.f('ck_execution_attempts_timeline')),
        sa.CheckConstraint('length(correlation_id) BETWEEN 1 AND 100 AND (failure_code IS NULL OR length(failure_code) BETWEEN 1 AND 100)', name=op.f('ck_execution_attempts_bounded_text')),
        sa.ForeignKeyConstraint(['workspace_id', 'execution_job_id'], ['retention.execution_jobs.workspace_id', 'retention.execution_jobs.id'], name='fk_retention_execution_attempts_job', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_execution_attempts_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_execution_attempts')),
        sa.UniqueConstraint('workspace_id', 'execution_job_id', 'lease_epoch', name='uq_retention_execution_attempts_job_fence'),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_retention_execution_attempts_workspace_id_id'),
        schema='retention'
        )
        op.execute('ALTER TABLE retention.execution_attempts ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.execution_attempts FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.execution_attempts USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('execution_events',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('execution_job_id', sa.Uuid(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=48), nullable=False),
        sa.Column('attempt_no', sa.Integer(), nullable=True),
        sa.Column('reason_code', sa.String(length=100), nullable=True),
        sa.Column('evidence_hash', sa.String(length=64), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("event_type IN ('PLANNED', 'LEASED', 'RETRY_WAIT', 'BLOCKED', 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED')", name=op.f('ck_execution_events_event_type')),
        sa.CheckConstraint("evidence_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_execution_events_evidence_hash_sha256')),
        sa.CheckConstraint('reason_code IS NULL OR length(reason_code) BETWEEN 1 AND 100', name=op.f('ck_execution_events_reason_code')),
        sa.CheckConstraint('sequence > 0', name=op.f('ck_execution_events_sequence_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'execution_job_id'], ['retention.execution_jobs.workspace_id', 'retention.execution_jobs.id'], name='fk_retention_execution_events_job', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_execution_events_workspace_id_workspaces')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_execution_events')),
        sa.UniqueConstraint('workspace_id', 'execution_job_id', 'sequence', name='uq_retention_execution_events_job_sequence'),
        sa.UniqueConstraint('workspace_id', 'id', name='uq_retention_execution_events_workspace_id_id'),
        schema='retention'
        )
        op.create_index('ix_retention_execution_events_workspace_job_time', 'execution_events', ['workspace_id', 'execution_job_id', 'occurred_at'], unique=False, schema='retention')
        op.execute('ALTER TABLE retention.execution_events ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE retention.execution_events FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON retention.execution_events USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('api_invocations',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('grant_id', sa.Uuid(), nullable=False),
        sa.Column('invocation_key', sa.String(length=200), nullable=False),
        sa.Column('requested_scope', sa.String(length=100), nullable=False),
        sa.Column('request_id', sa.String(length=100), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('units', sa.Integer(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'grant_id'], ['sharing.consumer_grants.workspace_id', 'sharing.consumer_grants.id'], name=op.f('fk_api_invocations_workspace_id_grant_id_consumer_grants'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_api_invocations')),
        sa.UniqueConstraint('workspace_id', 'grant_id', 'invocation_key', name=op.f('uq_api_invocations_workspace_id_grant_id_invocation_key')),
        schema='sharing'
        )
        op.create_index('ix_api_invocations_grant_time', 'api_invocations', ['grant_id', 'occurred_at'], unique=False, schema='sharing')
        op.execute('ALTER TABLE sharing.api_invocations ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE sharing.api_invocations FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON sharing.api_invocations USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('evidence_citations',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=False),
        sa.Column('chunk_id', sa.Uuid(), nullable=False),
        sa.Column('resource_id', sa.Uuid(), nullable=False),
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('system_id', sa.Uuid(), nullable=True),
        sa.Column('domain_id', sa.Uuid(), nullable=True),
        sa.Column('owner_department_id', sa.Uuid(), nullable=True),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('source_locator', sa.Text(), nullable=False),
        sa.Column('source_version', sa.String(length=255), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('effective_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('extraction_method', sa.String(length=100), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_evidence_citations_content_hash_sha256')),
        sa.CheckConstraint('classification >= 0 AND classification <= 3', name=op.f('ck_evidence_citations_classification_range')),
        sa.CheckConstraint('effective_until IS NULL OR effective_until >= effective_from', name=op.f('ck_evidence_citations_effective_window')),
        sa.CheckConstraint('rank > 0', name=op.f('ck_evidence_citations_rank_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'run_id'], ['assistant.assistant_runs.workspace_id', 'assistant.assistant_runs.id'], name=op.f('fk_evidence_citations_workspace_id_run_id_assistant_runs'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence_citations')),
        sa.UniqueConstraint('workspace_id', 'run_id', 'chunk_id', name=op.f('uq_evidence_citations_workspace_id_run_id_chunk_id')),
        sa.UniqueConstraint('workspace_id', 'run_id', 'rank', name=op.f('uq_evidence_citations_workspace_id_run_id_rank')),
        schema='assistant'
        )
        op.create_index('ix_evidence_citations_run_rank', 'evidence_citations', ['run_id', 'rank'], unique=False, schema='assistant')
        op.execute('ALTER TABLE assistant.evidence_citations ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE assistant.evidence_citations FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON assistant.evidence_citations USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.execute("CREATE FUNCTION integration.reject_object_manifest_content_profile_change()\nRETURNS trigger\nLANGUAGE plpgsql\nSECURITY INVOKER\nSET search_path = pg_catalog\nAS $function$\nBEGIN\n    IF NEW.content_profile IS DISTINCT FROM OLD.content_profile THEN\n        RAISE EXCEPTION 'object manifest content_profile is immutable'\n            USING ERRCODE = '23514';\n    END IF;\n    RETURN NEW;\nEND\n$function$")
        op.execute('CREATE TRIGGER reject_object_manifest_content_profile_change\nBEFORE UPDATE OF content_profile ON integration.object_manifests\nFOR EACH ROW\nEXECUTE FUNCTION integration.reject_object_manifest_content_profile_change()')
        op.execute("CREATE FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()\nRETURNS trigger\nLANGUAGE plpgsql\nSECURITY INVOKER\nSET search_path = pg_catalog\nAS $function$\nBEGIN\n    IF TG_OP = 'INSERT' AND NEW.evidence_version <> 'DATASET_DESCRIPTION_CANDIDATE_V2' THEN\n        RAISE EXCEPTION 'new upload registration candidates require V2 evidence'\n            USING ERRCODE = '23514';\n    END IF;\n    IF TG_OP IN ('UPDATE', 'DELETE') THEN\n        RAISE EXCEPTION 'upload registration candidate evidence is immutable'\n            USING ERRCODE = '23514';\n    END IF;\n    RETURN NEW;\nEND\n$function$")
        op.execute('CREATE TRIGGER reject_upload_registration_candidate_evidence_mutation\nBEFORE INSERT OR UPDATE OR DELETE ON integration.upload_registration_candidates\nFOR EACH ROW\nEXECUTE FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()')
        op.execute("CREATE FUNCTION assistant.enforce_chat_session_retention_binding()\nRETURNS trigger\nLANGUAGE plpgsql\nSECURITY INVOKER\nSET search_path = pg_catalog\nAS $function$\nDECLARE\n    policy_days integer;\nBEGIN\n    IF TG_OP = 'UPDATE' THEN\n        IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id\n           OR NEW.owner_id IS DISTINCT FROM OLD.owner_id\n           OR NEW.created_at IS DISTINCT FROM OLD.created_at\n           OR NEW.retention_until IS DISTINCT FROM OLD.retention_until\n           OR NEW.retention_policy_id IS DISTINCT FROM OLD.retention_policy_id\n           OR NEW.retention_policy_hash IS DISTINCT FROM OLD.retention_policy_hash\n           OR NEW.retention_basis_at IS DISTINCT FROM OLD.retention_basis_at\n           OR NEW.retention_binding_version IS DISTINCT FROM OLD.retention_binding_version THEN\n            RAISE EXCEPTION 'Chat session retention evidence is immutable'\n                USING ERRCODE = '23514';\n        END IF;\n        RETURN NEW;\n    END IF;\n\n    IF NEW.retention_binding_version <> 'ACTIVE_POLICY_V1' THEN\n        RAISE EXCEPTION 'new Chat sessions require an active-policy retention binding'\n            USING ERRCODE = '23514';\n    END IF;\n\n    SELECT policy.chat_content_days\n    INTO policy_days\n    FROM retention.policy_versions AS policy\n    WHERE policy.workspace_id = NEW.workspace_id\n      AND policy.id = NEW.retention_policy_id\n      AND policy.payload_hash = NEW.retention_policy_hash\n      AND policy.state = 'ACTIVE'\n    FOR KEY SHARE;\n\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'Chat retention policy binding is not active'\n            USING ERRCODE = '23514';\n    END IF;\n    IF NEW.retention_basis_at IS DISTINCT FROM transaction_timestamp() THEN\n        RAISE EXCEPTION 'Chat retention basis must equal the persistence transaction time'\n            USING ERRCODE = '23514';\n    END IF;\n    IF NEW.retention_until IS DISTINCT FROM\n       NEW.retention_basis_at + make_interval(days => policy_days) THEN\n        RAISE EXCEPTION 'Chat retention deadline does not match the active policy'\n            USING ERRCODE = '23514';\n    END IF;\n    RETURN NEW;\nEND\n$function$")
        op.execute('CREATE TRIGGER enforce_chat_session_retention_binding\nBEFORE INSERT OR UPDATE ON assistant.chat_sessions\nFOR EACH ROW\nEXECUTE FUNCTION assistant.enforce_chat_session_retention_binding()')
        op.execute("CREATE FUNCTION assistant.enforce_chat_message_retention_binding()\nRETURNS trigger\nLANGUAGE plpgsql\nSECURITY INVOKER\nSET search_path = pg_catalog\nAS $function$\nBEGIN\n    PERFORM 1\n    FROM assistant.chat_sessions AS session\n    JOIN retention.policy_versions AS policy\n      ON policy.workspace_id = session.workspace_id\n     AND policy.id = session.retention_policy_id\n     AND policy.payload_hash = session.retention_policy_hash\n    WHERE session.workspace_id = NEW.workspace_id\n      AND session.id = NEW.session_id\n      AND session.owner_id =\n          NULLIF(current_setting('app.subject_id', true), '')::uuid\n      AND session.retention_binding_version = 'ACTIVE_POLICY_V1'\n      AND session.retention_until > transaction_timestamp()\n      AND policy.state = 'ACTIVE'\n    FOR KEY SHARE OF session, policy;\n\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'Chat session is not appendable under the active retention policy'\n            USING ERRCODE = '23514';\n    END IF;\n    RETURN NEW;\nEND\n$function$")
        op.execute('CREATE TRIGGER enforce_chat_message_retention_binding\nBEFORE INSERT ON assistant.chat_messages\nFOR EACH ROW\nEXECUTE FUNCTION assistant.enforce_chat_message_retention_binding()')
        op.execute("CREATE OR REPLACE FUNCTION iam.provision_workspace_identity(\n    p_subject_id uuid, p_workspace_id uuid, p_issuer text, p_external_subject text,\n    p_display_name text, p_email text, p_department_id uuid, p_job_function text,\n    p_role_id uuid, p_access_expires_at timestamptz\n)\nRETURNS uuid\nLANGUAGE plpgsql\nSECURITY DEFINER\nSET search_path = pg_catalog, iam, platform\nAS $datariver$\nDECLARE\n    actor_id uuid;\n    existing_subject_id uuid;\n    access_clearance integer := 0;\n    access_attributes jsonb := jsonb_build_object(\n        'groups', jsonb_build_array(), 'allowed_actions', jsonb_build_array(),\n        'denied_actions', jsonb_build_array(), 'allowed_system_ids', jsonb_build_array(),\n        'allowed_domain_ids', jsonb_build_array(), 'default_workspace', true,\n        'managed_by', 'IDENTITY_PROVISIONING_V1'\n    );\n    selected_role iam.access_roles%ROWTYPE;\nBEGIN\n    actor_id := NULLIF(current_setting('app.subject_id', true), '')::uuid;\n    IF actor_id IS NULL OR NULLIF(current_setting('app.workspace_id', true), '')::uuid\n       IS DISTINCT FROM p_workspace_id THEN\n        RAISE EXCEPTION 'A matching DataRiver security context is required'\n            USING ERRCODE = '42501';\n    END IF;\n    IF p_access_expires_at <= transaction_timestamp()\n       OR p_access_expires_at > transaction_timestamp() + INTERVAL '7 months' THEN\n        RAISE EXCEPTION 'The initial access expiration is outside the governed bound'\n            USING ERRCODE = '23514';\n    END IF;\n    PERFORM 1\n    FROM iam.workspace_memberships AS membership\n    JOIN iam.subjects AS subject ON subject.id = membership.subject_id\n    JOIN platform.workspaces AS workspace ON workspace.id = membership.workspace_id\n    WHERE membership.workspace_id = p_workspace_id\n      AND membership.subject_id = actor_id\n      AND subject.active IS TRUE AND membership.active IS TRUE\n      AND workspace.status = 'ACTIVE'\n      AND (membership.access_expires_at IS NULL\n           OR membership.access_expires_at > transaction_timestamp())\n      AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'\n      AND membership.clearance >= 3\n      AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb)\n          ? 'security-administrators'\n      AND NOT (COALESCE(membership.attributes -> 'groups', '[]'::jsonb)\n          ? 'service-accounts')\n      AND COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb)\n          ? 'admin.manage'\n      AND NOT (COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb)\n          ? 'admin.manage')\n    FOR KEY SHARE OF membership, subject, workspace;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'An eligible human security administrator is required'\n            USING ERRCODE = '42501';\n    END IF;\n    IF p_role_id IS NOT NULL THEN\n        SELECT * INTO selected_role FROM iam.access_roles\n        WHERE workspace_id = p_workspace_id AND id = p_role_id AND active IS TRUE\n        FOR KEY SHARE;\n        IF NOT FOUND THEN\n            RAISE EXCEPTION 'The selected workspace role is not active'\n                USING ERRCODE = '23503';\n        END IF;\n        access_clearance := selected_role.clearance;\n        access_attributes := jsonb_build_object(\n            'groups', selected_role.groups\n                || jsonb_build_array('datariver-role-' || selected_role.role_key),\n            'allowed_actions', selected_role.allowed_actions,\n            'denied_actions', selected_role.denied_actions,\n            'allowed_system_ids', selected_role.allowed_system_ids,\n            'allowed_domain_ids', selected_role.allowed_domain_ids,\n            'default_workspace', true, 'role_id', selected_role.id::text,\n            'managed_by', 'IDENTITY_PROVISIONING_V1'\n        );\n    END IF;\n    SELECT id INTO existing_subject_id FROM iam.subjects\n    WHERE issuer = p_issuer AND external_subject = p_external_subject FOR KEY SHARE;\n    IF FOUND THEN\n        IF existing_subject_id IS DISTINCT FROM p_subject_id THEN\n            RAISE EXCEPTION 'The external identity is already bound to another subject'\n                USING ERRCODE = '23505';\n        END IF;\n        RETURN existing_subject_id;\n    END IF;\n    INSERT INTO iam.subjects (\n        id, issuer, external_subject, display_name, email, active, created_at, updated_at\n    ) VALUES (\n        p_subject_id, p_issuer, p_external_subject, p_display_name, p_email, TRUE,\n        transaction_timestamp(), transaction_timestamp()\n    );\n    INSERT INTO iam.workspace_memberships (\n        workspace_id, subject_id, department_id, job_function, clearance, attributes,\n        active, access_expires_at, version, created_at, updated_at\n    ) VALUES (\n        p_workspace_id, p_subject_id, p_department_id, p_job_function,\n        access_clearance, access_attributes, TRUE, p_access_expires_at,\n        1, transaction_timestamp(), transaction_timestamp()\n    );\n    RETURN p_subject_id;\nEND\n$datariver$")
        op.execute('REVOKE ALL ON FUNCTION iam.provision_workspace_identity(uuid, uuid, text, text, text, text, uuid, text, uuid, timestamptz) FROM PUBLIC')
        op.execute("\n        CREATE FUNCTION iam.resolve_default_workspace(\n            p_issuer text,\n            p_external_subject text\n        )\n        RETURNS uuid\n        LANGUAGE sql\n        STABLE\n        SECURITY DEFINER\n        SET search_path = pg_catalog, iam, platform\n        AS $datariver$\n            SELECT membership.workspace_id\n            FROM iam.subjects AS subject\n            JOIN iam.workspace_memberships AS membership\n              ON membership.subject_id = subject.id\n            JOIN platform.workspaces AS workspace\n              ON workspace.id = membership.workspace_id\n            WHERE subject.issuer = p_issuer\n              AND subject.external_subject = p_external_subject\n              AND subject.active IS TRUE\n              AND membership.active IS TRUE\n              AND (\n                  membership.access_expires_at IS NULL\n                  OR membership.access_expires_at > CURRENT_TIMESTAMP\n              )\n              AND workspace.status = 'ACTIVE'\n            ORDER BY\n              CASE WHEN membership.attributes ->> 'default_workspace' = 'true'\n                THEN 0 ELSE 1 END,\n              workspace.slug ASC,\n              membership.workspace_id ASC\n            LIMIT 1\n        $datariver$\n        ")
        op.execute('REVOKE ALL ON FUNCTION iam.resolve_default_workspace(text, text) FROM PUBLIC')
        op.create_foreign_key(op.f('fk_api_products_workspace_id_id_current_version_id_api_product_versions'), 'api_products', 'api_product_versions', ['workspace_id', 'id', 'current_version_id'], ['workspace_id', 'product_id', 'id'], source_schema='sharing', referent_schema='sharing', use_alter=True)
        op.create_foreign_key('fk_catalog_export_requests_workspace_job', 'export_requests', 'jobs', ['workspace_id', 'job_id'], ['workspace_id', 'id'], source_schema='catalog', referent_schema='integration', ondelete='RESTRICT', use_alter=True)
        op.create_foreign_key('fk_change_requests_current_round', 'change_requests', 'change_request_rounds', ['workspace_id', 'id', 'current_round_id'], ['workspace_id', 'change_request_id', 'id'], source_schema='governance', referent_schema='governance', initially='DEFERRED', deferrable=True, use_alter=True)
        op.create_foreign_key(op.f('fk_changesets_workspace_id_graph_id_base_release_id_releases'), 'changesets', 'releases', ['workspace_id', 'graph_id', 'base_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', use_alter=True)
        op.create_foreign_key(op.f('fk_changesets_workspace_id_graph_id_published_release_id_releases'), 'changesets', 'releases', ['workspace_id', 'graph_id', 'published_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', use_alter=True)
        op.create_foreign_key(op.f('fk_changesets_workspace_id_source_analysis_job_id_source_analysis_jobs'), 'changesets', 'source_analysis_jobs', ['workspace_id', 'source_analysis_job_id'], ['workspace_id', 'id'], source_schema='knowledge', referent_schema='knowledge', ondelete='RESTRICT', use_alter=True)
        op.create_foreign_key(op.f('fk_graphs_workspace_id_id_active_release_id_releases'), 'graphs', 'releases', ['workspace_id', 'id', 'active_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', use_alter=True)
        op.create_foreign_key(op.f('fk_source_analysis_jobs_workspace_id_graph_id_base_release_id_releases'), 'source_analysis_jobs', 'releases', ['workspace_id', 'graph_id', 'base_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', ondelete='RESTRICT', use_alter=True)
        op.create_foreign_key(op.f('fk_source_analysis_jobs_workspace_id_graph_id_result_changeset_id_changesets'), 'source_analysis_jobs', 'changesets', ['workspace_id', 'graph_id', 'result_changeset_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', ondelete='RESTRICT', use_alter=True)
        op.execute("DO $datariver$\nBEGIN\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN\n        GRANT USAGE ON SCHEMA platform, iam, authz, catalog, governance, integration, knowledge, assistant, sharing, retention TO datariver_app;\n        GRANT USAGE ON SCHEMA public TO datariver_app;\n        GRANT SELECT ON public.alembic_version TO datariver_app;\n        GRANT SELECT ON platform.workspaces, iam.subjects TO datariver_app;\n        GRANT UPDATE (email, last_login_at, last_login_ip, updated_at)\n            ON iam.subjects TO datariver_app;\n        GRANT SELECT ON iam.workspace_memberships TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON iam.membership_renewal_requests TO datariver_app;\n        GRANT SELECT, INSERT ON iam.access_roles TO datariver_app;\n        GRANT UPDATE (name, description, clearance, groups, allowed_actions, denied_actions,\n            allowed_system_ids, allowed_domain_ids, active, updated_by, version, updated_at)\n            ON iam.access_roles TO datariver_app;\n        GRANT SELECT, INSERT ON iam.access_role_data_rules,\n            iam.access_role_assignment_events TO datariver_app;\n        GRANT SELECT, INSERT ON iam.access_role_assignments TO datariver_app;\n        GRANT UPDATE (role_id, role_version, membership_version, access_payload_hash,\n            assigned_by, active, version, updated_at)\n            ON iam.access_role_assignments TO datariver_app;\n        GRANT EXECUTE ON FUNCTION iam.resolve_default_workspace(text, text) TO datariver_app;\n        GRANT EXECUTE ON FUNCTION iam.provision_workspace_identity(uuid, uuid, text, text, text, text, uuid, text, uuid, timestamptz) TO datariver_app;\n        GRANT UPDATE (active, clearance, attributes, version, updated_at)\n            ON iam.workspace_memberships TO datariver_app;\n        GRANT UPDATE (access_expires_at, version, updated_at)\n            ON iam.workspace_memberships TO datariver_app;\n        GRANT SELECT, INSERT ON iam.admin_access_requests TO datariver_app;\n        GRANT UPDATE (state, checker_id, consumed_by, consumed_at,\n            consume_policy_decision_id, version, updated_at)\n            ON iam.admin_access_requests TO datariver_app;\n        GRANT SELECT, INSERT ON iam.admin_access_approvals TO datariver_app;\n        GRANT INSERT ON authz.policy_decisions TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON catalog.assets_projection,\n            catalog.sync_runs, catalog.projection_watermarks TO datariver_app;\n        GRANT SELECT, INSERT ON catalog.export_requests TO datariver_app;\n        GRANT SELECT, INSERT ON governance.change_request_items,\n            governance.approvals, governance.state_transitions TO datariver_app;\n        GRANT SELECT, INSERT ON governance.change_request_attachments TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON governance.change_request_rounds TO datariver_app;\n        GRANT SELECT, INSERT ON governance.change_test_runs TO datariver_app;\n        GRANT SELECT, INSERT ON governance.registration_content_bindings TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON governance.change_requests TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON platform.data_systems, platform.system_schema_scopes,\n            platform.system_assignees, platform.external_service_profiles TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON platform.external_service_profile_versions\n            TO datariver_app;\n        GRANT SELECT ON integration.jobs, integration.job_attempts TO datariver_app;\n        GRANT INSERT ON integration.jobs TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON integration.object_manifests TO datariver_app;\n        GRANT SELECT, INSERT ON integration.upload_preparation_jobs TO datariver_app;\n        GRANT UPDATE (state, lease_token, lease_until, attempts, rows_processed,\n            total_rows, last_error_code, version, updated_at)\n            ON integration.upload_preparation_jobs TO datariver_app;\n        GRANT SELECT ON integration.upload_preparation_receipts,\n            integration.upload_registration_candidates TO datariver_app;\n        GRANT INSERT ON integration.upload_preparation_receipts,\n            integration.upload_registration_candidates TO datariver_app;\n        GRANT SELECT, INSERT ON integration.idempotency_keys,\n            integration.outbox_events TO datariver_app;\n        GRANT SELECT ON knowledge.graphs, knowledge.ontology_versions,\n            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,\n            knowledge.changesets, knowledge.change_operations,\n            knowledge.validation_results, knowledge.projection_deployments,\n            knowledge.source_snapshots, knowledge.source_pages,\n            knowledge.source_page_embeddings, knowledge.extraction_runs,\n            knowledge.graphrag_audits TO datariver_app;\n        GRANT INSERT ON knowledge.graphs, knowledge.ontology_versions,\n            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,\n            knowledge.changesets, knowledge.change_operations,\n            knowledge.validation_results, knowledge.projection_deployments,\n            knowledge.source_snapshots, knowledge.source_pages,\n            knowledge.source_page_embeddings, knowledge.extraction_runs,\n            knowledge.graphrag_audits TO datariver_app;\n        GRANT UPDATE ON knowledge.graphs, knowledge.changesets,\n            knowledge.projection_deployments, knowledge.source_snapshots TO datariver_app;\n        GRANT DELETE ON knowledge.validation_results TO datariver_app;\n        GRANT SELECT, INSERT ON assistant.chat_sessions, assistant.chat_messages,\n            assistant.assistant_runs, assistant.evidence_citations TO datariver_app;\n        GRANT UPDATE (version, updated_at) ON assistant.chat_sessions TO datariver_app;\n        GRANT SELECT, INSERT ON retention.policy_versions,\n            retention.policy_class_rules TO datariver_app;\n        GRANT UPDATE (state, checker_id, decision_reason,\n            decision_policy_decision_id, decided_at, superseded_by, supersede_reason,\n            supersede_policy_decision_id, superseded_at, version, updated_at)\n            ON retention.policy_versions TO datariver_app;\n        GRANT SELECT, INSERT ON retention.legal_holds TO datariver_app;\n        GRANT UPDATE (state, release_requested_by, release_request_reason,\n            release_request_policy_decision_id, release_checker_id,\n            release_decision_reason, release_decision_policy_decision_id,\n            released_at, version, updated_at)\n            ON retention.legal_holds TO datariver_app;\n        GRANT SELECT, INSERT ON retention.legal_hold_events TO datariver_app;\n        GRANT SELECT, INSERT ON retention.erasure_requests TO datariver_app;\n        GRANT UPDATE (state, checker_id, decision_reason,\n            decision_policy_decision_id, decided_at, version, updated_at)\n            ON retention.erasure_requests TO datariver_app;\n        GRANT SELECT, INSERT ON retention.erasure_request_events TO datariver_app;\n        GRANT SELECT ON retention.archive_capability_attestations,\n            retention.immutable_archive_receipts TO datariver_app;\n        GRANT SELECT ON retention.execution_jobs TO datariver_app;\n        GRANT SELECT ON retention.execution_attempts,\n            retention.execution_events TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON sharing.api_products,\n            sharing.api_product_versions, sharing.consumer_grants TO datariver_app;\n        GRANT SELECT, INSERT ON sharing.api_invocations TO datariver_app;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_relay') THEN\n        GRANT USAGE ON SCHEMA platform, integration TO datariver_relay;\n        GRANT SELECT ON platform.external_service_profiles,\n            platform.external_service_profile_versions TO datariver_relay;\n        GRANT SELECT, UPDATE ON integration.outbox_events TO datariver_relay;\n        GRANT SELECT ON integration.inbox_messages TO datariver_relay;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_upload') THEN\n        GRANT USAGE ON SCHEMA platform, integration TO datariver_upload;\n        GRANT SELECT ON platform.external_service_profiles,\n            platform.external_service_profile_versions TO datariver_upload;\n        GRANT SELECT, UPDATE ON integration.object_manifests TO datariver_upload;\n        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_upload;\n        GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages TO datariver_upload;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') THEN\n        GRANT USAGE ON SCHEMA platform, iam, authz, governance, integration\n            TO datariver_governance;\n        GRANT SELECT ON platform.external_service_profiles,\n            platform.external_service_profile_versions TO datariver_governance;\n        GRANT SELECT, INSERT ON authz.policy_decisions TO datariver_governance;\n        GRANT SELECT ON governance.change_requests TO datariver_governance;\n        GRANT UPDATE (state, version, updated_at)\n            ON governance.change_requests TO datariver_governance;\n        GRANT SELECT ON governance.change_request_items, governance.approvals,\n            governance.state_transitions, governance.change_request_rounds,\n            governance.change_test_runs TO datariver_governance;\n        GRANT INSERT ON governance.state_transitions TO datariver_governance;\n        GRANT SELECT, INSERT ON integration.jobs, integration.job_attempts\n            TO datariver_governance;\n        GRANT UPDATE (state, progress, result_ref, lease_until, attempts,\n            attempt_cycle, cycle_attempts, lease_token_hash, lease_owner_id,\n            last_error_code, version, updated_at)\n            ON integration.jobs TO datariver_governance;\n        GRANT UPDATE (state, error_class, external_response_hash, finished_at)\n            ON integration.job_attempts TO datariver_governance;\n        GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages\n            TO datariver_governance;\n        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_governance;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_export') THEN\n        GRANT USAGE ON SCHEMA platform, iam, authz, catalog, integration TO datariver_export;\n        GRANT SELECT ON platform.workspaces, iam.subjects,\n            iam.workspace_memberships TO datariver_export;\n        GRANT SELECT ON platform.external_service_profiles,\n            platform.external_service_profile_versions TO datariver_export;\n        GRANT SELECT ON authz.classification_access_policy_versions,\n            authz.classification_access_policy_rules, authz.classification_access_generations,\n            authz.restricted_search_grants TO datariver_export;\n        GRANT INSERT ON authz.policy_decisions TO datariver_export;\n        GRANT SELECT ON catalog.assets_projection, catalog.projection_watermarks,\n            catalog.export_requests TO datariver_export;\n        GRANT UPDATE (object_bucket, object_key, row_count, size_bytes, content_sha256,\n            provider_checksum, completed_at, version, updated_at)\n            ON catalog.export_requests TO datariver_export;\n        GRANT SELECT ON integration.inference_provider_profile_versions,\n            integration.jobs, integration.job_attempts TO datariver_export;\n        GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages TO datariver_export;\n        GRANT UPDATE (state, progress, result_ref, lease_until, attempts, last_error_code,\n            version, updated_at) ON integration.jobs TO datariver_export;\n        GRANT INSERT, UPDATE (state, error_class, external_response_hash, finished_at)\n            ON integration.job_attempts TO datariver_export;\n    END IF;\n\n    IF EXISTS (\n        SELECT 1 FROM pg_roles WHERE rolname = 'datariver_retention_scheduler'\n    ) THEN\n        GRANT USAGE ON SCHEMA platform, iam, authz, assistant, retention\n            TO datariver_retention_scheduler;\n        GRANT SELECT ON platform.workspaces, iam.subjects,\n            iam.workspace_memberships, iam.access_roles,\n            iam.access_role_assignments, authz.policy_decisions,\n            retention.policy_versions, retention.policy_class_rules,\n            retention.legal_holds, retention.erasure_requests,\n            retention.erasure_request_events,\n            assistant.chat_sessions TO datariver_retention_scheduler;\n        GRANT SELECT, INSERT ON retention.execution_jobs,\n            retention.execution_events TO datariver_retention_scheduler;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_archive') THEN\n        GRANT USAGE ON SCHEMA platform, iam, authz, assistant, retention\n            TO datariver_archive;\n        GRANT SELECT ON platform.workspaces, iam.subjects,\n            iam.workspace_memberships, iam.access_roles,\n            iam.access_role_assignments, authz.policy_decisions,\n            retention.policy_versions, retention.policy_class_rules,\n            retention.legal_holds, retention.erasure_requests,\n            retention.erasure_request_events,\n            assistant.chat_sessions, retention.execution_jobs,\n            retention.execution_attempts,\n            retention.archive_capability_attestations,\n            retention.immutable_archive_receipts TO datariver_archive;\n        GRANT INSERT ON retention.archive_capability_attestations,\n            retention.immutable_archive_receipts,\n            retention.execution_attempts TO datariver_archive;\n        GRANT SELECT, INSERT ON retention.execution_events TO datariver_archive;\n        GRANT UPDATE (state, next_attempt_at, attempt_count, lease_epoch,\n            lease_token_hash, lease_owner_fingerprint, lease_until,\n            archive_receipt_id, archive_manifest_hash, last_failure_code,\n            version, updated_at) ON retention.execution_jobs TO datariver_archive;\n        GRANT UPDATE (state, stage, evidence_hash, external_response_hash,\n            failure_code, finished_at) ON retention.execution_attempts TO datariver_archive;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_bootstrap') THEN\n        GRANT USAGE ON SCHEMA platform, iam TO datariver_bootstrap;\n        GRANT SELECT, INSERT, UPDATE ON platform.workspaces, iam.subjects,\n            iam.workspace_memberships TO datariver_bootstrap;\n    END IF;\nEND\n$datariver$")
        op.execute("DO $datariver$\nDECLARE\n    role_is_safe boolean;\nBEGIN\n    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN\n        RAISE EXCEPTION 'datariver_app must exist before durable Knowledge migration';\n    END IF;\n    SELECT\n        rolcanlogin\n        AND NOT rolsuper\n        AND NOT rolcreatedb\n        AND NOT rolcreaterole\n        AND NOT rolreplication\n        AND NOT rolbypassrls\n    INTO role_is_safe\n    FROM pg_roles WHERE rolname = 'datariver_app';\n    IF NOT role_is_safe THEN\n        RAISE EXCEPTION 'datariver_app must be an unprivileged LOGIN principal';\n    END IF;\n    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_knowledge') THEN\n        RAISE EXCEPTION\n            'datariver_knowledge must be reconciled before durable Knowledge migration';\n    END IF;\n    SELECT\n        rolcanlogin\n        AND NOT rolsuper\n        AND NOT rolcreatedb\n        AND NOT rolcreaterole\n        AND NOT rolreplication\n        AND NOT rolbypassrls\n    INTO role_is_safe\n    FROM pg_roles WHERE rolname = 'datariver_knowledge';\n    IF NOT role_is_safe THEN\n        RAISE EXCEPTION\n            'datariver_knowledge must be an unprivileged LOGIN principal';\n    END IF;\n    IF EXISTS (\n        SELECT 1\n        FROM pg_roles AS candidate\n        WHERE candidate.rolname <> 'datariver_knowledge'\n          AND pg_has_role('datariver_knowledge', candidate.oid, 'MEMBER')\n    ) THEN\n        RAISE EXCEPTION\n            'datariver_knowledge must not inherit or SET ROLE to another principal';\n    END IF;\n    IF EXISTS (\n        SELECT 1\n        FROM pg_roles AS candidate\n        WHERE candidate.rolname <> 'datariver_knowledge'\n          AND NOT candidate.rolsuper\n          AND pg_has_role(candidate.oid, 'datariver_knowledge', 'MEMBER')\n    ) THEN\n        RAISE EXCEPTION\n            'datariver_knowledge must not be assumable by another non-superuser principal';\n    END IF;\nEND\n$datariver$;")
        op.execute("CREATE OR REPLACE FUNCTION knowledge.current_source_claim_scope()\nRETURNS TABLE (\n    job_id uuid,\n    workspace_id uuid,\n    graph_id uuid,\n    source_snapshot_id uuid,\n    upload_id uuid,\n    requested_by uuid,\n    ontology_version_id uuid,\n    base_release_id uuid,\n    embedding_binding jsonb,\n    extraction_binding jsonb\n)\nLANGUAGE plpgsql\nSTABLE\nSECURITY DEFINER\nSET search_path = pg_catalog, knowledge\nAS $$\nDECLARE\n    selected_job_id uuid :=\n        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;\n    raw_token text :=\n        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');\n    raw_hash text;\nBEGIN\n    IF session_user <> 'datariver_knowledge'\n       OR selected_job_id IS NULL\n       OR raw_token IS NULL THEN\n        RETURN;\n    END IF;\n    raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');\n    RETURN QUERY\n    SELECT\n        job.id,\n        job.workspace_id,\n        job.graph_id,\n        job.source_snapshot_id,\n        source.upload_id,\n        job.requested_by,\n        job.ontology_version_id,\n        job.base_release_id,\n        job.embedding_binding,\n        job.extraction_binding\n    FROM knowledge.source_analysis_jobs AS job\n    JOIN knowledge.source_analysis_attempts AS attempt\n      ON attempt.workspace_id = job.workspace_id\n     AND attempt.job_id = job.id\n     AND attempt.lease_epoch = job.lease_epoch\n    JOIN knowledge.source_snapshots AS source\n      ON source.workspace_id = job.workspace_id\n     AND source.id = job.source_snapshot_id\n    WHERE job.id = selected_job_id\n      AND job.state IN ('RUNNING', 'CANCEL_REQUESTED')\n      AND job.lease_expires_at > clock_timestamp()\n      AND job.lease_token_hash = raw_hash\n      AND attempt.state = 'RUNNING'\n      AND attempt.lease_token_hash = raw_hash;\nEND\n$$;")
        op.execute('REVOKE ALL ON FUNCTION knowledge.current_source_claim_scope() FROM PUBLIC;')
        op.execute('GRANT EXECUTE ON FUNCTION knowledge.current_source_claim_scope()\nTO datariver_knowledge;')
        op.execute('ALTER TABLE iam.subjects ENABLE ROW LEVEL SECURITY;')
        op.execute('ALTER TABLE iam.subjects FORCE ROW LEVEL SECURITY;')
        op.execute('CREATE POLICY existing_subject_privileges\nON iam.subjects\nUSING (true)\nWITH CHECK (true);')
        op.execute('CREATE POLICY knowledge_worker_current_subject\nON iam.subjects\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    EXISTS (\n        SELECT 1\n        FROM knowledge.current_source_claim_scope() AS claim\n        WHERE claim.requested_by = subjects.id\n    )\n);')
        op.execute('CREATE POLICY knowledge_worker_current_membership\nON iam.workspace_memberships\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    EXISTS (\n        SELECT 1\n        FROM knowledge.current_source_claim_scope() AS claim\n        WHERE claim.workspace_id = workspace_memberships.workspace_id\n          AND claim.requested_by = workspace_memberships.subject_id\n    )\n);')
        op.execute("CREATE POLICY knowledge_worker_inference_profiles\nON platform.external_service_profiles\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    active\n    AND EXISTS (\n        SELECT 1\n        FROM knowledge.current_source_claim_scope() AS claim\n        WHERE claim.workspace_id = external_service_profiles.workspace_id\n          AND (\n              (\n                  external_service_profiles.service_key = 'LLM_CHAT_MODEL'\n                  AND claim.extraction_binding ->> 'configuration_source'\n                      = 'SYSTEM_CONFIGURATION'\n                  AND external_service_profiles.activated_version =\n                      (claim.extraction_binding ->> 'configuration_version')::integer\n              )\n              OR (\n                  external_service_profiles.service_key = 'LLM_EMBEDDING'\n                  AND claim.embedding_binding ->> 'configuration_source'\n                      = 'SYSTEM_CONFIGURATION'\n                  AND external_service_profiles.activated_version =\n                      (claim.embedding_binding ->> 'configuration_version')::integer\n              )\n          )\n    )\n);")
        op.execute("CREATE POLICY knowledge_worker_inference_profile_versions\nON platform.external_service_profile_versions\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    test_status = 'AVAILABLE'\n    AND EXISTS (\n        SELECT 1\n        FROM platform.external_service_profiles AS profile\n        JOIN knowledge.current_source_claim_scope() AS claim\n          ON claim.workspace_id = profile.workspace_id\n        WHERE profile.workspace_id = external_service_profile_versions.workspace_id\n          AND profile.id = external_service_profile_versions.profile_id\n          AND profile.active\n          AND profile.activated_version =\n              external_service_profile_versions.configuration_version\n          AND (\n              (\n                  profile.service_key = 'LLM_CHAT_MODEL'\n                  AND claim.extraction_binding ->> 'configuration_source'\n                      = 'SYSTEM_CONFIGURATION'\n                  AND external_service_profile_versions.configuration_version =\n                      (claim.extraction_binding ->> 'configuration_version')::integer\n                  AND external_service_profile_versions.configuration_hash =\n                      claim.extraction_binding ->> 'configuration_hash'\n              )\n              OR (\n                  profile.service_key = 'LLM_EMBEDDING'\n                  AND claim.embedding_binding ->> 'configuration_source'\n                      = 'SYSTEM_CONFIGURATION'\n                  AND external_service_profile_versions.configuration_version =\n                      (claim.embedding_binding ->> 'configuration_version')::integer\n                  AND external_service_profile_versions.configuration_hash =\n                      claim.embedding_binding ->> 'configuration_hash'\n              )\n          )\n    )\n);")
        op.execute('CREATE POLICY knowledge_worker_current_manifest\nON integration.object_manifests\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    EXISTS (\n        SELECT 1\n        FROM knowledge.current_source_claim_scope() AS claim\n        WHERE claim.workspace_id = object_manifests.workspace_id\n          AND claim.upload_id = object_manifests.id\n    )\n);')
        op.execute("CREATE POLICY knowledge_worker_inbox_consumer\nON integration.inbox_messages\nAS RESTRICTIVE TO datariver_knowledge\nUSING (consumer = 'knowledge-source-analysis-v1')\nWITH CHECK (consumer = 'knowledge-source-analysis-v1');")
        op.execute('CREATE POLICY knowledge_worker_current_graph\nON knowledge.graphs\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    EXISTS (\n        SELECT 1\n        FROM knowledge.current_source_claim_scope() AS claim\n        WHERE claim.workspace_id = graphs.workspace_id\n          AND claim.graph_id = graphs.id\n    )\n);')
        op.execute('CREATE POLICY knowledge_worker_current_ontology\nON knowledge.ontology_versions\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    EXISTS (\n        SELECT 1\n        FROM knowledge.current_source_claim_scope() AS claim\n        WHERE claim.workspace_id = ontology_versions.workspace_id\n          AND claim.graph_id = ontology_versions.graph_id\n          AND claim.ontology_version_id = ontology_versions.id\n    )\n);')
        op.execute('CREATE POLICY knowledge_worker_current_release\nON knowledge.releases\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    EXISTS (\n        SELECT 1\n        FROM knowledge.current_source_claim_scope() AS claim\n        WHERE claim.workspace_id = releases.workspace_id\n          AND claim.graph_id = releases.graph_id\n          AND claim.base_release_id = releases.id\n    )\n);')
        op.execute('CREATE POLICY knowledge_worker_current_source\nON knowledge.source_snapshots\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    EXISTS (\n        SELECT 1\n        FROM knowledge.current_source_claim_scope() AS claim\n        WHERE claim.workspace_id = source_snapshots.workspace_id\n          AND claim.source_snapshot_id = source_snapshots.id\n    )\n);')
        op.execute('CREATE POLICY knowledge_worker_current_changeset\nON knowledge.changesets\nAS RESTRICTIVE FOR SELECT TO datariver_knowledge\nUSING (\n    EXISTS (\n        SELECT 1\n        FROM knowledge.current_source_claim_scope() AS claim\n        WHERE claim.workspace_id = changesets.workspace_id\n          AND claim.graph_id = changesets.graph_id\n          AND (\n              changesets.source_analysis_job_id = claim.job_id\n              OR changesets.published_release_id = claim.base_release_id\n          )\n    )\n);')
        op.execute('CREATE UNIQUE INDEX IF NOT EXISTS\n    ux_source_analysis_events_transition_evidence\nON knowledge.source_analysis_events (\n    workspace_id, job_id, event_type, occurred_at\n);')
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS\n    ux_outbox_source_analysis_transition\nON integration.outbox_events (\n    workspace_id, aggregate_id, event_type, (payload ->> 'version')\n)\nWHERE aggregate_type = 'knowledge_source_analysis_job';")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS\n    ux_policy_decisions_source_analysis_finalization\nON authz.policy_decisions (workspace_id, request_id, action)\nWHERE evaluation_context ->> 'kind'\n    = 'knowledge_source_job_finalization';")
        op.execute("CREATE OR REPLACE FUNCTION knowledge.list_knowledge_worker_workspaces()\nRETURNS SETOF uuid\nLANGUAGE plpgsql\nVOLATILE\nSECURITY DEFINER\nSET search_path = pg_catalog, knowledge\nAS $$\nBEGIN\n    IF session_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'Knowledge workspace discovery is worker-only'\n            USING ERRCODE = '42501';\n    END IF;\n    RETURN QUERY\n    SELECT DISTINCT job.workspace_id\n    FROM knowledge.source_analysis_jobs AS job\n    WHERE (\n        job.state IN ('QUEUED', 'RETRY_WAIT')\n        AND job.next_attempt_at <= clock_timestamp()\n    ) OR (\n        job.state IN ('RUNNING', 'CANCEL_REQUESTED')\n        AND job.lease_expires_at <= clock_timestamp()\n    )\n    ORDER BY 1\n    LIMIT 10000;\nEND\n$$;")
        op.execute('REVOKE ALL ON FUNCTION knowledge.list_knowledge_worker_workspaces()\nFROM PUBLIC;')
        op.execute('GRANT EXECUTE ON FUNCTION knowledge.list_knowledge_worker_workspaces()\nTO datariver_knowledge;')
        op.execute("CREATE OR REPLACE FUNCTION knowledge.lock_source_analysis_finalization()\nRETURNS void\nLANGUAGE plpgsql\nVOLATILE\nSECURITY DEFINER\nSET search_path = pg_catalog, platform, iam, integration, knowledge\nAS $$\nDECLARE\n    selected_job_id uuid :=\n        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;\n    raw_token text :=\n        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');\n    raw_hash text;\n    selected_job knowledge.source_analysis_jobs%ROWTYPE;\n    selected_source knowledge.source_snapshots%ROWTYPE;\nBEGIN\n    IF session_user <> 'datariver_knowledge'\n       OR selected_job_id IS NULL\n       OR raw_token IS NULL THEN\n        RAISE EXCEPTION 'Knowledge finalization locking is worker-claim only'\n            USING ERRCODE = '42501';\n    END IF;\n    raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');\n    SELECT * INTO selected_job\n    FROM knowledge.source_analysis_jobs\n    WHERE id = selected_job_id\n    FOR UPDATE;\n    IF NOT FOUND\n       OR selected_job.state <> 'RUNNING'\n       OR selected_job.lease_expires_at <= clock_timestamp()\n       OR raw_hash IS DISTINCT FROM selected_job.lease_token_hash THEN\n        RAISE EXCEPTION 'Knowledge finalization claim is expired or superseded'\n            USING ERRCODE = '42501';\n    END IF;\n    SELECT * INTO selected_source\n    FROM knowledge.source_snapshots\n    WHERE workspace_id = selected_job.workspace_id\n      AND id = selected_job.source_snapshot_id\n    FOR UPDATE;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'Knowledge finalization source is unavailable';\n    END IF;\n    PERFORM 1\n    FROM integration.object_manifests\n    WHERE workspace_id = selected_job.workspace_id\n      AND id = selected_source.upload_id\n    FOR UPDATE;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'Knowledge finalization manifest is unavailable';\n    END IF;\n    PERFORM 1\n    FROM knowledge.graphs\n    WHERE workspace_id = selected_job.workspace_id\n      AND id = selected_job.graph_id\n    FOR UPDATE;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'Knowledge finalization graph is unavailable';\n    END IF;\n    PERFORM 1\n    FROM knowledge.ontology_versions\n    WHERE workspace_id = selected_job.workspace_id\n      AND graph_id = selected_job.graph_id\n    FOR UPDATE;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'Knowledge finalization ontology is unavailable';\n    END IF;\n    PERFORM 1\n    FROM iam.subjects\n    WHERE id = selected_job.requested_by\n    FOR UPDATE;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'Knowledge finalization requester is unavailable';\n    END IF;\n    PERFORM 1\n    FROM iam.workspace_memberships\n    WHERE workspace_id = selected_job.workspace_id\n      AND subject_id = selected_job.requested_by\n    FOR UPDATE;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'Knowledge finalization membership is unavailable';\n    END IF;\n    PERFORM 1\n    FROM platform.external_service_profiles\n    WHERE workspace_id = selected_job.workspace_id\n      AND service_key IN ('LLM_CHAT_MODEL', 'LLM_EMBEDDING')\n    FOR UPDATE;\n    PERFORM 1\n    FROM platform.external_service_profile_versions AS version\n    WHERE version.workspace_id = selected_job.workspace_id\n      AND EXISTS (\n          SELECT 1\n          FROM platform.external_service_profiles AS profile\n          WHERE profile.workspace_id = version.workspace_id\n            AND profile.id = version.profile_id\n            AND profile.service_key IN ('LLM_CHAT_MODEL', 'LLM_EMBEDDING')\n      )\n    FOR UPDATE;\nEND\n$$;")
        op.execute('REVOKE ALL ON FUNCTION knowledge.lock_source_analysis_finalization()\nFROM PUBLIC;')
        op.execute('GRANT EXECUTE ON FUNCTION knowledge.lock_source_analysis_finalization()\nTO datariver_knowledge;')
        op.execute('GRANT EXECUTE ON FUNCTION knowledge.current_source_claim_scope()\nTO datariver_knowledge;')
        op.execute("CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_job_fence()\nRETURNS trigger\nLANGUAGE plpgsql\nAS $$\nDECLARE\n    table_owner text;\n    raw_token text :=\n        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');\n    raw_hash text;\n    actor_id uuid :=\n        NULLIF(current_setting('app.subject_id', true), '')::uuid;\n    selected_job_id uuid :=\n        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;\nBEGIN\n    SELECT pg_get_userbyid(relowner) INTO table_owner\n    FROM pg_class WHERE oid = TG_RELID;\n    IF current_user = table_owner THEN\n        IF TG_OP = 'DELETE' THEN\n            RETURN OLD;\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF current_user = 'datariver_knowledge'\n       AND session_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';\n    END IF;\n    IF TG_OP = 'DELETE' THEN\n        RAISE EXCEPTION 'durable Knowledge jobs are not directly deletable';\n    END IF;\n    IF TG_OP = 'INSERT' THEN\n        IF current_user <> 'datariver_app'\n           OR NEW.requested_by IS DISTINCT FROM actor_id\n           OR NEW.state <> 'QUEUED'\n           OR NEW.stage <> 'QUEUED'\n           OR NEW.attempt_count <> 0\n           OR NEW.lease_epoch <> 0\n           OR NEW.version <> 1\n           OR NEW.completed_at IS NOT NULL THEN\n            RAISE EXCEPTION 'invalid durable Knowledge job submission';\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF ROW(\n        OLD.workspace_id, OLD.id, OLD.graph_id, OLD.source_snapshot_id,\n        OLD.requested_by, OLD.title, OLD.request_hash,\n        OLD.requester_authorization_hash, OLD.source_storage_version,\n        OLD.source_content_sha256, OLD.source_classification,\n        OLD.graph_version, OLD.base_kind, OLD.base_release_id,\n        OLD.base_release_hash, OLD.ontology_version_id,\n        OLD.ontology_checksum, OLD.parser_config_hash,\n        OLD.embedding_binding, OLD.embedding_binding_hash,\n        OLD.extraction_binding, OLD.extraction_binding_hash,\n        OLD.pin_hash, OLD.prepared_at, OLD.created_at,\n        OLD.maximum_attempts\n    ) IS DISTINCT FROM ROW(\n        NEW.workspace_id, NEW.id, NEW.graph_id, NEW.source_snapshot_id,\n        NEW.requested_by, NEW.title, NEW.request_hash,\n        NEW.requester_authorization_hash, NEW.source_storage_version,\n        NEW.source_content_sha256, NEW.source_classification,\n        NEW.graph_version, NEW.base_kind, NEW.base_release_id,\n        NEW.base_release_hash, NEW.ontology_version_id,\n        NEW.ontology_checksum, NEW.parser_config_hash,\n        NEW.embedding_binding, NEW.embedding_binding_hash,\n        NEW.extraction_binding, NEW.extraction_binding_hash,\n        NEW.pin_hash, NEW.prepared_at, NEW.created_at,\n        NEW.maximum_attempts\n    ) THEN\n        RAISE EXCEPTION 'durable Knowledge job pins are immutable';\n    END IF;\n    IF NEW.version <> OLD.version + 1 OR NEW.updated_at < OLD.updated_at THEN\n        RAISE EXCEPTION 'invalid durable Knowledge job version transition';\n    END IF;\n    IF current_user = 'datariver_app' THEN\n        IF OLD.requested_by IS DISTINCT FROM actor_id\n           OR NEW.cancel_requested_by IS DISTINCT FROM actor_id\n           OR NEW.cancel_requested_at IS NULL\n           OR NEW.cancel_reason IS NULL\n           OR NOT (\n               (\n                   OLD.state IN ('QUEUED', 'RETRY_WAIT')\n                   AND NEW.state = 'CANCELLED'\n                   AND NEW.stage = 'COMPLETED'\n                   AND NEW.completed_at IS NOT NULL\n               )\n               OR (\n                   OLD.state = 'RUNNING'\n                   AND NEW.state = 'CANCEL_REQUESTED'\n                   AND NEW.completed_at IS NULL\n                   AND NEW.lease_token_hash = OLD.lease_token_hash\n                   AND NEW.lease_owner_fingerprint = OLD.lease_owner_fingerprint\n                   AND NEW.lease_expires_at = OLD.lease_expires_at\n               )\n           ) THEN\n            RAISE EXCEPTION 'invalid durable Knowledge cancellation';\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF current_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'only the API or Knowledge worker may update durable jobs';\n    END IF;\n    IF NOT (\n        OLD.state IN ('QUEUED', 'RETRY_WAIT') AND NEW.state = 'RUNNING'\n    ) AND (\n        NEW.attempt_count <> OLD.attempt_count\n        OR NEW.lease_epoch <> OLD.lease_epoch\n    ) THEN\n        RAISE EXCEPTION 'durable Knowledge counters may change only during claim';\n    END IF;\n    IF raw_token IS NOT NULL THEN\n        raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');\n    END IF;\n    IF OLD.state IN ('QUEUED', 'RETRY_WAIT') AND NEW.state = 'RUNNING' THEN\n        IF raw_hash IS DISTINCT FROM NEW.lease_token_hash\n           OR NEW.attempt_count <> OLD.attempt_count + 1\n           OR NEW.lease_epoch <> OLD.lease_epoch + 1\n           OR NEW.lease_started_at IS NULL\n           OR NEW.lease_expires_at <= clock_timestamp()\n           OR NEW.lease_expires_at > clock_timestamp() + interval '1 hour'\n           OR NEW.last_failure_code IS NOT NULL THEN\n            RAISE EXCEPTION 'invalid durable Knowledge claim';\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF OLD.state IN ('RUNNING', 'CANCEL_REQUESTED')\n       AND OLD.lease_expires_at > clock_timestamp()\n       AND raw_hash = OLD.lease_token_hash THEN\n        IF OLD.state = 'CANCEL_REQUESTED' AND NEW.state <> 'CANCELLED' THEN\n            RAISE EXCEPTION 'a cancellation request may only become cancelled';\n        END IF;\n        IF NEW.state NOT IN (\n            'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED'\n        ) THEN\n            RAISE EXCEPTION 'invalid live durable Knowledge transition';\n        END IF;\n        IF NEW.state = 'RUNNING' AND (\n            NEW.lease_token_hash IS DISTINCT FROM OLD.lease_token_hash\n            OR NEW.lease_owner_fingerprint IS DISTINCT FROM OLD.lease_owner_fingerprint\n            OR NEW.lease_epoch <> OLD.lease_epoch\n            OR NEW.attempt_count <> OLD.attempt_count\n            OR NEW.lease_expires_at <= clock_timestamp()\n            OR NEW.lease_expires_at > clock_timestamp() + interval '1 hour'\n        ) THEN\n            RAISE EXCEPTION 'invalid durable Knowledge renewal';\n        END IF;\n        IF NEW.state <> 'RUNNING' AND (\n            NEW.lease_token_hash IS NOT NULL\n            OR NEW.lease_owner_fingerprint IS NOT NULL\n            OR NEW.lease_started_at IS NOT NULL\n            OR NEW.lease_expires_at IS NOT NULL\n        ) THEN\n            RAISE EXCEPTION 'durable Knowledge terminal transition retained a lease';\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF OLD.state IN ('RUNNING', 'CANCEL_REQUESTED')\n       AND OLD.lease_expires_at <= clock_timestamp()\n       AND raw_token IS NULL\n       AND selected_job_id = OLD.id\n       AND (\n           (OLD.state = 'RUNNING' AND NEW.state IN ('RETRY_WAIT', 'FAILED'))\n           OR (OLD.state = 'CANCEL_REQUESTED' AND NEW.state = 'CANCELLED')\n       )\n       AND NEW.lease_token_hash IS NULL\n       AND NEW.lease_owner_fingerprint IS NULL\n       AND NEW.lease_started_at IS NULL\n       AND NEW.lease_expires_at IS NULL THEN\n        RETURN NEW;\n    END IF;\n    RAISE EXCEPTION 'durable Knowledge lease is missing, expired or superseded';\nEND\n$$;")
        op.execute('CREATE TRIGGER trg_source_analysis_job_fence\nBEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_analysis_jobs\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_job_fence();')
        op.execute("CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_attempt_fence()\nRETURNS trigger\nLANGUAGE plpgsql\nAS $$\nDECLARE\n    table_owner text;\n    parent knowledge.source_analysis_jobs%ROWTYPE;\n    raw_token text :=\n        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');\n    raw_hash text;\n    selected_job_id uuid :=\n        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;\nBEGIN\n    SELECT pg_get_userbyid(relowner) INTO table_owner\n    FROM pg_class WHERE oid = TG_RELID;\n    IF current_user = table_owner THEN\n        IF TG_OP = 'DELETE' THEN\n            RETURN OLD;\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF current_user = 'datariver_knowledge'\n       AND session_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';\n    END IF;\n    IF current_user <> 'datariver_knowledge' OR TG_OP = 'DELETE' THEN\n        RAISE EXCEPTION 'durable Knowledge attempts are worker-owned and append-preserving';\n    END IF;\n    SELECT * INTO parent FROM knowledge.source_analysis_jobs\n    WHERE workspace_id = NEW.workspace_id AND id = NEW.job_id;\n    raw_hash := CASE WHEN raw_token IS NULL THEN NULL\n        ELSE encode(sha256(convert_to(raw_token, 'UTF8')), 'hex') END;\n    IF TG_OP = 'INSERT' THEN\n        IF parent.state <> 'RUNNING'\n           OR parent.lease_expires_at <= clock_timestamp()\n           OR raw_hash IS DISTINCT FROM parent.lease_token_hash\n           OR NEW.lease_token_hash IS DISTINCT FROM parent.lease_token_hash\n           OR NEW.attempt_no <> parent.attempt_count\n           OR NEW.lease_epoch <> parent.lease_epoch\n           OR NEW.state <> 'RUNNING' THEN\n            RAISE EXCEPTION 'invalid durable Knowledge attempt claim';\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF ROW(\n        OLD.workspace_id, OLD.id, OLD.job_id, OLD.attempt_no,\n        OLD.lease_epoch, OLD.lease_token_hash, OLD.worker_fingerprint,\n        OLD.input_hash, OLD.started_at\n    ) IS DISTINCT FROM ROW(\n        NEW.workspace_id, NEW.id, NEW.job_id, NEW.attempt_no,\n        NEW.lease_epoch, NEW.lease_token_hash, NEW.worker_fingerprint,\n        NEW.input_hash, NEW.started_at\n    ) OR OLD.state <> 'RUNNING' THEN\n        RAISE EXCEPTION 'durable Knowledge attempt identity is immutable';\n    END IF;\n    IF (\n        parent.lease_epoch = OLD.lease_epoch\n        AND parent.lease_token_hash = OLD.lease_token_hash\n        AND parent.lease_expires_at > clock_timestamp()\n        AND raw_hash = parent.lease_token_hash\n        AND NEW.state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')\n    ) OR (\n        parent.lease_epoch = OLD.lease_epoch\n        AND OLD.finished_at IS NULL\n        AND raw_token IS NULL\n        AND selected_job_id = parent.id\n        AND parent.lease_expires_at <= clock_timestamp()\n        AND NEW.state = 'SUPERSEDED'\n        AND NEW.failure_code = 'LEASE_EXPIRED'\n    ) THEN\n        RETURN NEW;\n    END IF;\n    RAISE EXCEPTION 'durable Knowledge attempt lease is superseded';\nEND\n$$;")
        op.execute('CREATE TRIGGER trg_source_analysis_attempt_fence\nBEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_analysis_attempts\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_attempt_fence();')
        op.execute("CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_attempt_terminal_pair()\nRETURNS trigger\nLANGUAGE plpgsql\nAS $$\nDECLARE\n    parent knowledge.source_analysis_jobs%ROWTYPE;\nBEGIN\n    IF current_user = 'datariver_knowledge'\n       AND session_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';\n    END IF;\n    SELECT * INTO parent\n    FROM knowledge.source_analysis_jobs\n    WHERE workspace_id = NEW.workspace_id AND id = NEW.job_id;\n    IF NOT FOUND OR parent.lease_epoch <> NEW.lease_epoch THEN\n        RAISE EXCEPTION 'durable Knowledge attempt has no matching job epoch';\n    END IF;\n    IF (\n        NEW.state = 'RUNNING'\n        AND parent.state IN ('RUNNING', 'CANCEL_REQUESTED')\n    ) OR (\n        NEW.state = 'SUCCEEDED' AND parent.state = 'SUCCEEDED'\n    ) OR (\n        NEW.state = 'FAILED' AND parent.state IN ('FAILED', 'RETRY_WAIT')\n    ) OR (\n        NEW.state = 'STALE' AND parent.state = 'STALE'\n    ) OR (\n        NEW.state = 'CANCELLED' AND parent.state = 'CANCELLED'\n    ) OR (\n        NEW.state = 'SUPERSEDED'\n        AND parent.state IN ('RETRY_WAIT', 'FAILED', 'CANCELLED')\n    ) THEN\n        RETURN NULL;\n    END IF;\n    RAISE EXCEPTION 'durable Knowledge attempt and job terminal states diverged';\nEND\n$$;")
        op.execute('CREATE CONSTRAINT TRIGGER trg_source_analysis_attempt_terminal_pair\nAFTER INSERT OR UPDATE ON knowledge.source_analysis_attempts\nDEFERRABLE INITIALLY DEFERRED\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_attempt_terminal_pair();')
        op.execute("CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_event_append_only()\nRETURNS trigger\nLANGUAGE plpgsql\nAS $$\nDECLARE\n    table_owner text;\n    selected_job_id uuid :=\n        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;\n    actor_id uuid :=\n        NULLIF(current_setting('app.subject_id', true), '')::uuid;\n    parent knowledge.source_analysis_jobs%ROWTYPE;\n    current_attempt knowledge.source_analysis_attempts%ROWTYPE;\n    raw_token text :=\n        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');\n    raw_hash text;\n    parent_changed_in_transaction boolean := false;\n    expected_sequence integer;\n    live_event boolean := false;\n    recovery_event boolean := false;\n    app_event boolean := false;\nBEGIN\n    SELECT pg_get_userbyid(relowner) INTO table_owner\n    FROM pg_class WHERE oid = TG_RELID;\n    IF current_user = table_owner THEN\n        IF TG_OP = 'DELETE' THEN\n            RETURN OLD;\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF current_user = 'datariver_knowledge'\n       AND session_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';\n    END IF;\n    IF TG_OP <> 'INSERT'\n       OR current_user NOT IN ('datariver_app', 'datariver_knowledge') THEN\n        RAISE EXCEPTION 'durable Knowledge events are append-only';\n    END IF;\n    SELECT * INTO parent\n    FROM knowledge.source_analysis_jobs\n    WHERE workspace_id = NEW.workspace_id AND id = NEW.job_id;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'durable Knowledge event has no visible parent job';\n    END IF;\n    IF NEW.attempt_id IS NOT NULL AND NOT EXISTS (\n        SELECT 1\n        FROM knowledge.source_analysis_attempts AS candidate_attempt\n        WHERE candidate_attempt.workspace_id = NEW.workspace_id\n          AND candidate_attempt.id = NEW.attempt_id\n          AND candidate_attempt.job_id = NEW.job_id\n    ) THEN\n        RAISE EXCEPTION 'durable Knowledge event attempt is outside its job';\n    END IF;\n    SELECT (job.xmin::text::bigint = txid_current())\n    INTO parent_changed_in_transaction\n    FROM knowledge.source_analysis_jobs AS job\n    WHERE job.workspace_id = NEW.workspace_id\n      AND job.id = NEW.job_id;\n    SELECT COALESCE(MAX(event.sequence), 0) + 1\n    INTO expected_sequence\n    FROM knowledge.source_analysis_events AS event\n    WHERE event.workspace_id = NEW.workspace_id\n      AND event.job_id = NEW.job_id;\n    IF current_user = 'datariver_app' THEN\n        app_event :=\n            parent.requested_by = actor_id\n            AND NEW.actor_ref = 'subject:' || actor_id\n            AND NEW.attempt_id IS NULL\n            AND NEW.sequence = expected_sequence\n            AND parent_changed_in_transaction\n            AND NEW.occurred_at = parent.updated_at\n            AND (\n                (\n                    NEW.event_type = 'QUEUED'\n                    AND parent.state = 'QUEUED'\n                    AND parent.stage = 'QUEUED'\n                    AND parent.version = 1\n                    AND NEW.sequence = 1\n                    AND NEW.reason_code IS NULL\n                    AND NEW.details = jsonb_build_object(\n                        'pin_hash', parent.pin_hash,\n                        'request_hash', parent.request_hash\n                    )\n                )\n                OR (\n                    NEW.event_type IN ('CANCEL_REQUESTED', 'CANCELLED')\n                    AND parent.state = NEW.event_type\n                    AND parent.cancel_requested_by = actor_id\n                    AND parent.cancel_requested_at = parent.updated_at\n                    AND parent.cancel_reason IS NOT NULL\n                    AND NEW.reason_code = 'USER_REQUEST'\n                    AND NEW.details = '{}'::jsonb\n                )\n            );\n        IF NOT app_event THEN\n            RAISE EXCEPTION 'durable Knowledge API event evidence is invalid';\n        END IF;\n        NEW.evidence_hash := encode(\n            sha256(\n                convert_to(\n                    jsonb_build_object(\n                        'job_id', NEW.job_id,\n                        'sequence', NEW.sequence,\n                        'attempt_id', NEW.attempt_id,\n                        'event_type', NEW.event_type,\n                        'actor_ref', NEW.actor_ref,\n                        'reason_code', NEW.reason_code,\n                        'details', NEW.details,\n                        'occurred_at', NEW.occurred_at\n                    )::text,\n                    'UTF8'\n                )\n            ),\n            'hex'\n        );\n        RETURN NEW;\n    END IF;\n    IF current_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'durable Knowledge events are append-only';\n    END IF;\n    IF selected_job_id IS DISTINCT FROM NEW.job_id\n       OR NEW.attempt_id IS NULL THEN\n        RAISE EXCEPTION 'durable Knowledge worker event is outside its claim';\n    END IF;\n    SELECT * INTO current_attempt\n    FROM knowledge.source_analysis_attempts\n    WHERE workspace_id = NEW.workspace_id\n      AND id = NEW.attempt_id\n      AND job_id = NEW.job_id\n      AND lease_epoch = parent.lease_epoch;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION 'durable Knowledge worker event has no current attempt';\n    END IF;\n    IF NEW.sequence IS DISTINCT FROM expected_sequence\n       OR NOT parent_changed_in_transaction\n       OR NEW.occurred_at IS DISTINCT FROM parent.updated_at THEN\n        RAISE EXCEPTION 'durable Knowledge worker event is not bound to this transition';\n    END IF;\n    raw_hash := CASE\n        WHEN raw_token IS NULL THEN NULL\n        ELSE encode(sha256(convert_to(raw_token, 'UTF8')), 'hex')\n    END;\n    live_event :=\n        raw_hash = current_attempt.lease_token_hash\n        AND NEW.actor_ref = 'worker:' || current_attempt.worker_fingerprint\n        AND (\n            (\n                NEW.event_type = 'CLAIMED'\n                AND parent.state = 'RUNNING'\n                AND current_attempt.state = 'RUNNING'\n                AND NEW.reason_code IS NULL\n                AND NEW.details = jsonb_build_object(\n                    'attempt_no', current_attempt.attempt_no,\n                    'lease_epoch', current_attempt.lease_epoch\n                )\n            )\n            OR (\n                NEW.event_type = 'LEASE_RENEWED'\n                AND parent.state = 'RUNNING'\n                AND current_attempt.state = 'RUNNING'\n                AND NEW.reason_code IS NULL\n                AND NEW.details = jsonb_build_object(\n                    'stage', parent.stage,\n                    'progress', parent.progress\n                )\n            )\n            OR (\n                NEW.event_type = 'CANCELLED'\n                AND parent.state = 'CANCELLED'\n                AND current_attempt.state = 'CANCELLED'\n                AND NEW.reason_code = 'USER_REQUEST'\n                AND NEW.details = '{}'::jsonb\n            )\n            OR (\n                NEW.event_type IN ('RETRY_WAIT', 'FAILED')\n                AND parent.state = NEW.event_type\n                AND current_attempt.state = 'FAILED'\n                AND NEW.reason_code = parent.last_failure_code\n                AND NEW.reason_code = current_attempt.failure_code\n                AND NEW.details = jsonb_build_object(\n                    'retryable', current_attempt.retryable\n                )\n            )\n            OR (\n                NEW.event_type = 'STALE'\n                AND parent.state = 'STALE'\n                AND current_attempt.state = 'STALE'\n                AND NEW.reason_code = parent.last_failure_code\n                AND NEW.reason_code = current_attempt.failure_code\n                AND NEW.details = '{}'::jsonb\n            )\n            OR (\n                NEW.event_type = 'SUCCEEDED'\n                AND parent.state = 'SUCCEEDED'\n                AND current_attempt.state = 'SUCCEEDED'\n                AND NEW.reason_code IS NULL\n                AND NEW.details = jsonb_build_object(\n                    'changeset_id', parent.result_changeset_id,\n                    'result_evidence_hash', parent.result_evidence_hash\n                )\n            )\n        );\n    recovery_event :=\n        raw_token IS NULL\n        AND current_attempt.state = 'SUPERSEDED'\n        AND current_attempt.failure_code = 'LEASE_EXPIRED'\n        AND current_attempt.finished_at IS NOT NULL\n        AND current_attempt.finished_at = parent.updated_at\n        AND NEW.actor_ref = 'system:lease-recovery'\n        AND NEW.details = jsonb_build_object(\n            'expired_lease_epoch', current_attempt.lease_epoch\n        )\n        AND (\n            (\n                NEW.event_type = 'RETRY_WAIT'\n                AND parent.state = 'RETRY_WAIT'\n                AND NEW.reason_code = 'LEASE_EXPIRED'\n            )\n            OR (\n                NEW.event_type = 'FAILED'\n                AND parent.state = 'FAILED'\n                AND NEW.reason_code = 'WORKER_LEASE_EXHAUSTED'\n            )\n            OR (\n                NEW.event_type = 'CANCELLED'\n                AND parent.state = 'CANCELLED'\n                AND NEW.reason_code = 'CANCELLED_AFTER_LEASE_EXPIRY'\n            )\n        );\n    IF NOT live_event AND NOT recovery_event THEN\n        RAISE EXCEPTION 'durable Knowledge worker event evidence is invalid';\n    END IF;\n    NEW.evidence_hash := encode(\n        sha256(\n            convert_to(\n                jsonb_build_object(\n                    'job_id', NEW.job_id,\n                    'sequence', NEW.sequence,\n                    'attempt_id', NEW.attempt_id,\n                    'event_type', NEW.event_type,\n                    'actor_ref', NEW.actor_ref,\n                    'reason_code', NEW.reason_code,\n                    'details', NEW.details,\n                    'occurred_at', NEW.occurred_at\n                )::text,\n                'UTF8'\n            )\n        ),\n        'hex'\n    );\n    RETURN NEW;\nEND\n$$;")
        op.execute('CREATE TRIGGER trg_source_analysis_event_append_only\nBEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_analysis_events\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_event_append_only();')
        op.execute("CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_write_scope()\nRETURNS trigger\nLANGUAGE plpgsql\nAS $$\nDECLARE\n    document jsonb := to_jsonb(NEW);\n    selected_job_id uuid :=\n        NULLIF(current_setting('app.knowledge_source_job_id', true), '')::uuid;\n    raw_token text :=\n        NULLIF(current_setting('app.knowledge_source_lease_token', true), '');\n    raw_hash text;\n    parent knowledge.source_analysis_jobs%ROWTYPE;\n    selected_changeset knowledge.changesets%ROWTYPE;\n    selected_source_id uuid;\nBEGIN\n    IF current_user = 'datariver_knowledge'\n       AND session_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';\n    END IF;\n    IF TG_OP = 'DELETE' THEN\n        IF current_user = 'datariver_knowledge' THEN\n            RAISE EXCEPTION 'Knowledge canonical evidence is not worker-deletable';\n        END IF;\n        RETURN OLD;\n    END IF;\n    IF current_user <> 'datariver_knowledge' THEN\n        IF TG_TABLE_NAME = 'changesets' AND (\n            (TG_OP = 'INSERT' AND document ->> 'source_analysis_job_id' IS NOT NULL)\n            OR (\n                TG_OP = 'UPDATE'\n                AND to_jsonb(OLD) ->> 'source_analysis_job_id'\n                    IS DISTINCT FROM document ->> 'source_analysis_job_id'\n            )\n        ) THEN\n            RAISE EXCEPTION 'only the Knowledge worker may bind a source-analysis job';\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF selected_job_id IS NULL OR raw_token IS NULL THEN\n        RAISE EXCEPTION 'Knowledge canonical writes require a current job claim';\n    END IF;\n    raw_hash := encode(sha256(convert_to(raw_token, 'UTF8')), 'hex');\n    SELECT * INTO parent FROM knowledge.source_analysis_jobs\n    WHERE id = selected_job_id\n      AND workspace_id = (document ->> 'workspace_id')::uuid;\n    IF NOT FOUND OR parent.state <> 'RUNNING'\n       OR parent.lease_expires_at <= clock_timestamp()\n       OR raw_hash IS DISTINCT FROM parent.lease_token_hash THEN\n        RAISE EXCEPTION 'Knowledge canonical write claim is expired or superseded';\n    END IF;\n    IF TG_TABLE_NAME IN ('source_pages', 'source_page_embeddings') THEN\n        selected_source_id := (document ->> 'source_snapshot_id')::uuid;\n        IF selected_source_id IS DISTINCT FROM parent.source_snapshot_id THEN\n            RAISE EXCEPTION 'Knowledge page write is outside the claimed source';\n        END IF;\n    ELSIF TG_TABLE_NAME = 'extraction_runs' THEN\n        IF (document ->> 'source_analysis_job_id')::uuid IS DISTINCT FROM parent.id\n           OR (document ->> 'source_analysis_attempt_id')::uuid IS DISTINCT FROM\n              (\n                  SELECT id\n                  FROM knowledge.source_analysis_attempts\n                  WHERE workspace_id = parent.workspace_id\n                    AND job_id = parent.id\n                    AND lease_epoch = parent.lease_epoch\n              )\n           OR (document ->> 'graph_id')::uuid IS DISTINCT FROM parent.graph_id\n           OR (document ->> 'source_snapshot_id')::uuid IS DISTINCT FROM\n              parent.source_snapshot_id\n           OR (document ->> 'contract_version') <> 'DURABLE_SOURCE_V1' THEN\n            RAISE EXCEPTION 'Knowledge extraction evidence is outside the claim';\n        END IF;\n        SELECT * INTO selected_changeset\n        FROM knowledge.changesets\n        WHERE workspace_id = parent.workspace_id\n          AND id = (document ->> 'proposed_changeset_id')::uuid;\n        IF NOT FOUND\n           OR selected_changeset.source_analysis_job_id IS DISTINCT FROM parent.id THEN\n            RAISE EXCEPTION 'Knowledge extraction changeset is outside the claim';\n        END IF;\n    ELSIF TG_TABLE_NAME = 'changesets' THEN\n        IF (document ->> 'graph_id')::uuid IS DISTINCT FROM parent.graph_id\n           OR (document ->> 'author_id')::uuid IS DISTINCT FROM parent.requested_by\n           OR (document ->> 'source_analysis_job_id')::uuid IS DISTINCT FROM parent.id\n           OR (document ->> 'base_release_id')::uuid IS DISTINCT FROM\n              parent.base_release_id\n           OR (document ->> 'ontology_version_id')::uuid IS DISTINCT FROM\n              parent.ontology_version_id\n           OR document ->> 'state' <> 'DRAFT' THEN\n            RAISE EXCEPTION 'Knowledge proposal changeset is outside the claim';\n        END IF;\n    ELSIF TG_TABLE_NAME = 'change_operations' THEN\n        SELECT * INTO selected_changeset FROM knowledge.changesets\n        WHERE workspace_id = parent.workspace_id\n          AND id = (document ->> 'changeset_id')::uuid;\n        IF NOT FOUND\n           OR selected_changeset.graph_id IS DISTINCT FROM parent.graph_id\n           OR selected_changeset.author_id IS DISTINCT FROM parent.requested_by\n           OR selected_changeset.source_analysis_job_id IS DISTINCT FROM parent.id\n           OR selected_changeset.state <> 'DRAFT' THEN\n            RAISE EXCEPTION 'Knowledge proposal operation is outside the claim';\n        END IF;\n    ELSIF TG_TABLE_NAME = 'source_snapshots' THEN\n        IF (document ->> 'id')::uuid IS DISTINCT FROM parent.source_snapshot_id\n           OR document ->> 'state' <> 'ANALYZED' THEN\n            RAISE EXCEPTION 'Knowledge source update is outside the claim';\n        END IF;\n    END IF;\n    RETURN NEW;\nEND\n$$;")
        op.execute('CREATE TRIGGER trg_source_page_job_scope\nBEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_pages\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();')
        op.execute('CREATE TRIGGER trg_source_embedding_job_scope\nBEFORE INSERT OR UPDATE OR DELETE ON knowledge.source_page_embeddings\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();')
        op.execute('CREATE TRIGGER trg_extraction_run_job_scope\nBEFORE INSERT OR UPDATE OR DELETE ON knowledge.extraction_runs\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();')
        op.execute('CREATE TRIGGER trg_changeset_job_scope\nBEFORE INSERT OR UPDATE OR DELETE ON knowledge.changesets\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();')
        op.execute('CREATE TRIGGER trg_change_operation_job_scope\nBEFORE INSERT OR UPDATE OR DELETE ON knowledge.change_operations\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();')
        op.execute('CREATE TRIGGER trg_source_snapshot_job_scope\nBEFORE UPDATE OR DELETE ON knowledge.source_snapshots\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_write_scope();')
        op.execute('CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_shared_evidence_scope()\nRETURNS trigger\nLANGUAGE plpgsql\nAS $$\nDECLARE\n    selected_job_id uuid :=\n        NULLIF(current_setting(\'app.knowledge_source_job_id\', true), \'\')::uuid;\n    document jsonb := to_jsonb(NEW);\n    old_document jsonb := to_jsonb(OLD);\n    parent record;\n    current_attempt record;\n    subject record;\n    membership record;\n    graph record;\n    actor_id uuid :=\n        NULLIF(current_setting(\'app.subject_id\', true), \'\')::uuid;\n    raw_token text :=\n        NULLIF(current_setting(\'app.knowledge_source_lease_token\', true), \'\');\n    raw_hash text;\n    parent_changed_in_transaction boolean := false;\n    expected_event_type text;\n    expected_reasons jsonb := \'[]\'::jsonb;\n    expected_effect text;\n    live_claim boolean := false;\n    recovery_transition boolean := false;\nBEGIN\n    IF current_user = \'datariver_knowledge\'\n       AND session_user <> \'datariver_knowledge\' THEN\n        RAISE EXCEPTION \'Knowledge worker writes require a direct worker session\';\n    END IF;\n    IF TG_TABLE_NAME = \'outbox_events\' THEN\n        IF TG_OP = \'DELETE\'\n           AND old_document ->> \'aggregate_type\'\n               = \'knowledge_source_analysis_job\' THEN\n            RAISE EXCEPTION \'Knowledge outbox evidence is append-only\';\n        ELSIF TG_OP = \'UPDATE\'\n              AND (\n                  old_document ->> \'aggregate_type\'\n                      = \'knowledge_source_analysis_job\'\n                  OR document ->> \'aggregate_type\'\n                      = \'knowledge_source_analysis_job\'\n              ) THEN\n            IF current_user <> \'datariver_relay\'\n               OR (\n                   document - ARRAY[\n                       \'published_at\', \'dead_lettered_at\', \'lease_until\',\n                       \'attempts\', \'last_error_code\'\n                   ]\n               ) IS DISTINCT FROM (\n                   old_document - ARRAY[\n                       \'published_at\', \'dead_lettered_at\', \'lease_until\',\n                       \'attempts\', \'last_error_code\'\n                   ]\n               ) THEN\n                RAISE EXCEPTION \'Knowledge outbox transition evidence is immutable\';\n            END IF;\n            RETURN NEW;\n        ELSIF TG_OP = \'INSERT\'\n              AND document ->> \'aggregate_type\'\n                  = \'knowledge_source_analysis_job\'\n              AND current_user NOT IN (\'datariver_app\', \'datariver_knowledge\') THEN\n            RAISE EXCEPTION \'Knowledge outbox evidence has an unauthorized producer\';\n        END IF;\n    ELSIF TG_TABLE_NAME = \'policy_decisions\' THEN\n        IF TG_OP IN (\'UPDATE\', \'DELETE\')\n           AND old_document -> \'evaluation_context\' ->> \'kind\'\n               = \'knowledge_source_job_finalization\' THEN\n            RAISE EXCEPTION \'Knowledge policy evidence is append-only\';\n        ELSIF TG_OP = \'UPDATE\'\n              AND document -> \'evaluation_context\' ->> \'kind\'\n                  = \'knowledge_source_job_finalization\' THEN\n            RAISE EXCEPTION \'Knowledge policy evidence namespace is immutable\';\n        ELSIF TG_OP = \'INSERT\'\n              AND document -> \'evaluation_context\' ->> \'kind\'\n                  = \'knowledge_source_job_finalization\'\n              AND current_user <> \'datariver_knowledge\' THEN\n            RAISE EXCEPTION \'Knowledge policy evidence has an unauthorized producer\';\n        END IF;\n    END IF;\n    IF current_user = \'datariver_app\'\n       AND TG_TABLE_NAME = \'outbox_events\'\n       AND document ->> \'aggregate_type\'\n           = \'knowledge_source_analysis_job\' THEN\n        IF TG_OP <> \'INSERT\' THEN\n            RAISE EXCEPTION \'Knowledge API outbox evidence is append-only\';\n        END IF;\n        SELECT * INTO parent\n        FROM knowledge.source_analysis_jobs\n        WHERE workspace_id = NEW.workspace_id\n          AND id = NEW.aggregate_id;\n        IF NOT FOUND THEN\n            RAISE EXCEPTION \'Knowledge API outbox parent is unavailable\';\n        END IF;\n        SELECT (job.xmin::text::bigint = txid_current())\n        INTO parent_changed_in_transaction\n        FROM knowledge.source_analysis_jobs AS job\n        WHERE job.workspace_id = parent.workspace_id\n          AND job.id = parent.id;\n        expected_event_type :=\n            \'knowledge.source-analysis.\'\n            || lower(parent.state)\n            || \'.v1\';\n        IF parent.requested_by IS DISTINCT FROM actor_id\n           OR parent.state NOT IN (\'QUEUED\', \'CANCEL_REQUESTED\', \'CANCELLED\')\n           OR NEW.event_type IS DISTINCT FROM expected_event_type\n           OR NEW.schema_version <> 1\n           OR NEW.published_at IS NOT NULL\n           OR NEW.dead_lettered_at IS NOT NULL\n           OR NEW.lease_until IS NOT NULL\n           OR NEW.attempts <> 0\n           OR NEW.last_error_code IS NOT NULL\n           OR NOT parent_changed_in_transaction\n           OR (\n               parent.state = \'QUEUED\'\n               AND (\n                   parent.version <> 1\n                   OR NEW.payload IS DISTINCT FROM jsonb_build_object(\n                       \'job_id\', parent.id,\n                       \'graph_id\', parent.graph_id,\n                       \'source_snapshot_id\', parent.source_snapshot_id,\n                       \'pin_hash\', parent.pin_hash,\n                       \'state\', parent.state,\n                       \'version\', parent.version\n                   )\n               )\n           )\n           OR (\n               parent.state IN (\'CANCEL_REQUESTED\', \'CANCELLED\')\n               AND (\n                   parent.cancel_requested_by IS DISTINCT FROM actor_id\n                   OR NEW.payload IS DISTINCT FROM jsonb_build_object(\n                       \'job_id\', parent.id,\n                       \'graph_id\', parent.graph_id,\n                       \'state\', parent.state,\n                       \'version\', parent.version\n                   )\n               )\n           ) THEN\n            RAISE EXCEPTION \'Knowledge API outbox evidence is invalid\';\n        END IF;\n        NEW.created_at := parent.updated_at;\n        RETURN NEW;\n    END IF;\n    IF current_user <> \'datariver_knowledge\' THEN\n        RETURN NEW;\n    END IF;\n    IF TG_OP <> \'INSERT\' OR selected_job_id IS NULL THEN\n        RAISE EXCEPTION \'Knowledge shared evidence requires one current job\';\n    END IF;\n    SELECT * INTO parent\n    FROM knowledge.source_analysis_jobs\n    WHERE id = selected_job_id\n      AND workspace_id = (document ->> \'workspace_id\')::uuid;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION \'Knowledge shared evidence is outside the selected job\';\n    END IF;\n    SELECT * INTO current_attempt\n    FROM knowledge.source_analysis_attempts\n    WHERE workspace_id = parent.workspace_id\n      AND job_id = parent.id\n      AND lease_epoch = parent.lease_epoch;\n    IF NOT FOUND THEN\n        RAISE EXCEPTION \'Knowledge shared evidence has no current attempt\';\n    END IF;\n    raw_hash := CASE\n        WHEN raw_token IS NULL THEN NULL\n        ELSE encode(sha256(convert_to(raw_token, \'UTF8\')), \'hex\')\n    END;\n    live_claim :=\n        raw_hash = current_attempt.lease_token_hash\n        AND (\n            (\n                parent.state = \'RUNNING\'\n                AND parent.lease_token_hash = raw_hash\n                AND parent.lease_expires_at > clock_timestamp()\n                AND current_attempt.state = \'RUNNING\'\n            )\n            OR (\n                parent.state IN (\'RETRY_WAIT\', \'FAILED\')\n                AND current_attempt.state = \'FAILED\'\n            )\n            OR (\n                parent.state = \'STALE\'\n                AND current_attempt.state = \'STALE\'\n            )\n            OR (\n                parent.state = \'SUCCEEDED\'\n                AND current_attempt.state = \'SUCCEEDED\'\n            )\n            OR (\n                parent.state = \'CANCELLED\'\n                AND current_attempt.state = \'CANCELLED\'\n            )\n        );\n    SELECT (job.xmin::text::bigint = txid_current())\n    INTO parent_changed_in_transaction\n    FROM knowledge.source_analysis_jobs AS job\n    WHERE job.workspace_id = parent.workspace_id\n      AND job.id = parent.id;\n    recovery_transition :=\n        raw_token IS NULL\n        AND parent_changed_in_transaction\n        AND current_attempt.state = \'SUPERSEDED\'\n        AND current_attempt.failure_code = \'LEASE_EXPIRED\'\n        AND current_attempt.finished_at = parent.updated_at\n        AND parent.state IN (\'RETRY_WAIT\', \'FAILED\', \'CANCELLED\');\n    IF TG_TABLE_NAME = \'outbox_events\' THEN\n        expected_event_type :=\n            \'knowledge.source-analysis.\'\n            || lower(parent.state)\n            || \'.v1\';\n        IF document ->> \'aggregate_type\' <> \'knowledge_source_analysis_job\'\n           OR (document ->> \'aggregate_id\')::uuid IS DISTINCT FROM parent.id\n           OR document ->> \'event_type\' IS DISTINCT FROM expected_event_type\n           OR parent.state NOT IN (\n               \'RETRY_WAIT\', \'SUCCEEDED\', \'FAILED\', \'STALE\', \'CANCELLED\'\n           )\n           OR document -> \'payload\' IS DISTINCT FROM jsonb_build_object(\n               \'job_id\', parent.id,\n               \'graph_id\', parent.graph_id,\n               \'state\', parent.state,\n               \'version\', parent.version\n           )\n           OR NEW.schema_version <> 1\n           OR NEW.published_at IS NOT NULL\n           OR NEW.dead_lettered_at IS NOT NULL\n           OR NEW.lease_until IS NOT NULL\n           OR NEW.attempts <> 0\n           OR NEW.last_error_code IS NOT NULL\n           OR NOT parent_changed_in_transaction\n           OR (NOT live_claim AND NOT recovery_transition) THEN\n            RAISE EXCEPTION \'Knowledge outbox evidence is outside the selected job\';\n        END IF;\n        NEW.created_at := parent.updated_at;\n    ELSIF TG_TABLE_NAME = \'policy_decisions\' THEN\n        IF NOT (\n            parent.state = \'RUNNING\'\n            AND parent.lease_token_hash = raw_hash\n            AND parent.lease_expires_at > clock_timestamp()\n            AND current_attempt.state = \'RUNNING\'\n            AND current_attempt.lease_token_hash = raw_hash\n        ) THEN\n            RAISE EXCEPTION \'Knowledge policy evidence has no live claim\';\n        END IF;\n        SELECT * INTO subject\n        FROM iam.subjects\n        WHERE id = parent.requested_by;\n        SELECT * INTO membership\n        FROM iam.workspace_memberships\n        WHERE workspace_id = parent.workspace_id\n          AND subject_id = parent.requested_by;\n        SELECT * INTO graph\n        FROM knowledge.graphs\n        WHERE workspace_id = parent.workspace_id\n          AND id = parent.graph_id;\n        IF subject.id IS NULL OR membership.subject_id IS NULL OR graph.id IS NULL THEN\n            RAISE EXCEPTION \'Knowledge policy evidence inputs are unavailable\';\n        END IF;\n        IF NOT (\n            subject.active\n            AND membership.active\n            AND (\n                membership.access_expires_at IS NULL\n                OR membership.access_expires_at > NEW.decided_at\n            )\n        ) THEN\n            expected_reasons := expected_reasons\n                || \'["SUBJECT_INACTIVE"]\'::jsonb;\n        END IF;\n        IF COALESCE(\n            membership.attributes -> \'denied_actions\' @> \'["kg.edit"]\'::jsonb,\n            false\n        ) THEN\n            expected_reasons := expected_reasons\n                || \'["EXPLICIT_ACTION_DENY"]\'::jsonb;\n        END IF;\n        IF NOT COALESCE(\n            membership.attributes -> \'allowed_actions\' @> \'["kg.edit"]\'::jsonb,\n            false\n        ) THEN\n            expected_reasons := expected_reasons\n                || \'["ACTION_NOT_GRANTED"]\'::jsonb;\n        END IF;\n        IF graph.classification > membership.clearance THEN\n            expected_reasons := expected_reasons\n                || \'["CLEARANCE_INSUFFICIENT"]\'::jsonb;\n        END IF;\n        expected_effect := CASE\n            WHEN expected_reasons = \'[]\'::jsonb THEN \'ALLOW\'\n            ELSE \'DENY\'\n        END;\n        IF expected_reasons = \'[]\'::jsonb THEN\n            expected_reasons := \'["POLICY_ALLOW"]\'::jsonb;\n        END IF;\n        IF (document ->> \'subject_id\')::uuid IS DISTINCT FROM parent.requested_by\n           OR (document ->> \'resource_id\')::uuid IS DISTINCT FROM parent.graph_id\n           OR document ->> \'action\' <> \'kg.edit\'\n           OR document -> \'evaluation_context\' ->> \'kind\'\n              <> \'knowledge_source_job_finalization\'\n           OR document -> \'evaluation_context\' ->> \'job_id\'\n              IS DISTINCT FROM parent.id::text\n           OR document -> \'evaluation_context\' ->> \'pin_hash\'\n              IS DISTINCT FROM parent.pin_hash\n           OR document -> \'evaluation_context\'\n              IS DISTINCT FROM jsonb_build_object(\n                  \'kind\', \'knowledge_source_job_finalization\',\n                  \'job_id\', parent.id,\n                  \'pin_hash\', parent.pin_hash\n              )\n           OR document ->> \'request_id\' IS DISTINCT FROM parent.id::text\n           OR document ->> \'effect\' IS DISTINCT FROM expected_effect\n           OR document -> \'reason_codes\' IS DISTINCT FROM expected_reasons\n           OR document -> \'policy_versions\'\n              IS DISTINCT FROM \'["builtin-abac-v2"]\'::jsonb\n           OR NEW.decided_at < current_attempt.started_at\n           OR NEW.decided_at > clock_timestamp() + interval \'30 seconds\' THEN\n            RAISE EXCEPTION \'Knowledge policy evidence is outside the selected job\';\n        END IF;\n    END IF;\n    RETURN NEW;\nEND\n$$;')
        op.execute('CREATE TRIGGER trg_knowledge_source_outbox_scope\nBEFORE INSERT OR UPDATE OR DELETE ON integration.outbox_events\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_shared_evidence_scope();')
        op.execute('CREATE TRIGGER trg_knowledge_source_policy_decision_scope\nBEFORE INSERT OR UPDATE OR DELETE ON authz.policy_decisions\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_shared_evidence_scope();')
        op.execute("CREATE OR REPLACE FUNCTION knowledge.enforce_source_analysis_inbox_scope()\nRETURNS trigger\nLANGUAGE plpgsql\nAS $$\nBEGIN\n    IF current_user = 'datariver_knowledge'\n       AND session_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'Knowledge worker writes require a direct worker session';\n    END IF;\n    IF TG_OP = 'DELETE'\n       AND OLD.consumer = 'knowledge-source-analysis-v1' THEN\n        RAISE EXCEPTION 'Knowledge inbox evidence is append-only';\n    ELSIF TG_OP = 'UPDATE'\n          AND (\n              OLD.consumer = 'knowledge-source-analysis-v1'\n              OR NEW.consumer = 'knowledge-source-analysis-v1'\n          )\n          AND current_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'Knowledge inbox evidence has an unauthorized consumer';\n    ELSIF TG_OP = 'INSERT'\n          AND NEW.consumer = 'knowledge-source-analysis-v1'\n          AND current_user <> 'datariver_knowledge' THEN\n        RAISE EXCEPTION 'Knowledge inbox evidence has an unauthorized consumer';\n    END IF;\n    IF current_user <> 'datariver_knowledge' THEN\n        IF TG_OP = 'DELETE' THEN\n            RETURN OLD;\n        END IF;\n        RETURN NEW;\n    END IF;\n    IF TG_OP = 'DELETE' THEN\n        RAISE EXCEPTION 'Knowledge inbox evidence is not worker-deletable';\n    END IF;\n    IF NEW.consumer <> 'knowledge-source-analysis-v1' THEN\n        RAISE EXCEPTION 'Knowledge inbox consumer is outside the worker scope';\n    END IF;\n    IF TG_OP = 'UPDATE'\n       AND (\n           NEW.consumer IS DISTINCT FROM OLD.consumer\n           OR NEW.event_id IS DISTINCT FROM OLD.event_id\n           OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id\n           OR NEW.received_at IS DISTINCT FROM OLD.received_at\n       ) THEN\n        RAISE EXCEPTION 'Knowledge inbox identity is immutable';\n    END IF;\n    RETURN NEW;\nEND\n$$;")
        op.execute('CREATE TRIGGER trg_knowledge_source_inbox_scope\nBEFORE INSERT OR UPDATE OR DELETE ON integration.inbox_messages\nFOR EACH ROW EXECUTE FUNCTION knowledge.enforce_source_analysis_inbox_scope();')
        op.execute('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA\n    platform, iam, authz, catalog, governance, integration,\n    knowledge, assistant, sharing, retention\nFROM datariver_knowledge;')
        op.execute('REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA\n    platform, iam, authz, catalog, governance, integration,\n    knowledge, assistant, sharing, retention\nFROM datariver_knowledge;')
        op.execute('REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA\n    platform, iam, authz, catalog, governance, integration,\n    knowledge, assistant, sharing, retention\nFROM datariver_knowledge;')
        op.execute('REVOKE ALL PRIVILEGES ON SCHEMA\n    platform, iam, authz, catalog, governance, integration,\n    knowledge, assistant, sharing, retention\nFROM datariver_knowledge;')
        op.execute('REVOKE INSERT, UPDATE, DELETE ON knowledge.source_pages,\n    knowledge.source_page_embeddings, knowledge.extraction_runs\nFROM datariver_app;')
        op.execute('GRANT SELECT, INSERT ON knowledge.source_analysis_jobs TO datariver_app;')
        op.execute('GRANT UPDATE (\n    state, stage, cancel_requested_by, cancel_requested_at, cancel_reason,\n    completed_at, version, updated_at\n) ON knowledge.source_analysis_jobs TO datariver_app;')
        op.execute('GRANT SELECT, INSERT ON knowledge.source_analysis_events TO datariver_app;')
        op.execute('GRANT USAGE ON SCHEMA platform, iam, authz, integration, knowledge\nTO datariver_knowledge;')
        op.execute('GRANT SELECT ON platform.external_service_profiles,\n    platform.external_service_profile_versions,\n    iam.subjects, iam.workspace_memberships,\n    integration.object_manifests, integration.inbox_messages,\n    knowledge.graphs, knowledge.ontology_versions, knowledge.releases,\n    knowledge.source_snapshots, knowledge.source_analysis_jobs,\n    knowledge.source_analysis_attempts, knowledge.source_analysis_events,\n    knowledge.changesets\nTO datariver_knowledge;')
        op.execute('GRANT INSERT ON authz.policy_decisions, integration.outbox_events,\n    integration.inbox_messages, knowledge.source_analysis_attempts,\n    knowledge.source_analysis_events, knowledge.source_pages,\n    knowledge.source_page_embeddings, knowledge.changesets,\n    knowledge.change_operations, knowledge.extraction_runs\nTO datariver_knowledge;')
        op.execute('GRANT UPDATE (completed_at, result_hash)\nON integration.inbox_messages TO datariver_knowledge;')
        op.execute('GRANT UPDATE (\n    state, stage, progress, next_attempt_at, attempt_count, lease_epoch,\n    lease_token_hash, lease_owner_fingerprint, lease_started_at,\n    lease_expires_at, result_changeset_id, result_evidence_hash,\n    last_failure_code, completed_at, version, updated_at\n) ON knowledge.source_analysis_jobs TO datariver_knowledge;')
        op.execute('GRANT UPDATE (\n    state, stage, output_hash, external_response_hash, retryable,\n    failure_code, finished_at\n) ON knowledge.source_analysis_attempts TO datariver_knowledge;')
        op.execute('GRANT UPDATE (state, updated_at)\nON knowledge.source_snapshots TO datariver_knowledge;')
        op.execute('GRANT EXECUTE ON FUNCTION knowledge.list_knowledge_worker_workspaces()\nTO datariver_knowledge;')
        op.execute('GRANT EXECUTE ON FUNCTION knowledge.lock_source_analysis_finalization()\nTO datariver_knowledge;')
        op.execute('GRANT EXECUTE ON FUNCTION knowledge.current_source_claim_scope()\nTO datariver_knowledge;')


def downgrade() -> None:
        op.execute('DROP POLICY IF EXISTS knowledge_worker_current_changeset\n    ON knowledge.changesets;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_current_source\n    ON knowledge.source_snapshots;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_current_release\n    ON knowledge.releases;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_current_ontology\n    ON knowledge.ontology_versions;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_current_graph\n    ON knowledge.graphs;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_inbox_consumer\n    ON integration.inbox_messages;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_current_manifest\n    ON integration.object_manifests;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_current_membership\n    ON iam.workspace_memberships;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_inference_profile_versions\n    ON platform.external_service_profile_versions;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_inference_profiles\n    ON platform.external_service_profiles;')
        op.execute('DROP POLICY IF EXISTS knowledge_worker_current_subject\n    ON iam.subjects;')
        op.execute('DROP POLICY IF EXISTS existing_subject_privileges ON iam.subjects;')
        op.execute('ALTER TABLE iam.subjects NO FORCE ROW LEVEL SECURITY;')
        op.execute('ALTER TABLE iam.subjects DISABLE ROW LEVEL SECURITY;')
        op.execute('DROP INDEX IF EXISTS authz.ux_policy_decisions_source_analysis_finalization;')
        op.execute('DROP INDEX IF EXISTS integration.ux_outbox_source_analysis_transition;')
        op.execute('DROP TRIGGER IF EXISTS trg_knowledge_source_inbox_scope\n    ON integration.inbox_messages;')
        op.execute('DROP TRIGGER IF EXISTS trg_knowledge_source_policy_decision_scope\n    ON authz.policy_decisions;')
        op.execute('DROP TRIGGER IF EXISTS trg_knowledge_source_outbox_scope\n    ON integration.outbox_events;')
        op.execute('DROP TRIGGER IF EXISTS trg_source_snapshot_job_scope\n    ON knowledge.source_snapshots;')
        op.execute('DROP TRIGGER IF EXISTS trg_change_operation_job_scope\n    ON knowledge.change_operations;')
        op.execute('DROP TRIGGER IF EXISTS trg_changeset_job_scope ON knowledge.changesets;')
        op.execute('DROP TRIGGER IF EXISTS trg_extraction_run_job_scope\n    ON knowledge.extraction_runs;')
        op.execute('DROP TRIGGER IF EXISTS trg_source_embedding_job_scope\n    ON knowledge.source_page_embeddings;')
        op.execute('DROP TRIGGER IF EXISTS trg_source_page_job_scope ON knowledge.source_pages;')
        op.execute('DROP TRIGGER IF EXISTS trg_source_analysis_event_append_only\n    ON knowledge.source_analysis_events;')
        op.execute('DROP TRIGGER IF EXISTS trg_source_analysis_attempt_terminal_pair\n    ON knowledge.source_analysis_attempts;')
        op.execute('DROP TRIGGER IF EXISTS trg_source_analysis_attempt_fence\n    ON knowledge.source_analysis_attempts;')
        op.execute('DROP TRIGGER IF EXISTS trg_source_analysis_job_fence\n    ON knowledge.source_analysis_jobs;')
        op.execute('DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_write_scope();')
        op.execute('DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_inbox_scope();')
        op.execute('DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_shared_evidence_scope();')
        op.execute('DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_event_append_only();')
        op.execute('DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_attempt_terminal_pair();')
        op.execute('DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_attempt_fence();')
        op.execute('DROP FUNCTION IF EXISTS knowledge.enforce_source_analysis_job_fence();')
        op.execute('DROP FUNCTION IF EXISTS knowledge.lock_source_analysis_finalization();')
        op.execute('DROP FUNCTION IF EXISTS knowledge.list_knowledge_worker_workspaces();')
        op.execute('DROP FUNCTION IF EXISTS knowledge.current_source_claim_scope();')
        op.execute('DROP FUNCTION iam.provision_workspace_identity(uuid, uuid, text, text, text, text, uuid, text, uuid, timestamptz)')
        op.execute('DROP FUNCTION iam.resolve_default_workspace(text, text)')
        op.execute('DROP TRIGGER enforce_chat_message_retention_binding ON assistant.chat_messages')
        op.execute('DROP FUNCTION assistant.enforce_chat_message_retention_binding()')
        op.execute('DROP TRIGGER enforce_chat_session_retention_binding ON assistant.chat_sessions')
        op.execute('DROP FUNCTION assistant.enforce_chat_session_retention_binding()')
        op.execute('DROP TRIGGER reject_upload_registration_candidate_evidence_mutation ON integration.upload_registration_candidates')
        op.execute('DROP FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()')
        op.execute('DROP TRIGGER reject_object_manifest_content_profile_change ON integration.object_manifests')
        op.execute('DROP FUNCTION integration.reject_object_manifest_content_profile_change()')
        op.drop_constraint(op.f('fk_source_analysis_jobs_workspace_id_graph_id_result_changeset_id_changesets'), 'source_analysis_jobs', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_source_analysis_jobs_workspace_id_graph_id_base_release_id_releases'), 'source_analysis_jobs', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_graphs_workspace_id_id_active_release_id_releases'), 'graphs', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_changesets_workspace_id_source_analysis_job_id_source_analysis_jobs'), 'changesets', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_changesets_workspace_id_graph_id_published_release_id_releases'), 'changesets', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_changesets_workspace_id_graph_id_base_release_id_releases'), 'changesets', schema='knowledge', type_='foreignkey')
        op.drop_constraint('fk_change_requests_current_round', 'change_requests', schema='governance', type_='foreignkey')
        op.drop_constraint('fk_catalog_export_requests_workspace_job', 'export_requests', schema='catalog', type_='foreignkey')
        op.drop_constraint(op.f('fk_api_products_workspace_id_id_current_version_id_api_product_versions'), 'api_products', schema='sharing', type_='foreignkey')
        op.drop_table('evidence_citations', schema='assistant')
        op.drop_table('api_invocations', schema='sharing')
        op.drop_table('execution_events', schema='retention')
        op.drop_table('execution_attempts', schema='retention')
        op.drop_table('catalog_metadata_candidate_rows', schema='integration')
        op.drop_table('registration_metadata_content_bindings', schema='governance')
        op.drop_table('registration_content_bindings', schema='governance')
        op.drop_table('assistant_runs', schema='assistant')
        op.drop_table('consumer_grants', schema='sharing')
        op.drop_table('execution_jobs', schema='retention')
        op.drop_table('erasure_request_events', schema='retention')
        op.drop_table('source_analysis_events', schema='knowledge')
        op.drop_table('extraction_runs', schema='knowledge')
        op.drop_table('upload_registration_candidates', schema='integration')
        op.drop_table('catalog_metadata_rows', schema='integration')
        op.drop_table('catalog_metadata_candidates', schema='integration')
        op.drop_table('manual_metadata_aspect_reports', schema='governance')
        op.drop_table('restricted_search_grant_events', schema='authz')
        op.drop_table('chat_messages', schema='assistant')
        op.drop_table('api_product_versions', schema='sharing')
        op.drop_table('policy_class_rules', schema='retention')
        op.drop_table('legal_hold_events', schema='retention')
        op.drop_table('immutable_archive_receipts', schema='retention')
        op.drop_table('erasure_requests', schema='retention')
        op.drop_table('external_service_profile_versions', schema='platform')
        op.drop_table('validation_results', schema='knowledge')
        op.drop_table('source_page_embeddings', schema='knowledge')
        op.drop_table('source_analysis_attempts', schema='knowledge')
        op.drop_table('release_nodes', schema='knowledge')
        op.drop_table('release_edges', schema='knowledge')
        op.drop_table('projection_deployments', schema='knowledge')
        op.drop_table('graphrag_audits', schema='knowledge')
        op.drop_table('change_operations', schema='knowledge')
        op.drop_table('upload_preparation_receipts', schema='integration')
        op.drop_table('job_attempts', schema='integration')
        op.drop_table('admin_access_approvals', schema='iam')
        op.drop_table('access_role_data_rules', schema='iam')
        op.drop_table('access_role_assignments', schema='iam')
        op.drop_table('access_role_assignment_events', schema='iam')
        op.drop_table('manual_metadata_apply_attempts', schema='governance')
        op.drop_table('change_test_runs', schema='governance')
        op.drop_table('restricted_search_grants', schema='authz')
        op.drop_table('classification_access_policy_rules', schema='authz')
        op.drop_table('chat_sessions', schema='assistant')
        op.drop_table('policy_versions', schema='retention')
        op.drop_table('legal_holds', schema='retention')
        op.drop_table('system_schema_scopes', schema='platform')
        op.drop_table('system_assignees', schema='platform')
        op.drop_table('external_service_profiles', schema='platform')
        op.drop_table('source_pages', schema='knowledge')
        op.drop_table('source_analysis_jobs', schema='knowledge')
        op.drop_table('releases', schema='knowledge')
        op.drop_table('changesets', schema='knowledge')
        op.drop_table('upload_preparation_jobs', schema='integration')
        op.drop_table('registration_worker_call_receipts', schema='integration')
        op.drop_table('jobs', schema='integration')
        op.drop_table('inference_provider_profile_versions', schema='integration')
        op.drop_table('membership_renewal_requests', schema='iam')
        op.drop_table('admin_access_requests', schema='iam')
        op.drop_table('access_roles', schema='iam')
        op.drop_table('state_transitions', schema='governance')
        op.drop_table('manual_metadata_submissions', schema='governance')
        op.drop_table('change_request_items', schema='governance')
        op.drop_table('change_request_attachments', schema='governance')
        op.drop_table('change_request_attachment_upload_intents', schema='governance')
        op.drop_table('approvals', schema='governance')
        op.drop_table('export_requests', schema='catalog')
        op.drop_table('classification_access_policy_versions', schema='authz')
        op.drop_table('api_products', schema='sharing')
        op.drop_table('archive_capability_attestations', schema='retention')
        op.drop_table('data_systems', schema='platform')
        op.drop_table('source_snapshots', schema='knowledge')
        op.drop_table('ontology_versions', schema='knowledge')
        op.drop_table('inference_provider_generations', schema='integration')
        op.drop_table('workspace_memberships', schema='iam')
        op.drop_table('change_request_rounds', schema='governance')
        op.drop_table('vocabulary_sync_runs', schema='catalog')
        op.drop_table('vocabulary_entries', schema='catalog')
        op.drop_table('projection_watermarks', schema='catalog')
        op.drop_table('classification_access_generations', schema='authz')
        op.drop_table('workspaces', schema='platform')
        op.drop_table('graphs', schema='knowledge')
        op.drop_table('seed_runs', schema='integration')
        op.drop_table('outbox_events', schema='integration')
        op.drop_table('object_manifests', schema='integration')
        op.drop_table('inbox_messages', schema='integration')
        op.drop_table('idempotency_keys', schema='integration')
        op.drop_table('subjects', schema='iam')
        op.drop_table('change_requests', schema='governance')
        op.drop_table('sync_runs', schema='catalog')
        op.drop_table('assets_projection', schema='catalog')
        op.drop_table('resources', schema='authz')
        op.drop_table('policy_decisions', schema='authz')
        op.execute('DROP SCHEMA IF EXISTS retention')
        op.execute('DROP SCHEMA IF EXISTS sharing')
        op.execute('DROP SCHEMA IF EXISTS assistant')
        op.execute('DROP SCHEMA IF EXISTS knowledge')
        op.execute('DROP SCHEMA IF EXISTS integration')
        op.execute('DROP SCHEMA IF EXISTS governance')
        op.execute('DROP SCHEMA IF EXISTS catalog')
        op.execute('DROP SCHEMA IF EXISTS authz')
        op.execute('DROP SCHEMA IF EXISTS iam')
        op.execute('DROP SCHEMA IF EXISTS platform')
