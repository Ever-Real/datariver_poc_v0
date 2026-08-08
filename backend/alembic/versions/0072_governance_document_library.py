"""Add immutable Governance Document library, approval and projection evidence.

Revision ID: 0072
Revises: 0071
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0072"
down_revision: str | Sequence[str] | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BOUNDARY = "-- datariver-statement-boundary"

_ROLE_ASSERTION_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'datariver_app'
          AND rolcanlogin IS TRUE
          AND rolsuper IS FALSE
          AND rolcreatedb IS FALSE
          AND rolcreaterole IS FALSE
          AND rolreplication IS FALSE
          AND rolbypassrls IS FALSE
    ) THEN
        RAISE EXCEPTION 'required role datariver_app is missing';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = 'datariver_governance_document'
          AND rolcanlogin IS TRUE
          AND rolsuper IS FALSE
          AND rolcreatedb IS FALSE
          AND rolcreaterole IS FALSE
          AND rolreplication IS FALSE
          AND rolbypassrls IS FALSE
    ) THEN
        RAISE EXCEPTION
            'datariver_governance_document must be a safe NOBYPASSRLS login role';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members AS membership
        JOIN pg_roles AS member_role ON member_role.oid = membership.member
        JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
        WHERE member_role.rolname = 'datariver_governance_document'
           OR (
               granted_role.rolname = 'datariver_governance_document'
               AND member_role.rolname NOT IN (
                   current_user, session_user, 'datariver_migrator'
               )
           )
    ) THEN
        RAISE EXCEPTION 'datariver_governance_document role membership is unsafe';
    END IF;
END
$$
"""

_SECURITY_SQL = r"""
CREATE OR REPLACE FUNCTION governance.current_human_can_document_v1(
    p_workspace_id uuid,
    p_action text,
    p_classification integer,
    p_system_id uuid,
    p_domain_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, platform, iam
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM platform.workspaces AS workspace
        JOIN iam.workspace_memberships AS membership
          ON membership.workspace_id = workspace.id
        JOIN iam.subjects AS subject
          ON subject.id = membership.subject_id
        WHERE workspace.id = p_workspace_id
          AND workspace.status = 'ACTIVE'
          AND membership.subject_id =
              NULLIF(current_setting('app.subject_id', true), '')::uuid
          AND subject.active IS TRUE
          AND membership.active IS TRUE
          AND (
              membership.access_expires_at IS NULL
              OR membership.access_expires_at > transaction_timestamp()
          )
          AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT'
          AND NOT (
              COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
              ? 'service-accounts'
          )
          AND membership.clearance >= p_classification
          AND (
              p_system_id IS NULL
              OR p_classification = 0
              OR COALESCE(
                  membership.attributes -> 'allowed_system_ids',
                  '[]'::jsonb
              ) ? p_system_id::text
          )
          AND (
              p_domain_id IS NULL
              OR p_classification = 0
              OR COALESCE(
                  membership.attributes -> 'allowed_domain_ids',
                  '[]'::jsonb
              ) ? p_domain_id::text
          )
          AND COALESCE(
              membership.attributes -> 'allowed_actions',
              '[]'::jsonb
          ) ? p_action
          AND NOT (
              COALESCE(
                  membership.attributes -> 'denied_actions',
                  '[]'::jsonb
              ) ? p_action
          )
    )
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION governance.current_human_can_document_v1(
    uuid, text, integer, uuid, uuid
) FROM PUBLIC;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION governance.current_human_can_document_v1(
    uuid, text, integer, uuid, uuid
) TO datariver_app;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION governance.can_read_document_v1(p_document_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, governance
AS $$
    SELECT governance.current_human_can_document_v1(
        document.workspace_id,
        CASE
            WHEN document.kind = 'TEMPLATE' THEN 'governance.template.read'
            WHEN document.state = 'ARCHIVED' THEN 'governance.document.history.read'
            ELSE 'governance.document.read'
        END,
        document.classification,
        document.system_id,
        document.domain_id
    )
    FROM governance.documents AS document
    WHERE document.id = p_document_id
      AND document.workspace_id =
          NULLIF(current_setting('app.workspace_id', true), '')::uuid
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION governance.can_read_document_v1(uuid) FROM PUBLIC;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION governance.can_read_document_v1(uuid) TO datariver_app;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION governance.can_act_on_document_v1(
    p_document_id uuid,
    p_document_action text,
    p_template_action text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, governance
AS $$
    SELECT governance.current_human_can_document_v1(
        document.workspace_id,
        CASE WHEN document.kind = 'TEMPLATE'
             THEN p_template_action ELSE p_document_action END,
        document.classification,
        document.system_id,
        document.domain_id
    )
    FROM governance.documents AS document
    WHERE document.id = p_document_id
      AND document.workspace_id =
          NULLIF(current_setting('app.workspace_id', true), '')::uuid
$$;
-- datariver-statement-boundary
REVOKE ALL ON FUNCTION governance.can_act_on_document_v1(
    uuid, text, text
) FROM PUBLIC;
-- datariver-statement-boundary
GRANT EXECUTE ON FUNCTION governance.can_act_on_document_v1(
    uuid, text, text
) TO datariver_app;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION governance.reject_document_evidence_mutation_v1()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Governance Document evidence is immutable'
        USING ERRCODE = '55000';
END
$$;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION governance.enforce_document_mutation_v1()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    required_action text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Governance Documents are logically archived, never deleted'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.category IS DISTINCT FROM OLD.category
       OR NEW.classification IS DISTINCT FROM OLD.classification
       OR NEW.owner_subject_id IS DISTINCT FROM OLD.owner_subject_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Governance Document identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.state = 'ARCHIVED' AND OLD.state <> 'ARCHIVED' THEN
        required_action := CASE WHEN NEW.kind = 'TEMPLATE'
            THEN 'governance.template.archive'
            ELSE 'governance.document.archive' END;
    ELSIF NEW.current_published_version_id IS DISTINCT FROM
          OLD.current_published_version_id THEN
        required_action := CASE WHEN NEW.kind = 'TEMPLATE'
            THEN 'governance.template.activate'
            ELSE 'governance.document.publish' END;
    ELSE
        required_action := CASE WHEN NEW.kind = 'TEMPLATE'
            THEN 'governance.template.propose'
            ELSE 'governance.document.edit' END;
    END IF;
    IF NOT governance.current_human_can_document_v1(
        NEW.workspace_id,
        required_action,
        NEW.classification,
        NEW.system_id,
        NEW.domain_id
    ) AND NOT (
        required_action = 'governance.document.edit'
        AND governance.current_human_can_document_v1(
            NEW.workspace_id,
            'governance.document.review',
            NEW.classification,
            NEW.system_id,
            NEW.domain_id
        )
    ) AND NOT (
        required_action = 'governance.template.propose'
        AND governance.current_human_can_document_v1(
            NEW.workspace_id,
            'governance.template.review',
            NEW.classification,
            NEW.system_id,
            NEW.domain_id
        )
    ) THEN
        RAISE EXCEPTION 'Governance Document transition is not authorized'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.state = 'ARCHIVED' AND (
        NEW.archived_at IS NULL OR NEW.archived_by IS DISTINCT FROM
        NULLIF(current_setting('app.subject_id', true), '')::uuid
    ) THEN
        RAISE EXCEPTION 'Governance Document archive evidence is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary

CREATE OR REPLACE FUNCTION governance.enforce_document_version_mutation_v1()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    parent governance.documents%ROWTYPE;
    required_action text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Governance Document versions are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.document_id IS DISTINCT FROM OLD.document_id
       OR NEW.version_number IS DISTINCT FROM OLD.version_number
       OR NEW.version_tag IS DISTINCT FROM OLD.version_tag
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.summary IS DISTINCT FROM OLD.summary
       OR NEW.applicability_scope IS DISTINCT FROM OLD.applicability_scope
       OR NEW.sanitized_html IS DISTINCT FROM OLD.sanitized_html
       OR NEW.plain_text IS DISTINCT FROM OLD.plain_text
       OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
       OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
       OR NEW.sanitizer_policy_version IS DISTINCT FROM OLD.sanitizer_policy_version
       OR NEW.sanitizer_policy_sha256 IS DISTINCT FROM OLD.sanitizer_policy_sha256
       OR NEW.source_format IS DISTINCT FROM OLD.source_format
       OR NEW.source_template_version_id IS DISTINCT FROM OLD.source_template_version_id
       OR NEW.author_id IS DISTINCT FROM OLD.author_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Governance Document version content is immutable'
            USING ERRCODE = '55000';
    END IF;
    SELECT * INTO parent
    FROM governance.documents
    WHERE workspace_id = NEW.workspace_id AND id = NEW.document_id;
    IF current_user = 'datariver_governance_document' THEN
        IF NEW.state IS DISTINCT FROM OLD.state
           OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at
           OR NEW.reviewed_by IS DISTINCT FROM OLD.reviewed_by
           OR NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at
           OR NEW.published_at IS DISTINCT FROM OLD.published_at THEN
            RAISE EXCEPTION 'Projection worker cannot change publication state'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.artifact_state IS DISTINCT FROM OLD.artifact_state
       OR NEW.knowledge_state IS DISTINCT FROM OLD.knowledge_state
       OR NEW.projection_attempts IS DISTINCT FROM OLD.projection_attempts
       OR NEW.next_attempt_at IS DISTINCT FROM OLD.next_attempt_at
       OR NEW.lease_owner IS DISTINCT FROM OLD.lease_owner
       OR NEW.lease_until IS DISTINCT FROM OLD.lease_until
       OR NEW.failure_code IS DISTINCT FROM OLD.failure_code THEN
        RAISE EXCEPTION 'Human commands cannot mutate projection evidence'
            USING ERRCODE = '42501';
    END IF;
    IF OLD.state = 'DRAFT' AND NEW.state = 'IN_REVIEW'
       AND NEW.author_id =
           NULLIF(current_setting('app.subject_id', true), '')::uuid THEN
        required_action := CASE WHEN parent.kind = 'TEMPLATE'
            THEN 'governance.template.propose'
            ELSE 'governance.document.edit' END;
    ELSIF OLD.state = 'IN_REVIEW' AND NEW.state = 'REJECTED'
       AND NEW.reviewed_by =
           NULLIF(current_setting('app.subject_id', true), '')::uuid
       AND NEW.reviewed_by <> NEW.author_id THEN
        required_action := CASE WHEN parent.kind = 'TEMPLATE'
            THEN 'governance.template.review'
            ELSE 'governance.document.review' END;
    ELSIF OLD.state = 'IN_REVIEW' AND NEW.state = 'PUBLISHED'
       AND NEW.reviewed_by =
           NULLIF(current_setting('app.subject_id', true), '')::uuid
       AND NEW.reviewed_by <> NEW.author_id THEN
        required_action := CASE WHEN parent.kind = 'TEMPLATE'
            THEN 'governance.template.activate'
            ELSE 'governance.document.publish' END;
    ELSIF OLD.state = 'PUBLISHED' AND NEW.state = 'SUPERSEDED' THEN
        required_action := CASE WHEN parent.kind = 'TEMPLATE'
            THEN 'governance.template.activate'
            ELSE 'governance.document.publish' END;
    ELSIF NEW.state IS NOT DISTINCT FROM OLD.state THEN
        required_action := CASE WHEN parent.kind = 'TEMPLATE'
            THEN 'governance.template.propose'
            ELSE 'governance.document.edit' END;
    ELSE
        RAISE EXCEPTION 'Governance Document version transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    IF NOT governance.current_human_can_document_v1(
        NEW.workspace_id,
        required_action,
        parent.classification,
        parent.system_id,
        parent.domain_id
    ) THEN
        RAISE EXCEPTION 'Governance Document version transition is not authorized'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END
$$;
-- datariver-statement-boundary

CREATE TRIGGER enforce_document_mutation
BEFORE UPDATE OR DELETE ON governance.documents
FOR EACH ROW EXECUTE FUNCTION governance.enforce_document_mutation_v1();
-- datariver-statement-boundary
CREATE TRIGGER enforce_document_version_mutation
BEFORE UPDATE OR DELETE ON governance.document_versions
FOR EACH ROW EXECUTE FUNCTION governance.enforce_document_version_mutation_v1();
-- datariver-statement-boundary
CREATE TRIGGER reject_document_review_mutation
BEFORE UPDATE OR DELETE ON governance.document_reviews
FOR EACH ROW EXECUTE FUNCTION governance.reject_document_evidence_mutation_v1();
-- datariver-statement-boundary
CREATE TRIGGER reject_document_event_mutation
BEFORE UPDATE OR DELETE ON governance.document_events
FOR EACH ROW EXECUTE FUNCTION governance.reject_document_evidence_mutation_v1();
-- datariver-statement-boundary
CREATE TRIGGER reject_document_artifact_receipt_mutation
BEFORE UPDATE OR DELETE ON governance.document_artifact_receipts
FOR EACH ROW EXECUTE FUNCTION governance.reject_document_evidence_mutation_v1();
-- datariver-statement-boundary
CREATE TRIGGER reject_document_attachment_mutation
BEFORE UPDATE OR DELETE ON governance.document_attachments
FOR EACH ROW EXECUTE FUNCTION governance.reject_document_evidence_mutation_v1();
-- datariver-statement-boundary
CREATE TRIGGER reject_document_chunk_mutation
BEFORE UPDATE OR DELETE ON governance.document_knowledge_chunks
FOR EACH ROW EXECUTE FUNCTION governance.reject_document_evidence_mutation_v1();
-- datariver-statement-boundary
CREATE TRIGGER reject_document_projection_receipt_mutation
BEFORE UPDATE OR DELETE ON governance.document_projection_receipts
FOR EACH ROW EXECUTE FUNCTION governance.reject_document_evidence_mutation_v1();
-- datariver-statement-boundary

ALTER TABLE governance.documents ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.documents FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_versions ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_versions FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_reviews ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_reviews FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_events ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_events FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_artifact_receipts ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_artifact_receipts FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_attachments ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_attachments FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_knowledge_chunks ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_knowledge_chunks FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_projection_receipts ENABLE ROW LEVEL SECURITY;
-- datariver-statement-boundary
ALTER TABLE governance.document_projection_receipts FORCE ROW LEVEL SECURITY;
-- datariver-statement-boundary

CREATE POLICY governance_documents_app_select ON governance.documents
FOR SELECT TO datariver_app
USING (governance.can_read_document_v1(id));
-- datariver-statement-boundary
CREATE POLICY governance_documents_app_insert ON governance.documents
FOR INSERT TO datariver_app
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND owner_subject_id = NULLIF(current_setting('app.subject_id', true), '')::uuid
    AND governance.current_human_can_document_v1(
        workspace_id,
        CASE WHEN kind = 'TEMPLATE' THEN 'governance.template.propose'
             ELSE 'governance.document.create' END,
        classification, system_id, domain_id
    )
);
-- datariver-statement-boundary
CREATE POLICY governance_documents_app_update ON governance.documents
FOR UPDATE TO datariver_app
USING (governance.can_read_document_v1(id))
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
);
-- datariver-statement-boundary

CREATE POLICY governance_document_versions_app_select ON governance.document_versions
FOR SELECT TO datariver_app
USING (governance.can_read_document_v1(document_id));
-- datariver-statement-boundary
CREATE POLICY governance_document_versions_app_insert ON governance.document_versions
FOR INSERT TO datariver_app
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND author_id = NULLIF(current_setting('app.subject_id', true), '')::uuid
    AND governance.can_act_on_document_v1(
        document_id, 'governance.document.edit', 'governance.template.propose'
    )
);
-- datariver-statement-boundary
CREATE POLICY governance_document_versions_app_update ON governance.document_versions
FOR UPDATE TO datariver_app
USING (governance.can_read_document_v1(document_id))
WITH CHECK (governance.can_read_document_v1(document_id));
-- datariver-statement-boundary

CREATE POLICY governance_document_reviews_app_select ON governance.document_reviews
FOR SELECT TO datariver_app
USING (governance.can_read_document_v1(document_id));
-- datariver-statement-boundary
CREATE POLICY governance_document_reviews_app_insert ON governance.document_reviews
FOR INSERT TO datariver_app
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND reviewer_id = NULLIF(current_setting('app.subject_id', true), '')::uuid
    AND governance.can_act_on_document_v1(
        document_id, 'governance.document.review', 'governance.template.review'
    )
);
-- datariver-statement-boundary
CREATE POLICY governance_document_events_app_select ON governance.document_events
FOR SELECT TO datariver_app
USING (governance.can_read_document_v1(document_id));
-- datariver-statement-boundary
CREATE POLICY governance_document_events_app_insert ON governance.document_events
FOR INSERT TO datariver_app
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND actor_id = NULLIF(current_setting('app.subject_id', true), '')::uuid
    AND governance.can_act_on_document_v1(
        document_id,
        CASE event_type
            WHEN 'CREATED' THEN 'governance.document.create'
            WHEN 'VERSION_CREATED' THEN 'governance.document.edit'
            WHEN 'SUBMITTED' THEN 'governance.document.edit'
            WHEN 'REJECTED' THEN 'governance.document.review'
            WHEN 'PUBLISHED' THEN 'governance.document.publish'
            WHEN 'ARCHIVED' THEN 'governance.document.archive'
            WHEN 'ATTACHMENT_ADDED' THEN 'governance.document.edit'
            ELSE 'governance.document.__denied__'
        END,
        CASE event_type
            WHEN 'CREATED' THEN 'governance.template.propose'
            WHEN 'VERSION_CREATED' THEN 'governance.template.propose'
            WHEN 'SUBMITTED' THEN 'governance.template.propose'
            WHEN 'REJECTED' THEN 'governance.template.review'
            WHEN 'PUBLISHED' THEN 'governance.template.activate'
            WHEN 'ARCHIVED' THEN 'governance.template.archive'
            WHEN 'ATTACHMENT_ADDED' THEN 'governance.template.propose'
            ELSE 'governance.template.__denied__'
        END
    )
);
-- datariver-statement-boundary
CREATE POLICY governance_document_attachments_app_select ON governance.document_attachments
FOR SELECT TO datariver_app
USING (governance.can_read_document_v1(document_id));
-- datariver-statement-boundary
CREATE POLICY governance_document_attachments_app_insert ON governance.document_attachments
FOR INSERT TO datariver_app
WITH CHECK (
    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    AND uploaded_by = NULLIF(current_setting('app.subject_id', true), '')::uuid
    AND governance.can_act_on_document_v1(
        document_id, 'governance.document.edit', 'governance.template.propose'
    )
);
-- datariver-statement-boundary
CREATE POLICY governance_document_chunks_app_select ON governance.document_knowledge_chunks
FOR SELECT TO datariver_app
USING (governance.can_read_document_v1(document_id));
-- datariver-statement-boundary

CREATE POLICY governance_documents_worker_select ON governance.documents
FOR SELECT TO datariver_governance_document USING (true);
-- datariver-statement-boundary
CREATE POLICY governance_versions_worker_select ON governance.document_versions
FOR SELECT TO datariver_governance_document USING (true);
-- datariver-statement-boundary
CREATE POLICY governance_versions_worker_update ON governance.document_versions
FOR UPDATE TO datariver_governance_document USING (true) WITH CHECK (true);
-- datariver-statement-boundary
CREATE POLICY governance_artifacts_worker_all ON governance.document_artifact_receipts
FOR ALL TO datariver_governance_document USING (true) WITH CHECK (true);
-- datariver-statement-boundary
CREATE POLICY governance_chunks_worker_all ON governance.document_knowledge_chunks
FOR ALL TO datariver_governance_document USING (true) WITH CHECK (true);
-- datariver-statement-boundary
CREATE POLICY governance_projection_receipts_worker_all
ON governance.document_projection_receipts
FOR ALL TO datariver_governance_document USING (true) WITH CHECK (true);
-- datariver-statement-boundary

REVOKE ALL ON ALL TABLES IN SCHEMA governance
FROM datariver_governance_document;
-- datariver-statement-boundary
GRANT USAGE ON SCHEMA governance TO datariver_app, datariver_governance_document;
-- datariver-statement-boundary
GRANT SELECT, INSERT, UPDATE ON governance.documents TO datariver_app;
-- datariver-statement-boundary
GRANT SELECT, INSERT, UPDATE ON governance.document_versions TO datariver_app;
-- datariver-statement-boundary
GRANT SELECT, INSERT ON governance.document_reviews TO datariver_app;
-- datariver-statement-boundary
GRANT SELECT, INSERT ON governance.document_events TO datariver_app;
-- datariver-statement-boundary
GRANT SELECT ON governance.document_artifact_receipts TO datariver_app;
-- datariver-statement-boundary
GRANT SELECT, INSERT ON governance.document_attachments TO datariver_app;
-- datariver-statement-boundary
GRANT SELECT ON governance.document_knowledge_chunks TO datariver_app;
-- datariver-statement-boundary
GRANT SELECT ON governance.document_projection_receipts TO datariver_app;
-- datariver-statement-boundary
GRANT SELECT ON governance.documents TO datariver_governance_document;
-- datariver-statement-boundary
GRANT SELECT ON governance.document_versions TO datariver_governance_document;
-- datariver-statement-boundary
GRANT UPDATE (
    artifact_state,
    knowledge_state,
    projection_attempts,
    next_attempt_at,
    lease_owner,
    lease_until,
    failure_code,
    version
) ON governance.document_versions TO datariver_governance_document;
-- datariver-statement-boundary
GRANT SELECT, INSERT ON governance.document_artifact_receipts
TO datariver_governance_document;
-- datariver-statement-boundary
GRANT SELECT, INSERT ON governance.document_knowledge_chunks
TO datariver_governance_document;
-- datariver-statement-boundary
GRANT SELECT, INSERT ON governance.document_projection_receipts
TO datariver_governance_document;
"""

_DOWNGRADE_GUARD_SQL = """
DO $$
DECLARE
    populated boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM governance.documents
        UNION ALL SELECT 1 FROM governance.document_versions
        UNION ALL SELECT 1 FROM governance.document_reviews
        UNION ALL SELECT 1 FROM governance.document_events
        UNION ALL SELECT 1 FROM governance.document_artifact_receipts
        UNION ALL SELECT 1 FROM governance.document_attachments
        UNION ALL SELECT 1 FROM governance.document_knowledge_chunks
        UNION ALL SELECT 1 FROM governance.document_projection_receipts
    ) INTO populated;
    IF populated THEN
        RAISE EXCEPTION '0072 downgrade refused: Governance Document evidence exists';
    END IF;
END
$$
"""


def _statements(value: str) -> tuple[str, ...]:
    return tuple(statement.strip() for statement in value.split(_BOUNDARY) if statement.strip())


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("document_folders", schema="governance"): return
    _create_tables()
    op.execute(_ROLE_ASSERTION_SQL)
    for statement in _statements(_SECURITY_SQL):
        op.execute(statement)


def downgrade() -> None:
    op.execute(_DOWNGRADE_GUARD_SQL)
    op.execute(
        "DROP FUNCTION governance.can_read_document_v1(uuid), "
        "governance.can_act_on_document_v1(uuid,text,text), "
        "governance.current_human_can_document_v1(uuid,text,integer,uuid,uuid), "
        "governance.enforce_document_mutation_v1(), "
        "governance.enforce_document_version_mutation_v1(), "
        "governance.reject_document_evidence_mutation_v1() CASCADE"
    )
    for table_name in (
        "document_projection_receipts",
        "document_knowledge_chunks",
        "document_attachments",
        "document_artifact_receipts",
        "document_events",
        "document_reviews",
        "document_versions",
        "documents",
    ):
        op.drop_table(table_name, schema="governance")


def _create_tables() -> None:
    op.create_table(
        "documents",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("classification", sa.Integer(), nullable=False),
        sa.Column("owner_subject_id", sa.Uuid(), nullable=False),
        sa.Column("owner_department_id", sa.Uuid(), nullable=True),
        sa.Column("system_id", sa.Uuid(), nullable=True),
        sa.Column("domain_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("current_published_version_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.Uuid(), nullable=True),
        sa.Column("archived_reason", sa.String(length=2_000), nullable=True),
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
            "(state = 'DRAFT' AND current_published_version_id IS NULL "
            "AND archived_at IS NULL AND archived_by IS NULL AND archived_reason IS NULL) "
            "OR (state = 'ACTIVE' AND current_published_version_id IS NOT NULL "
            "AND archived_at IS NULL AND archived_by IS NULL AND archived_reason IS NULL) "
            "OR (state = 'ARCHIVED' AND archived_at IS NOT NULL "
            "AND archived_by IS NOT NULL AND archived_reason IS NOT NULL)",
            name=op.f("ck_documents_lifecycle_shape"),
        ),
        sa.CheckConstraint(
            "category IN ('POLICY','STANDARD_TERMINOLOGY','SECURITY_GUIDE','OTHER')",
            name=op.f("ck_documents_category_vocabulary"),
        ),
        sa.CheckConstraint(
            "kind IN ('DOCUMENT','TEMPLATE')",
            name=op.f("ck_documents_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','ACTIVE','ARCHIVED')",
            name=op.f("ck_documents_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "char_length(summary) <= 2000",
            name=op.f("ck_documents_summary_length"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 500",
            name=op.f("ck_documents_title_length"),
        ),
        sa.CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name=op.f("ck_documents_classification_range"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "archived_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_governance_documents_archiver",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "current_published_version_id"],
            ["governance.document_versions.workspace_id", "governance.document_versions.id"],
            name="fk_governance_documents_current_version",
            ondelete="RESTRICT",
            initially="DEFERRED",
            deferrable=True,
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "owner_subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_governance_documents_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_governance_documents_workspace_id",
        ),
        schema="governance",
    )
    op.create_index("ix_governance_documents_title",
        "documents",
        ["workspace_id", sa.literal_column("lower(title)"), "id"],
        schema="governance",
     if_not_exists=True)
    op.create_index("ix_governance_documents_list",
        "documents",
        [
            "workspace_id",
            "kind",
            "state",
            sa.literal_column("updated_at DESC"),
            sa.literal_column("id DESC"),
        ],
        schema="governance",
     if_not_exists=True)
    _create_version_table()
    op.create_foreign_key(
        "fk_governance_document_versions_template",
        "document_versions",
        "document_versions",
        ["workspace_id", "source_template_version_id"],
        ["workspace_id", "id"],
        source_schema="governance",
        referent_schema="governance",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_governance_documents_current_version",
        "documents",
        "document_versions",
        ["workspace_id", "current_published_version_id"],
        ["workspace_id", "id"],
        source_schema="governance",
        referent_schema="governance",
        ondelete="RESTRICT",
        initially="DEFERRED",
        deferrable=True,
    )
    _create_evidence_tables()


def _create_version_table() -> None:
    op.create_table(
        "document_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_tag", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("applicability_scope", sa.Text(), nullable=False),
        sa.Column("sanitized_html", sa.Text(), nullable=False),
        sa.Column("plain_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sanitizer_policy_version", sa.String(length=100), nullable=False),
        sa.Column("sanitizer_policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_format", sa.String(length=16), nullable=False),
        sa.Column("source_template_version_id", sa.Uuid(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_state", sa.String(length=16), nullable=False),
        sa.Column("knowledge_state", sa.String(length=16), nullable=False),
        sa.Column("projection_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(state = 'DRAFT' AND submitted_at IS NULL AND reviewed_by IS NULL "
            "AND reviewed_at IS NULL AND published_at IS NULL) OR "
            "(state = 'IN_REVIEW' AND submitted_at IS NOT NULL AND reviewed_by IS NULL "
            "AND reviewed_at IS NULL AND published_at IS NULL) OR "
            "(state = 'REJECTED' AND submitted_at IS NOT NULL AND reviewed_by IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND published_at IS NULL) OR "
            "(state IN ('PUBLISHED','SUPERSEDED') AND submitted_at IS NOT NULL "
            "AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND published_at IS NOT NULL)",
            name=op.f("ck_document_versions_lifecycle_shape"),
        ),
        sa.CheckConstraint(
            "artifact_state IN ('PENDING','STORED','FAILED')",
            name=op.f("ck_document_versions_artifact_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_versions_content_sha256_valid"),
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR (artifact_state = 'FAILED' OR knowledge_state = 'FAILED')",
            name=op.f("ck_document_versions_failure_code_shape"),
        ),
        sa.CheckConstraint(
            "knowledge_state IN ('PENDING','PROJECTING','READY','FAILED')",
            name=op.f("ck_document_versions_knowledge_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "sanitizer_policy_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_versions_sanitizer_policy_sha256_valid"),
        ),
        sa.CheckConstraint(
            "source_format IN ('HTML','MARKDOWN','DOCX')",
            name=op.f("ck_document_versions_source_format_vocabulary"),
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT','IN_REVIEW','PUBLISHED','REJECTED','SUPERSEDED')",
            name=op.f("ck_document_versions_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "version_tag ~ '^v[1-9][0-9]{0,8}$'",
            name=op.f("ck_document_versions_version_tag_valid"),
        ),
        sa.CheckConstraint(
            "char_length(applicability_scope) <= 4000",
            name=op.f("ck_document_versions_applicability_scope_length"),
        ),
        sa.CheckConstraint(
            "char_length(summary) <= 2000",
            name=op.f("ck_document_versions_summary_length"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 500",
            name=op.f("ck_document_versions_title_length"),
        ),
        sa.CheckConstraint(
            "reviewed_by IS NULL OR reviewed_by <> author_id",
            name=op.f("ck_document_versions_maker_checker_distinct"),
        ),
        sa.CheckConstraint(
            "size_bytes BETWEEN 1 AND 1048576",
            name=op.f("ck_document_versions_size_bytes_range"),
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name=op.f("ck_document_versions_version_number_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "author_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_governance_document_versions_author",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["governance.documents.workspace_id", "governance.documents.id"],
            name="fk_governance_document_versions_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "reviewed_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_governance_document_versions_reviewer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_template_version_id"],
            ["governance.document_versions.workspace_id", "governance.document_versions.id"],
            name="fk_governance_document_versions_template",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "workspace_id",
            "document_id",
            "version_number",
            name="uq_governance_document_versions_number",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "document_id",
            "version_tag",
            name="uq_governance_document_versions_tag",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_governance_document_versions_workspace_id",
        ),
        schema="governance",
    )
    op.create_index("ix_governance_document_versions_projection",
        "document_versions",
        ["knowledge_state", "next_attempt_at", "lease_until", "id"],
        schema="governance",
        postgresql_where=sa.text("state = 'PUBLISHED' AND knowledge_state IN ('PENDING','FAILED')"),
     if_not_exists=True)
    op.create_index("uq_governance_document_versions_live_candidate",
        "document_versions",
        ["workspace_id", "document_id"],
        unique=True,
        schema="governance",
        postgresql_where=sa.text("state IN ('DRAFT','IN_REVIEW')"),
     if_not_exists=True)
    op.create_index("ix_governance_document_versions_history",
        "document_versions",
        [
            "workspace_id",
            "document_id",
            sa.literal_column("version_number DESC"),
            sa.literal_column("id DESC"),
        ],
        schema="governance",
     if_not_exists=True)


def _create_evidence_tables() -> None:
    _create_review_and_event_tables()
    _create_artifact_and_attachment_tables()
    _create_projection_tables()


def _create_review_and_event_tables() -> None:
    op.create_table(
        "document_reviews",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=2_000), nullable=False),
        sa.Column("policy_decision_id", sa.Uuid(), nullable=False),
        sa.Column("authentication_assurance", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('APPROVE','REJECT')",
            name=op.f("ck_document_reviews_decision_vocabulary"),
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 2000",
            name=op.f("ck_document_reviews_reason_length"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["governance.documents.workspace_id", "governance.documents.id"],
            name="fk_governance_document_reviews_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["governance.document_versions.workspace_id", "governance.document_versions.id"],
            name="fk_governance_document_reviews_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "reviewer_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_governance_document_reviews_reviewer",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_reviews")),
        sa.UniqueConstraint(
            "workspace_id",
            "document_version_id",
            name="uq_governance_document_reviews_version",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_governance_document_reviews_workspace_id",
        ),
        schema="governance",
    )
    op.create_index("ix_governance_document_reviews_history",
        "document_reviews",
        [
            "workspace_id",
            "document_id",
            sa.literal_column("created_at DESC"),
            sa.literal_column("id DESC"),
        ],
        schema="governance",
     if_not_exists=True)
    op.create_table(
        "document_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("policy_decision_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('CREATED','VERSION_CREATED','SUBMITTED','APPROVED',"
            "'REJECTED','PUBLISHED','ARCHIVED','ATTACHMENT_ADDED','ARTIFACT_STORED',"
            "'KNOWLEDGE_PROJECTED','PROJECTION_FAILED')",
            name=op.f("ck_document_events_event_type_vocabulary"),
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name=op.f("ck_document_events_sequence_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_governance_document_events_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["governance.documents.workspace_id", "governance.documents.id"],
            name="fk_governance_document_events_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["governance.document_versions.workspace_id", "governance.document_versions.id"],
            name="fk_governance_document_events_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_events")),
        sa.UniqueConstraint(
            "workspace_id",
            "document_id",
            "sequence",
            name="uq_governance_document_events_sequence",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_governance_document_events_workspace_id",
        ),
        schema="governance",
    )
    op.create_index("ix_governance_document_events_history",
        "document_events",
        ["workspace_id", "document_id", "sequence"],
        schema="governance",
     if_not_exists=True)


def _create_artifact_and_attachment_tables() -> None:
    op.create_table(
        "document_artifact_receipts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("content_object_key", sa.Text(), nullable=False),
        sa.Column("content_provider_version_id", sa.String(length=1_000), nullable=False),
        sa.Column("content_etag", sa.String(length=255), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_object_key", sa.Text(), nullable=False),
        sa.Column("manifest_provider_version_id", sa.String(length=1_000), nullable=False),
        sa.Column("manifest_etag", sa.String(length=255), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_artifact_receipts_content_sha256_valid"),
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_artifact_receipts_manifest_sha256_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["governance.documents.workspace_id", "governance.documents.id"],
            name="fk_governance_document_artifact_receipts_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["governance.document_versions.workspace_id", "governance.document_versions.id"],
            name="fk_governance_document_artifact_receipts_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_artifact_receipts")),
        sa.UniqueConstraint(
            "bucket",
            "content_object_key",
            "content_provider_version_id",
            name="uq_governance_document_artifact_content",
        ),
        sa.UniqueConstraint(
            "bucket",
            "manifest_object_key",
            "manifest_provider_version_id",
            name="uq_governance_document_artifact_manifest",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "document_version_id",
            name="uq_governance_document_artifact_receipts_version",
        ),
        schema="governance",
    )
    op.create_table(
        "document_attachments",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("original_name", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("provider_version_id", sa.String(length=1_000), nullable=False),
        sa.Column("etag", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_attachments_content_sha256_valid"),
        ),
        sa.CheckConstraint(
            "size_bytes BETWEEN 1 AND 26214400",
            name=op.f("ck_document_attachments_size_bytes_range"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["governance.documents.workspace_id", "governance.documents.id"],
            name="fk_governance_document_attachments_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["governance.document_versions.workspace_id", "governance.document_versions.id"],
            name="fk_governance_document_attachments_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "uploaded_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_governance_document_attachments_uploader",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_attachments")),
        sa.UniqueConstraint(
            "bucket",
            "object_key",
            "provider_version_id",
            name="uq_governance_document_attachments_object",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_governance_document_attachments_workspace_id",
        ),
        schema="governance",
    )
    op.create_index("ix_governance_document_attachments_version",
        "document_attachments",
        ["workspace_id", "document_version_id", "created_at", "id"],
        schema="governance",
     if_not_exists=True)


def _create_projection_tables() -> None:
    op.create_table(
        "document_knowledge_chunks",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "embedding",
            sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql"),
            nullable=False,
        ),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_identity", sa.String(length=255), nullable=False),
        sa.Column("graph_node_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_knowledge_chunks_content_sha256_valid"),
        ),
        sa.CheckConstraint(
            "embedding_dimension BETWEEN 1 AND 16384",
            name=op.f("ck_document_knowledge_chunks_embedding_dimension_range"),
        ),
        sa.CheckConstraint(
            "ordinal > 0",
            name=op.f("ck_document_knowledge_chunks_ordinal_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["governance.documents.workspace_id", "governance.documents.id"],
            name="fk_governance_document_knowledge_chunks_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["governance.document_versions.workspace_id", "governance.document_versions.id"],
            name="fk_governance_document_knowledge_chunks_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_knowledge_chunks")),
        sa.UniqueConstraint(
            "workspace_id",
            "document_version_id",
            "ordinal",
            name="uq_governance_document_knowledge_chunks_ordinal",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_governance_document_knowledge_chunks_workspace_id",
        ),
        schema="governance",
    )
    op.create_index("ix_governance_document_knowledge_chunks_search",
        "document_knowledge_chunks",
        ["workspace_id", "document_id", "document_version_id", "ordinal"],
        schema="governance",
     if_not_exists=True)
    op.create_table(
        "document_projection_receipts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_identity", sa.String(length=255), nullable=False),
        sa.Column("projection_hash", sa.String(length=64), nullable=False),
        sa.Column("graph_projection_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "graph_projection_hash IS NULL OR graph_projection_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_projection_receipts_graph_projection_hash_valid"),
        ),
        sa.CheckConstraint(
            "projection_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_document_projection_receipts_projection_hash_valid"),
        ),
        sa.CheckConstraint(
            "chunk_count BETWEEN 1 AND 512",
            name=op.f("ck_document_projection_receipts_chunk_count_range"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["governance.documents.workspace_id", "governance.documents.id"],
            name="fk_governance_document_projection_receipts_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["governance.document_versions.workspace_id", "governance.document_versions.id"],
            name="fk_governance_document_projection_receipts_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_projection_receipts")),
        sa.UniqueConstraint(
            "workspace_id",
            "document_version_id",
            name="uq_governance_document_projection_receipts_version",
        ),
        schema="governance",
    )
