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
        sa.Column('search_vector', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple'::regconfig, coalesce(name, '') || ' ' || coalesce(description, ''))", persisted=True), nullable=False),
        sa.Column('platform', sa.String(length=100), nullable=True),
        sa.Column('database_name', sa.String(length=255), nullable=True),
        sa.Column('schema_name', sa.String(length=255), nullable=True),
        sa.Column('owner_ref', sa.String(length=1000), nullable=True),
        sa.Column('domain_ref', sa.String(length=1000), nullable=True),
        sa.Column('tags', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('glossary_terms', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('column_names', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
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
        sa.PrimaryKeyConstraint('id', name=op.f('pk_assets_projection')),
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
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_requests')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_change_requests_workspace_id_id')),
        sa.UniqueConstraint('workspace_id', 'number', name=op.f('uq_change_requests_workspace_id_number')),
        schema='governance'
        )
        op.create_index('ix_change_requests_workspace_state', 'change_requests', ['workspace_id', 'state', 'created_at'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.change_requests ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.change_requests FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.change_requests USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('subjects',
        sa.Column('issuer', sa.String(length=500), nullable=False),
        sa.Column('external_subject', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_subjects')),
        sa.UniqueConstraint('issuer', 'external_subject', name=op.f('uq_subjects_issuer_external_subject')),
        schema='iam'
        )
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
        sa.Column('last_error_code', sa.String(length=100), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs')),
        sa.UniqueConstraint('job_type', 'causation_id', name=op.f('uq_jobs_job_type_causation_id')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_jobs_workspace_id_id')),
        schema='integration'
        )
        op.create_index('ix_jobs_workspace_state', 'jobs', ['workspace_id', 'state', 'created_at'], unique=False, schema='integration')
        op.execute('ALTER TABLE integration.jobs ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.jobs FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.jobs USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
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
        sa.CheckConstraint("content_profile IN ('FORMAT_ONLY_V1', 'DATASET_DESCRIPTION_CSV_V1')", name=op.f('ck_object_manifests_content_profile_allowlist')),
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
        op.create_table('approvals',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('stage', sa.String(length=50), nullable=False),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name=op.f('fk_approvals_workspace_id_change_request_id_change_requests'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals')),
        sa.UniqueConstraint('change_request_id', 'stage', 'actor_id', name=op.f('uq_approvals_change_request_id_stage_actor_id')),
        schema='governance'
        )
        op.execute('ALTER TABLE governance.approvals ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.approvals FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.approvals USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
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
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint("target_binding_hash IS NULL OR target_binding_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_change_request_items_target_binding_hash_sha256')),
        sa.CheckConstraint('(target_asset_id IS NULL AND target_asset_type IS NULL AND target_system_id IS NULL AND target_domain_id IS NULL AND target_owner_department_id IS NULL AND target_classification IS NULL AND target_lifecycle IS NULL AND target_source_version IS NULL AND target_observed_at IS NULL AND target_binding_hash IS NULL) OR (target_asset_id IS NOT NULL AND target_asset_type IS NOT NULL AND target_classification IS NOT NULL AND target_lifecycle IS NOT NULL AND target_source_version IS NOT NULL AND target_observed_at IS NOT NULL AND target_binding_hash IS NOT NULL)', name=op.f('ck_change_request_items_target_binding_shape')),
        sa.CheckConstraint('target_classification IS NULL OR target_classification BETWEEN 0 AND 3', name=op.f('ck_change_request_items_target_classification_range')),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name=op.f('fk_change_request_items_workspace_id_change_request_id_change_requests'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_request_items')),
        sa.UniqueConstraint('change_request_id', 'ordinal', name=op.f('uq_change_request_items_change_request_id_ordinal')),
        sa.UniqueConstraint('workspace_id', 'change_request_id', 'id', name='uq_change_request_item_request_identity'),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_change_request_items_workspace_id_id')),
        schema='governance'
        )
        op.create_index('ix_change_items_request', 'change_request_items', ['change_request_id'], unique=False, schema='governance')
        op.create_index('ix_change_items_target', 'change_request_items', ['workspace_id', 'target_asset_id', 'aspect_name'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.change_request_items ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.change_request_items FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.change_request_items USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('state_transitions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('change_request_id', sa.Uuid(), nullable=False),
        sa.Column('from_state', sa.String(length=32), nullable=False),
        sa.Column('to_state', sa.String(length=32), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('policy_decision_id', sa.Uuid(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name=op.f('fk_state_transitions_workspace_id_change_request_id_change_requests'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_state_transitions')),
        schema='governance'
        )
        op.create_index('ix_state_transitions_request_time', 'state_transitions', ['change_request_id', 'occurred_at'], unique=False, schema='governance')
        op.execute('ALTER TABLE governance.state_transitions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.state_transitions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.state_transitions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('workspace_memberships',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('subject_id', sa.Uuid(), nullable=False),
        sa.Column('department_id', sa.Uuid(), nullable=True),
        sa.Column('job_function', sa.String(length=100), nullable=True),
        sa.Column('clearance', sa.Integer(), nullable=False),
        sa.Column('attributes', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['subject_id'], ['iam.subjects.id'], name=op.f('fk_workspace_memberships_subject_id_subjects'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['platform.workspaces.id'], name=op.f('fk_workspace_memberships_workspace_id_workspaces'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('workspace_id', 'subject_id', name=op.f('pk_workspace_memberships')),
        sa.UniqueConstraint('workspace_id', 'subject_id', name=op.f('uq_workspace_memberships_workspace_id_subject_id')),
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
        op.create_index('ix_inference_profile_versions_workspace_state', 'inference_provider_profile_versions', ['workspace_id', 'state', 'profile_key'], unique=False, schema='integration')
        op.execute('ALTER TABLE integration.inference_provider_profile_versions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE integration.inference_provider_profile_versions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON integration.inference_provider_profile_versions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
        op.create_table('upload_preparation_jobs',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('upload_id', sa.Uuid(), nullable=False),
        sa.Column('requested_by', sa.Uuid(), nullable=False),
        sa.Column('content_profile', sa.String(length=100), nullable=False),
        sa.Column('source_manifest_version', sa.Integer(), nullable=False),
        sa.Column('source_sha256', sa.String(length=64), nullable=False),
        sa.Column('configuration_hash', sa.String(length=64), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
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
        sa.CheckConstraint("configuration_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_jobs_configuration_hash_valid')),
        sa.CheckConstraint("content_profile = 'DATASET_DESCRIPTION_CSV_V1'", name=op.f('ck_upload_preparation_jobs_typed_profile_allowlist')),
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
        op.create_index('ix_upload_preparation_jobs_claim', 'upload_preparation_jobs', ['state', 'lease_until', 'created_at'], unique=False, schema='integration')
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
        op.create_table('external_service_profiles',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('service_key', sa.String(length=32), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('endpoint_url', sa.String(length=2048), nullable=False),
        sa.Column('auth_principal', sa.String(length=255), nullable=True),
        sa.Column('secret_reference', sa.String(length=512), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('updated_by', sa.Uuid(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint("endpoint_url ~ '^https?://'", name=op.f('ck_external_service_profiles_endpoint_url_scheme')),
        sa.CheckConstraint("service_key IN ('DATAHUB', 'AIRFLOW', 'PROMETHEUS', 'NEO4J')", name=op.f('ck_external_service_profiles_service_key_vocabulary')),
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
        op.execute('ALTER TABLE authz.restricted_search_grants ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE authz.restricted_search_grants FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON authz.restricted_search_grants USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
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
        sa.CheckConstraint("content_profile = 'DATASET_DESCRIPTION_CSV_V1'", name=op.f('ck_upload_preparation_receipts_typed_profile_allowlist')),
        sa.CheckConstraint("object_locator_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_receipts_object_locator_hash_valid')),
        sa.CheckConstraint("receipt_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_receipts_receipt_hash_valid')),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_upload_preparation_receipts_source_sha256_valid')),
        sa.CheckConstraint('accepted_sha256 = source_sha256', name=op.f('ck_upload_preparation_receipts_accepted_source_sha256_equal')),
        sa.CheckConstraint('item_count >= 0 AND rejected_count >= 0', name=op.f('ck_upload_preparation_receipts_row_counts_nonnegative')),
        sa.CheckConstraint('manifest_version > 0', name=op.f('ck_upload_preparation_receipts_manifest_version_positive')),
        sa.ForeignKeyConstraint(['workspace_id', 'preparation_job_id', 'upload_id', 'manifest_version', 'source_sha256', 'content_profile', 'configuration_hash'], ['integration.upload_preparation_jobs.workspace_id', 'integration.upload_preparation_jobs.id', 'integration.upload_preparation_jobs.upload_id', 'integration.upload_preparation_jobs.source_manifest_version', 'integration.upload_preparation_jobs.source_sha256', 'integration.upload_preparation_jobs.content_profile', 'integration.upload_preparation_jobs.configuration_hash'], name='fk_upload_prep_receipts_source_evidence', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workspace_id', 'upload_id'], ['integration.object_manifests.workspace_id', 'integration.object_manifests.id'], name='fk_upload_prep_receipts_workspace_upload', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_preparation_receipts')),
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
        op.create_table('projection_deployments',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('release_id', sa.Uuid(), nullable=False),
        sa.Column('adapter', sa.String(length=100), nullable=False),
        sa.Column('target_ref', sa.String(length=500), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('node_count', sa.Integer(), nullable=True),
        sa.Column('edge_count', sa.Integer(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'release_id'], ['knowledge.releases.workspace_id', 'knowledge.releases.id'], name=op.f('fk_projection_deployments_workspace_id_release_id_releases'), ondelete='CASCADE'),
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
        sa.UniqueConstraint('workspace_id', 'id', name='uq_erasure_requests_workspace_id_id'),
        sa.UniqueConstraint('workspace_id', 'requester_id', 'payload_hash', name='uq_erasure_requests_idempotent_payload'),
        schema='retention'
        )
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
        sa.CheckConstraint("source IN ('OUTBOX_EVENTS', 'INBOX_MESSAGES', 'POLICY_DECISIONS', 'ASSISTANT_RUNS')", name=op.f('ck_immutable_archive_receipts_source')),
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
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_registration_content_bindings_workspace_id_id')),
        schema='governance'
        )
        op.execute('ALTER TABLE governance.registration_content_bindings ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE governance.registration_content_bindings FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON governance.registration_content_bindings USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
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
        op.execute("\n        CREATE FUNCTION iam.resolve_default_workspace(\n            p_issuer text,\n            p_external_subject text\n        )\n        RETURNS uuid\n        LANGUAGE sql\n        STABLE\n        SECURITY DEFINER\n        SET search_path = pg_catalog, iam, platform\n        AS $datariver$\n            SELECT membership.workspace_id\n            FROM iam.subjects AS subject\n            JOIN iam.workspace_memberships AS membership\n              ON membership.subject_id = subject.id\n            JOIN platform.workspaces AS workspace\n              ON workspace.id = membership.workspace_id\n            WHERE subject.issuer = p_issuer\n              AND subject.external_subject = p_external_subject\n              AND subject.active IS TRUE\n              AND membership.active IS TRUE\n              AND workspace.status = 'ACTIVE'\n            ORDER BY\n              CASE WHEN membership.attributes ->> 'default_workspace' = 'true'\n                THEN 0 ELSE 1 END,\n              workspace.slug ASC,\n              membership.workspace_id ASC\n            LIMIT 1\n        $datariver$\n        ")
        op.execute('REVOKE ALL ON FUNCTION iam.resolve_default_workspace(text, text) FROM PUBLIC')
        op.create_foreign_key(op.f('fk_api_products_workspace_id_id_current_version_id_api_product_versions'), 'api_products', 'api_product_versions', ['workspace_id', 'id', 'current_version_id'], ['workspace_id', 'product_id', 'id'], source_schema='sharing', referent_schema='sharing', use_alter=True)
        op.create_foreign_key('fk_catalog_export_requests_workspace_job', 'export_requests', 'jobs', ['workspace_id', 'job_id'], ['workspace_id', 'id'], source_schema='catalog', referent_schema='integration', ondelete='RESTRICT', use_alter=True)
        op.create_foreign_key(op.f('fk_changesets_workspace_id_graph_id_base_release_id_releases'), 'changesets', 'releases', ['workspace_id', 'graph_id', 'base_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', use_alter=True)
        op.create_foreign_key(op.f('fk_changesets_workspace_id_graph_id_published_release_id_releases'), 'changesets', 'releases', ['workspace_id', 'graph_id', 'published_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', use_alter=True)
        op.create_foreign_key(op.f('fk_graphs_workspace_id_id_active_release_id_releases'), 'graphs', 'releases', ['workspace_id', 'id', 'active_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', use_alter=True)
        op.execute("DO $datariver$\nBEGIN\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN\n        GRANT USAGE ON SCHEMA platform, iam, authz, catalog, governance, integration, knowledge, assistant, sharing, retention TO datariver_app;\n        GRANT USAGE ON SCHEMA public TO datariver_app;\n        GRANT SELECT ON public.alembic_version TO datariver_app;\n        GRANT SELECT ON platform.workspaces, iam.subjects TO datariver_app;\n        GRANT SELECT ON iam.workspace_memberships TO datariver_app;\n        GRANT EXECUTE ON FUNCTION iam.resolve_default_workspace(text, text) TO datariver_app;\n        GRANT UPDATE (active, clearance, attributes, version, updated_at)\n            ON iam.workspace_memberships TO datariver_app;\n        GRANT SELECT, INSERT ON iam.admin_access_requests TO datariver_app;\n        GRANT UPDATE (state, checker_id, consumed_by, consumed_at,\n            consume_policy_decision_id, version, updated_at)\n            ON iam.admin_access_requests TO datariver_app;\n        GRANT SELECT, INSERT ON iam.admin_access_approvals TO datariver_app;\n        GRANT INSERT ON authz.policy_decisions TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON catalog.assets_projection,\n            catalog.sync_runs, catalog.projection_watermarks TO datariver_app;\n        GRANT SELECT, INSERT ON catalog.export_requests TO datariver_app;\n        GRANT SELECT, INSERT ON governance.change_request_items,\n            governance.approvals, governance.state_transitions TO datariver_app;\n        GRANT SELECT, INSERT ON governance.registration_content_bindings TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON governance.change_requests TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON platform.data_systems, platform.system_schema_scopes,\n            platform.system_assignees, platform.external_service_profiles TO datariver_app;\n        GRANT SELECT ON integration.jobs, integration.job_attempts TO datariver_app;\n        GRANT INSERT ON integration.jobs TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON integration.object_manifests TO datariver_app;\n        GRANT SELECT, INSERT ON integration.upload_preparation_jobs TO datariver_app;\n        GRANT SELECT ON integration.upload_preparation_receipts,\n            integration.upload_registration_candidates TO datariver_app;\n        GRANT SELECT, INSERT ON integration.idempotency_keys,\n            integration.outbox_events TO datariver_app;\n        GRANT SELECT ON knowledge.graphs, knowledge.ontology_versions,\n            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,\n            knowledge.changesets, knowledge.change_operations,\n            knowledge.validation_results, knowledge.projection_deployments TO datariver_app;\n        GRANT INSERT ON knowledge.graphs, knowledge.ontology_versions,\n            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,\n            knowledge.changesets, knowledge.change_operations,\n            knowledge.validation_results, knowledge.projection_deployments TO datariver_app;\n        GRANT UPDATE ON knowledge.graphs, knowledge.changesets,\n            knowledge.projection_deployments TO datariver_app;\n        GRANT DELETE ON knowledge.validation_results TO datariver_app;\n        GRANT SELECT, INSERT ON assistant.chat_sessions, assistant.chat_messages,\n            assistant.assistant_runs, assistant.evidence_citations TO datariver_app;\n        GRANT UPDATE (version, updated_at) ON assistant.chat_sessions TO datariver_app;\n        GRANT SELECT, INSERT ON retention.policy_versions TO datariver_app;\n        GRANT UPDATE (state, checker_id, decision_reason,\n            decision_policy_decision_id, decided_at, superseded_by, supersede_reason,\n            supersede_policy_decision_id, superseded_at, version, updated_at)\n            ON retention.policy_versions TO datariver_app;\n        GRANT SELECT, INSERT ON retention.legal_holds TO datariver_app;\n        GRANT UPDATE (state, release_requested_by, release_request_reason,\n            release_request_policy_decision_id, release_checker_id,\n            release_decision_reason, release_decision_policy_decision_id,\n            released_at, version, updated_at)\n            ON retention.legal_holds TO datariver_app;\n        GRANT SELECT, INSERT ON retention.legal_hold_events TO datariver_app;\n        GRANT SELECT, INSERT ON retention.erasure_requests TO datariver_app;\n        GRANT UPDATE (state, checker_id, decision_reason,\n            decision_policy_decision_id, decided_at, version, updated_at)\n            ON retention.erasure_requests TO datariver_app;\n        GRANT SELECT, INSERT ON retention.erasure_request_events TO datariver_app;\n        GRANT SELECT ON retention.archive_capability_attestations,\n            retention.immutable_archive_receipts TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON sharing.api_products,\n            sharing.api_product_versions, sharing.consumer_grants TO datariver_app;\n        GRANT SELECT, INSERT ON sharing.api_invocations TO datariver_app;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_relay') THEN\n        GRANT USAGE ON SCHEMA integration TO datariver_relay;\n        GRANT SELECT, UPDATE ON integration.outbox_events TO datariver_relay;\n        GRANT SELECT ON integration.inbox_messages TO datariver_relay;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_upload') THEN\n        GRANT USAGE ON SCHEMA integration TO datariver_upload;\n        GRANT SELECT, UPDATE ON integration.object_manifests TO datariver_upload;\n        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_upload;\n        GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages TO datariver_upload;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') THEN\n        GRANT USAGE ON SCHEMA authz, governance, integration TO datariver_governance;\n        GRANT SELECT, INSERT ON authz.policy_decisions TO datariver_governance;\n        GRANT SELECT, UPDATE ON governance.change_requests TO datariver_governance;\n        GRANT SELECT ON governance.change_request_items, governance.approvals,\n            governance.state_transitions TO datariver_governance;\n        GRANT INSERT ON governance.state_transitions TO datariver_governance;\n        GRANT SELECT, INSERT, UPDATE ON integration.jobs,\n            integration.job_attempts, integration.inbox_messages TO datariver_governance;\n        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_governance;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_bootstrap') THEN\n        GRANT USAGE ON SCHEMA platform, iam TO datariver_bootstrap;\n        GRANT SELECT, INSERT, UPDATE ON platform.workspaces, iam.subjects,\n            iam.workspace_memberships TO datariver_bootstrap;\n    END IF;\nEND\n$datariver$")


def downgrade() -> None:
        op.execute('DROP FUNCTION iam.resolve_default_workspace(text, text)')
        op.execute('DROP TRIGGER enforce_chat_message_retention_binding ON assistant.chat_messages')
        op.execute('DROP FUNCTION assistant.enforce_chat_message_retention_binding()')
        op.execute('DROP TRIGGER enforce_chat_session_retention_binding ON assistant.chat_sessions')
        op.execute('DROP FUNCTION assistant.enforce_chat_session_retention_binding()')
        op.execute('DROP TRIGGER reject_upload_registration_candidate_evidence_mutation ON integration.upload_registration_candidates')
        op.execute('DROP FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()')
        op.execute('DROP TRIGGER reject_object_manifest_content_profile_change ON integration.object_manifests')
        op.execute('DROP FUNCTION integration.reject_object_manifest_content_profile_change()')
        op.drop_constraint(op.f('fk_graphs_workspace_id_id_active_release_id_releases'), 'graphs', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_changesets_workspace_id_graph_id_published_release_id_releases'), 'changesets', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_changesets_workspace_id_graph_id_base_release_id_releases'), 'changesets', schema='knowledge', type_='foreignkey')
        op.drop_constraint('fk_catalog_export_requests_workspace_job', 'export_requests', schema='catalog', type_='foreignkey')
        op.drop_constraint(op.f('fk_api_products_workspace_id_id_current_version_id_api_product_versions'), 'api_products', schema='sharing', type_='foreignkey')
        op.drop_table('evidence_citations', schema='assistant')
        op.drop_table('api_invocations', schema='sharing')
        op.drop_table('registration_content_bindings', schema='governance')
        op.drop_table('assistant_runs', schema='assistant')
        op.drop_table('consumer_grants', schema='sharing')
        op.drop_table('erasure_request_events', schema='retention')
        op.drop_table('upload_registration_candidates', schema='integration')
        op.drop_table('restricted_search_grant_events', schema='authz')
        op.drop_table('chat_messages', schema='assistant')
        op.drop_table('api_product_versions', schema='sharing')
        op.drop_table('legal_hold_events', schema='retention')
        op.drop_table('immutable_archive_receipts', schema='retention')
        op.drop_table('erasure_requests', schema='retention')
        op.drop_table('validation_results', schema='knowledge')
        op.drop_table('release_nodes', schema='knowledge')
        op.drop_table('release_edges', schema='knowledge')
        op.drop_table('projection_deployments', schema='knowledge')
        op.drop_table('change_operations', schema='knowledge')
        op.drop_table('upload_preparation_receipts', schema='integration')
        op.drop_table('admin_access_approvals', schema='iam')
        op.drop_table('restricted_search_grants', schema='authz')
        op.drop_table('classification_access_policy_rules', schema='authz')
        op.drop_table('chat_sessions', schema='assistant')
        op.drop_table('policy_versions', schema='retention')
        op.drop_table('legal_holds', schema='retention')
        op.drop_table('system_schema_scopes', schema='platform')
        op.drop_table('system_assignees', schema='platform')
        op.drop_table('external_service_profiles', schema='platform')
        op.drop_table('releases', schema='knowledge')
        op.drop_table('changesets', schema='knowledge')
        op.drop_table('upload_preparation_jobs', schema='integration')
        op.drop_table('inference_provider_profile_versions', schema='integration')
        op.drop_table('admin_access_requests', schema='iam')
        op.drop_table('export_requests', schema='catalog')
        op.drop_table('classification_access_policy_versions', schema='authz')
        op.drop_table('api_products', schema='sharing')
        op.drop_table('archive_capability_attestations', schema='retention')
        op.drop_table('data_systems', schema='platform')
        op.drop_table('ontology_versions', schema='knowledge')
        op.drop_table('job_attempts', schema='integration')
        op.drop_table('inference_provider_generations', schema='integration')
        op.drop_table('workspace_memberships', schema='iam')
        op.drop_table('state_transitions', schema='governance')
        op.drop_table('change_request_items', schema='governance')
        op.drop_table('approvals', schema='governance')
        op.drop_table('projection_watermarks', schema='catalog')
        op.drop_table('classification_access_generations', schema='authz')
        op.drop_table('workspaces', schema='platform')
        op.drop_table('graphs', schema='knowledge')
        op.drop_table('seed_runs', schema='integration')
        op.drop_table('outbox_events', schema='integration')
        op.drop_table('object_manifests', schema='integration')
        op.drop_table('jobs', schema='integration')
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
