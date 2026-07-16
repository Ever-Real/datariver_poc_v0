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
        op.create_table('chat_sessions',
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('scope', sa.JSON().with_variant(postgresql.JSONB(none_as_null=True, astext_type=Text()), 'postgresql'), nullable=False),
        sa.Column('retention_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_sessions')),
        sa.UniqueConstraint('workspace_id', 'id', name=op.f('uq_chat_sessions_workspace_id_id')),
        schema='assistant'
        )
        op.create_index('ix_chat_sessions_owner', 'chat_sessions', ['workspace_id', 'owner_id', 'updated_at'], unique=False, schema='assistant')
        op.execute('ALTER TABLE assistant.chat_sessions ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE assistant.chat_sessions FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY workspace_isolation ON assistant.chat_sessions USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")
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
        sa.PrimaryKeyConstraint('id', name=op.f('pk_assets_projection')),
        sa.UniqueConstraint('workspace_id', 'urn_hash', name=op.f('uq_assets_projection_workspace_id_urn_hash')),
        schema='catalog'
        )
        op.create_index('ix_assets_projection_active_scope_order', 'assets_projection', ['workspace_id', 'classification', 'name', 'id'], unique=False, schema='catalog', postgresql_where=sa.text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"))
        op.create_index('ix_assets_projection_name_trgm_active', 'assets_projection', ['name'], unique=False, schema='catalog', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'}, postgresql_where=sa.text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"))
        op.create_index('ix_assets_projection_scope', 'assets_projection', ['workspace_id', 'classification', 'system_id', 'domain_id'], unique=False, schema='catalog')
        op.create_index('ix_assets_projection_search_fts_active', 'assets_projection', ['search_vector'], unique=False, schema='catalog', postgresql_using='gin', postgresql_where=sa.text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"))
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
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
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
        sa.Column('classification', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('retention_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_object_manifests')),
        sa.UniqueConstraint('bucket', 'object_key', name=op.f('uq_object_manifests_bucket_object_key')),
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
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id', 'change_request_id'], ['governance.change_requests.workspace_id', 'governance.change_requests.id'], name=op.f('fk_change_request_items_workspace_id_change_request_id_change_requests'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_change_request_items')),
        sa.UniqueConstraint('change_request_id', 'ordinal', name=op.f('uq_change_request_items_change_request_id_ordinal')),
        schema='governance'
        )
        op.create_index('ix_change_items_request', 'change_request_items', ['change_request_id'], unique=False, schema='governance')
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
        op.create_foreign_key(op.f('fk_api_products_workspace_id_id_current_version_id_api_product_versions'), 'api_products', 'api_product_versions', ['workspace_id', 'id', 'current_version_id'], ['workspace_id', 'product_id', 'id'], source_schema='sharing', referent_schema='sharing', use_alter=True)
        op.create_foreign_key(op.f('fk_changesets_workspace_id_graph_id_base_release_id_releases'), 'changesets', 'releases', ['workspace_id', 'graph_id', 'base_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', use_alter=True)
        op.create_foreign_key(op.f('fk_changesets_workspace_id_graph_id_published_release_id_releases'), 'changesets', 'releases', ['workspace_id', 'graph_id', 'published_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', use_alter=True)
        op.create_foreign_key(op.f('fk_graphs_workspace_id_id_active_release_id_releases'), 'graphs', 'releases', ['workspace_id', 'id', 'active_release_id'], ['workspace_id', 'graph_id', 'id'], source_schema='knowledge', referent_schema='knowledge', use_alter=True)
        op.execute("DO $datariver$\nBEGIN\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN\n        GRANT USAGE ON SCHEMA platform, iam, authz, catalog, governance, integration, knowledge, assistant, sharing, retention TO datariver_app;\n        GRANT USAGE ON SCHEMA public TO datariver_app;\n        GRANT SELECT ON public.alembic_version TO datariver_app;\n        GRANT SELECT ON platform.workspaces, iam.subjects TO datariver_app;\n        GRANT SELECT ON iam.workspace_memberships TO datariver_app;\n        GRANT UPDATE (active, clearance, attributes, version, updated_at)\n            ON iam.workspace_memberships TO datariver_app;\n        GRANT SELECT, INSERT ON iam.admin_access_requests TO datariver_app;\n        GRANT UPDATE (state, checker_id, consumed_by, consumed_at,\n            consume_policy_decision_id, version, updated_at)\n            ON iam.admin_access_requests TO datariver_app;\n        GRANT SELECT, INSERT ON iam.admin_access_approvals TO datariver_app;\n        GRANT INSERT ON authz.policy_decisions TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON catalog.assets_projection,\n            catalog.sync_runs, catalog.projection_watermarks TO datariver_app;\n        GRANT SELECT, INSERT ON governance.change_request_items,\n            governance.approvals, governance.state_transitions TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON governance.change_requests TO datariver_app;\n        GRANT SELECT ON integration.jobs, integration.job_attempts TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON integration.object_manifests TO datariver_app;\n        GRANT SELECT, INSERT ON integration.idempotency_keys,\n            integration.outbox_events TO datariver_app;\n        GRANT SELECT ON knowledge.graphs, knowledge.ontology_versions,\n            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,\n            knowledge.changesets, knowledge.change_operations,\n            knowledge.validation_results, knowledge.projection_deployments TO datariver_app;\n        GRANT INSERT ON knowledge.graphs, knowledge.ontology_versions,\n            knowledge.releases, knowledge.release_nodes, knowledge.release_edges,\n            knowledge.changesets, knowledge.change_operations,\n            knowledge.validation_results, knowledge.projection_deployments TO datariver_app;\n        GRANT UPDATE ON knowledge.graphs, knowledge.changesets,\n            knowledge.projection_deployments TO datariver_app;\n        GRANT DELETE ON knowledge.validation_results TO datariver_app;\n        GRANT SELECT, INSERT ON assistant.chat_sessions, assistant.chat_messages,\n            assistant.assistant_runs, assistant.evidence_citations TO datariver_app;\n        GRANT UPDATE ON assistant.chat_sessions TO datariver_app;\n        GRANT SELECT, INSERT ON retention.policy_versions TO datariver_app;\n        GRANT UPDATE (state, checker_id, decision_reason,\n            decision_policy_decision_id, decided_at, superseded_by, supersede_reason,\n            supersede_policy_decision_id, superseded_at, version, updated_at)\n            ON retention.policy_versions TO datariver_app;\n        GRANT SELECT, INSERT ON retention.legal_holds TO datariver_app;\n        GRANT UPDATE (state, release_requested_by, release_request_reason,\n            release_request_policy_decision_id, release_checker_id,\n            release_decision_reason, release_decision_policy_decision_id,\n            released_at, version, updated_at)\n            ON retention.legal_holds TO datariver_app;\n        GRANT SELECT, INSERT ON retention.legal_hold_events TO datariver_app;\n        GRANT SELECT, INSERT ON retention.erasure_requests TO datariver_app;\n        GRANT UPDATE (state, checker_id, decision_reason,\n            decision_policy_decision_id, decided_at, version, updated_at)\n            ON retention.erasure_requests TO datariver_app;\n        GRANT SELECT, INSERT ON retention.erasure_request_events TO datariver_app;\n        GRANT SELECT, INSERT, UPDATE ON sharing.api_products,\n            sharing.api_product_versions, sharing.consumer_grants TO datariver_app;\n        GRANT SELECT, INSERT ON sharing.api_invocations TO datariver_app;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_relay') THEN\n        GRANT USAGE ON SCHEMA integration TO datariver_relay;\n        GRANT SELECT, UPDATE ON integration.outbox_events TO datariver_relay;\n        GRANT SELECT ON integration.inbox_messages TO datariver_relay;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_upload') THEN\n        GRANT USAGE ON SCHEMA integration TO datariver_upload;\n        GRANT SELECT, UPDATE ON integration.object_manifests TO datariver_upload;\n        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_upload;\n        GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages TO datariver_upload;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_governance') THEN\n        GRANT USAGE ON SCHEMA authz, governance, integration TO datariver_governance;\n        GRANT SELECT, INSERT ON authz.policy_decisions TO datariver_governance;\n        GRANT SELECT, UPDATE ON governance.change_requests TO datariver_governance;\n        GRANT SELECT ON governance.change_request_items, governance.approvals,\n            governance.state_transitions TO datariver_governance;\n        GRANT INSERT ON governance.state_transitions TO datariver_governance;\n        GRANT SELECT, INSERT, UPDATE ON integration.jobs,\n            integration.job_attempts, integration.inbox_messages TO datariver_governance;\n        GRANT SELECT, INSERT ON integration.outbox_events TO datariver_governance;\n    END IF;\n\n    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_bootstrap') THEN\n        GRANT USAGE ON SCHEMA platform, iam TO datariver_bootstrap;\n        GRANT SELECT, INSERT, UPDATE ON platform.workspaces, iam.subjects,\n            iam.workspace_memberships TO datariver_bootstrap;\n    END IF;\nEND\n$datariver$")


def downgrade() -> None:
        op.drop_constraint(op.f('fk_graphs_workspace_id_id_active_release_id_releases'), 'graphs', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_changesets_workspace_id_graph_id_published_release_id_releases'), 'changesets', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_changesets_workspace_id_graph_id_base_release_id_releases'), 'changesets', schema='knowledge', type_='foreignkey')
        op.drop_constraint(op.f('fk_api_products_workspace_id_id_current_version_id_api_product_versions'), 'api_products', schema='sharing', type_='foreignkey')
        op.drop_table('api_invocations', schema='sharing')
        op.drop_table('consumer_grants', schema='sharing')
        op.drop_table('erasure_request_events', schema='retention')
        op.drop_table('api_product_versions', schema='sharing')
        op.drop_table('legal_hold_events', schema='retention')
        op.drop_table('erasure_requests', schema='retention')
        op.drop_table('validation_results', schema='knowledge')
        op.drop_table('release_nodes', schema='knowledge')
        op.drop_table('release_edges', schema='knowledge')
        op.drop_table('projection_deployments', schema='knowledge')
        op.drop_table('change_operations', schema='knowledge')
        op.drop_table('admin_access_approvals', schema='iam')
        op.drop_table('evidence_citations', schema='assistant')
        op.drop_table('policy_versions', schema='retention')
        op.drop_table('legal_holds', schema='retention')
        op.drop_table('releases', schema='knowledge')
        op.drop_table('changesets', schema='knowledge')
        op.drop_table('admin_access_requests', schema='iam')
        op.drop_table('assistant_runs', schema='assistant')
        op.drop_table('api_products', schema='sharing')
        op.drop_table('ontology_versions', schema='knowledge')
        op.drop_table('job_attempts', schema='integration')
        op.drop_table('workspace_memberships', schema='iam')
        op.drop_table('state_transitions', schema='governance')
        op.drop_table('change_request_items', schema='governance')
        op.drop_table('approvals', schema='governance')
        op.drop_table('projection_watermarks', schema='catalog')
        op.drop_table('chat_messages', schema='assistant')
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
        op.drop_table('chat_sessions', schema='assistant')
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
