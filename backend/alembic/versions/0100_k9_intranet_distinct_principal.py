"""k9 intranet distinct principal

Revision ID: 0100
Revises: 0099
Create Date: 2026-08-23 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0100"
down_revision: str | Sequence[str] | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_SUBJECT = "NULLIF(current_setting('app.subject_id', true), '')::uuid"
K9_MAKER = "'00000000-0000-4000-8000-000000000110'::uuid"
K9_CHECKER = "'00000000-0000-4000-8000-000000000111'::uuid"
K9_WORKSPACE = "'00000000-0000-4000-8000-000000000100'::uuid"
K9_DOMAIN = "'f14fa2ce-e5f2-beee-5eea-5e77be5754ff'::uuid"
K9_DOMAIN_STR = "f14fa2ce-e5f2-beee-5eea-5e77be5754ff"


def _reviewer_sql(
    draft_reference: str, *, require_publish: bool = False, upgrade: bool = True
) -> str:
    actions = ("kg.review", "kg.publish") if require_publish else ("kg.review",)
    action_checks = " AND ".join(
        (
            "COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb) "
            f"? '{action}' AND NOT ("
            "COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb) "
            f"? '{action}')"
        )
        for action in actions
    )

    k9_override_predicate = ""
    if upgrade:
        k9_override_predicate = (
            f"OR (membership.subject_id = {K9_CHECKER} "
            f"AND {draft_reference}.author_id = {K9_MAKER} "
            f"AND membership.workspace_id = {K9_WORKSPACE} "
            f"AND {draft_reference}.workspace_id = {K9_WORKSPACE} "
            f"AND {draft_reference}.domain_ref_id = {K9_DOMAIN} "
            "AND COALESCE(membership.job_function, '') = 'SERVICE_ACCOUNT' "
            "AND jsonb_array_length(COALESCE(membership.attributes -> 'groups', '[]'::jsonb)) = 2 "
            "AND COALESCE(membership.attributes -> 'groups', '[]'::jsonb) "
            '@> \'["service-accounts", "k9-publisher-checkers"]\'::jsonb '
            "AND jsonb_array_length(COALESCE(membership.attributes -> 'allowed_actions', "
            "'[]'::jsonb)) = 3 "
            "AND COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb) "
            '@> \'["kg.read", "kg.review", "kg.publish"]\'::jsonb '
            "AND COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb) = '[]'::jsonb "
            "AND COALESCE(membership.attributes -> 'allowed_system_ids', "
            "'[]'::jsonb) = '[]'::jsonb "
            "AND jsonb_array_length(COALESCE(membership.attributes -> 'allowed_domain_ids', "
            "'[]'::jsonb)) = 1 "
            "AND COALESCE(membership.attributes -> 'allowed_domain_ids', '[]'::jsonb) "
            f"@> '[\"{K9_DOMAIN_STR}\"]'::jsonb)"
        )

    return (
        "EXISTS (SELECT 1 FROM iam.workspace_memberships AS membership "  # noqa: S608 -- SQL is built solely from fixed migration identifiers
        "JOIN iam.subjects AS reviewer_subject "
        "ON reviewer_subject.id = membership.subject_id "
        "JOIN platform.workspaces AS reviewer_workspace "
        "ON reviewer_workspace.id = membership.workspace_id "
        f"WHERE membership.workspace_id = {draft_reference}.workspace_id "
        f"AND membership.subject_id = {CURRENT_SUBJECT} "
        f"AND membership.subject_id <> {draft_reference}.author_id "
        "AND reviewer_workspace.status = 'ACTIVE' "
        "AND reviewer_subject.active IS TRUE "
        "AND membership.active IS TRUE "
        "AND (membership.access_expires_at IS NULL "
        "OR membership.access_expires_at > transaction_timestamp()) "
        "AND (COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT' "
        f"{k9_override_predicate}) "
        "AND (NOT (COALESCE(membership.attributes -> 'groups', '[]'::jsonb) "
        f"? 'service-accounts') {k9_override_predicate}) "
        f"AND membership.clearance >= {draft_reference}.classification "
        f"AND ({draft_reference}.classification = 0 OR "
        "COALESCE(membership.attributes -> 'allowed_domain_ids', '[]'::jsonb) "
        f"? {draft_reference}.domain_ref_id::text) "
        f"AND {action_checks})"
    )


def _draft_actor_read_sql(draft_reference: str, upgrade: bool = True) -> str:
    return (
        f"{draft_reference}.author_id = {CURRENT_SUBJECT} OR "
        f"({draft_reference}.state IN ('REVIEW', 'PUBLISHED') "
        f"AND {_reviewer_sql(draft_reference, upgrade=upgrade)})"
    )


def _replace_draft_rls(upgrade: bool) -> None:
    owner = f"author_id = {CURRENT_SUBJECT}"
    reviewer = _reviewer_sql("studio_drafts", upgrade=upgrade)
    publisher = _reviewer_sql("studio_drafts", require_publish=True, upgrade=upgrade)

    op.execute("DROP POLICY studio_draft_actor_select ON knowledge.studio_drafts")
    op.execute(
        f"""
        CREATE POLICY studio_draft_actor_select ON knowledge.studio_drafts
        AS RESTRICTIVE FOR SELECT TO datariver_app
        USING (
            {owner}
            OR (state IN ('REVIEW', 'PUBLISHED') AND {reviewer})
        )
        """
    )
    op.execute("DROP POLICY studio_draft_governed_update ON knowledge.studio_drafts")
    op.execute(
        f"""
        CREATE POLICY studio_draft_governed_update ON knowledge.studio_drafts
        AS RESTRICTIVE FOR UPDATE TO datariver_app
        USING (
            ({owner} AND state IN ('DRAFT', 'REVIEW'))
            OR (state = 'REVIEW' AND {publisher})
        )
        WITH CHECK (
            ({owner} AND state IN ('DRAFT', 'REVIEW', 'DISCARDED'))
            OR (
                state = 'PUBLISHED'
                AND reviewed_by = {CURRENT_SUBJECT}
                AND published_by = {CURRENT_SUBJECT}
                AND {publisher}
            )
        )
        """
    )

    for table in (
        "tbox_draft_elements",
        "abox_binding_drafts",
        "abox_mapping_rule_drafts",
    ):
        op.execute(f"DROP POLICY studio_draft_actor_select ON knowledge.{table}")
        actor_parent = (
            "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS visible_draft "  # noqa: S608 -- SQL is built solely from fixed migration identifiers
            f"WHERE visible_draft.workspace_id = {table}.workspace_id "
            f"AND visible_draft.id = {table}.draft_id "
            f"AND ({_draft_actor_read_sql('visible_draft', upgrade=upgrade)}))"
        )
        op.execute(
            f"""
            CREATE POLICY studio_draft_actor_select ON knowledge.{table}
            AS RESTRICTIVE FOR SELECT TO datariver_app
            USING ({actor_parent})
            """
        )

    op.execute("DROP POLICY source_reference_actor_select ON knowledge.source_references")
    statement = f"""
        CREATE POLICY source_reference_actor_select ON knowledge.source_references
        AS RESTRICTIVE FOR SELECT TO datariver_app
        USING (
            created_by = {CURRENT_SUBJECT}
            OR EXISTS (
                SELECT 1
                FROM knowledge.abox_binding_drafts AS binding
                JOIN knowledge.studio_drafts AS bound_draft
                  ON bound_draft.workspace_id = binding.workspace_id
                 AND bound_draft.id = binding.draft_id
                WHERE binding.workspace_id = source_references.workspace_id
                  AND binding.source_reference_id = source_references.id
                  AND bound_draft.state IN ('REVIEW', 'PUBLISHED')
                  AND {_reviewer_sql("bound_draft", upgrade=upgrade)}
            )
        )
        """  # noqa: S608 -- SQL is built solely from fixed migration identifiers
    op.execute(statement)


def _install_preflight_rls(upgrade: bool) -> None:
    op.execute("DROP POLICY studio_preflight_actor_select ON knowledge.studio_preflight_checks")
    op.execute("DROP POLICY studio_preflight_actor_insert ON knowledge.studio_preflight_checks")

    visible_parent = (
        "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS visible_draft "  # noqa: S608 -- SQL is built solely from fixed migration identifiers
        "WHERE visible_draft.workspace_id = studio_preflight_checks.workspace_id "
        "AND visible_draft.id = studio_preflight_checks.draft_id "
        f"AND ({_draft_actor_read_sql('visible_draft', upgrade=upgrade)}))"
    )
    insert_parent = (
        "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS target_draft "  # noqa: S608 -- SQL is built solely from fixed migration identifiers
        "WHERE target_draft.workspace_id = studio_preflight_checks.workspace_id "
        "AND target_draft.id = studio_preflight_checks.draft_id "
        "AND ((target_draft.state = 'DRAFT' "
        f"AND target_draft.author_id = {CURRENT_SUBJECT}) "
        "OR (target_draft.state = 'REVIEW' "
        f"AND {_reviewer_sql('target_draft', upgrade=upgrade)})))"
    )
    op.execute(
        f"""
        CREATE POLICY studio_preflight_actor_select
        ON knowledge.studio_preflight_checks
        AS RESTRICTIVE FOR SELECT TO datariver_app
        USING ({visible_parent})
        """
    )
    op.execute(
        f"""
        CREATE POLICY studio_preflight_actor_insert
        ON knowledge.studio_preflight_checks
        AS RESTRICTIVE FOR INSERT TO datariver_app
        WITH CHECK (
            checked_by = {CURRENT_SUBJECT}
            AND {insert_parent}
        )
        """
    )


def _install_release_rls(upgrade: bool) -> None:
    op.execute("DROP POLICY studio_release_publisher_insert ON knowledge.studio_releases")
    op.execute("DROP POLICY studio_release_publisher_archive ON knowledge.studio_releases")

    insert_parent = (
        "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS source_draft "  # noqa: S608 -- SQL is built solely from fixed migration identifiers
        "WHERE source_draft.workspace_id = studio_releases.workspace_id "
        "AND source_draft.id = studio_releases.source_draft_id "
        "AND source_draft.state = 'REVIEW' "
        f"AND {_reviewer_sql('source_draft', require_publish=True, upgrade=upgrade)})"
    )
    archive_parent = (
        "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS source_draft "  # noqa: S608 -- SQL is built solely from fixed migration identifiers
        "WHERE source_draft.workspace_id = studio_releases.workspace_id "
        "AND source_draft.id = studio_releases.source_draft_id "
        "AND source_draft.state = 'PUBLISHED' "
        f"AND {_reviewer_sql('source_draft', require_publish=True, upgrade=upgrade)})"
    )
    op.execute(
        f"""
        CREATE POLICY studio_release_publisher_insert
        ON knowledge.studio_releases
        AS RESTRICTIVE FOR INSERT TO datariver_app
        WITH CHECK (
            reviewed_by = {CURRENT_SUBJECT}
            AND published_by = {CURRENT_SUBJECT}
            AND {insert_parent}
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY studio_release_publisher_archive
        ON knowledge.studio_releases
        AS RESTRICTIVE FOR UPDATE TO datariver_app
        USING (
            state = 'ACTIVE'
            AND {archive_parent}
        )
        WITH CHECK (
            state = 'ARCHIVED'
            AND archived_by = {CURRENT_SUBJECT}
            AND {archive_parent}
        )
        """
    )


def upgrade() -> None:
    _replace_draft_rls(upgrade=True)
    _install_preflight_rls(upgrade=True)
    _install_release_rls(upgrade=True)


def downgrade() -> None:
    _replace_draft_rls(upgrade=False)
    _install_preflight_rls(upgrade=False)
    _install_release_rls(upgrade=False)
