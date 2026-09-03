from __future__ import annotations

from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy.engine import Connection


class RelationDefinitionFingerprintV1(NamedTuple):
    constraints: str
    indexes: str
    policies: str
    triggers: str
    rls: str


RELATION_DEFINITION_FINGERPRINT_SQL_V1 = sa.text(
    """
    SELECT
        encode(sha256(convert_to(COALESCE((
            SELECT string_agg(
                constraint_state.conname || '|' || constraint_state.contype::text || '|' ||
                constraint_state.condeferrable::text || '|' ||
                constraint_state.condeferred::text || '|' ||
                regexp_replace(
                    pg_get_constraintdef(constraint_state.oid, true),
                    '[[:space:]]+', ' ', 'g'
                ),
                E'\\n' ORDER BY constraint_state.conname
            )
            FROM pg_constraint AS constraint_state
            WHERE constraint_state.conrelid = to_regclass(:relation)
        ), ''), 'UTF8')), 'hex') AS constraints,
        encode(sha256(convert_to(COALESCE((
            SELECT string_agg(
                index_class.relname || '|' || index_state.indisunique::text || '|' ||
                index_state.indisprimary::text || '|' ||
                regexp_replace(
                    pg_get_indexdef(index_state.indexrelid),
                    '[[:space:]]+', ' ', 'g'
                ) || '|' || COALESCE(regexp_replace(
                    pg_get_expr(index_state.indpred, index_state.indrelid, true),
                    '[[:space:]]+', ' ', 'g'
                ), ''),
                E'\\n' ORDER BY index_class.relname
            )
            FROM pg_index AS index_state
            JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
            WHERE index_state.indrelid = to_regclass(:relation)
              AND NOT EXISTS (
                  SELECT 1 FROM pg_constraint
                  WHERE conindid = index_state.indexrelid
              )
        ), ''), 'UTF8')), 'hex') AS indexes,
        encode(sha256(convert_to(COALESCE((
            SELECT string_agg(
                policy_state.polname || '|' || policy_state.polpermissive::text || '|' ||
                policy_state.polcmd::text || '|' || COALESCE((
                    SELECT string_agg(
                        COALESCE(role_state.rolname, 'PUBLIC'), ','
                        ORDER BY COALESCE(role_state.rolname, 'PUBLIC')
                    )
                    FROM unnest(policy_state.polroles) AS role_oid
                    LEFT JOIN pg_roles AS role_state ON role_state.oid = role_oid
                ), '') || '|' || COALESCE(regexp_replace(
                    pg_get_expr(policy_state.polqual, policy_state.polrelid, true),
                    '[[:space:]]+', ' ', 'g'
                ), '') || '|' || COALESCE(regexp_replace(
                    pg_get_expr(policy_state.polwithcheck, policy_state.polrelid, true),
                    '[[:space:]]+', ' ', 'g'
                ), ''),
                E'\\n' ORDER BY policy_state.polname
            )
            FROM pg_policy AS policy_state
            WHERE policy_state.polrelid = to_regclass(:relation)
        ), ''), 'UTF8')), 'hex') AS policies,
        encode(sha256(convert_to(COALESCE((
            SELECT string_agg(
                trigger_state.tgname || '|' || trigger_state.tgenabled::text || '|' ||
                trigger_state.tgtype::text || '|' ||
                trigger_state.tgfoid::regprocedure::text || '|' ||
                regexp_replace(
                    pg_get_triggerdef(trigger_state.oid, true),
                    '[[:space:]]+', ' ', 'g'
                ),
                E'\\n' ORDER BY trigger_state.tgname
            )
            FROM pg_trigger AS trigger_state
            WHERE trigger_state.tgrelid = to_regclass(:relation)
              AND NOT trigger_state.tgisinternal
        ), ''), 'UTF8')), 'hex') AS triggers,
        COALESCE((
            SELECT relation_state.relrowsecurity::text || '|' ||
                   relation_state.relforcerowsecurity::text
            FROM pg_class AS relation_state
            WHERE relation_state.oid = to_regclass(:relation)
        ), '') AS rls
    """
)


def read_relation_definition_fingerprint_v1(
    connection: Connection,
    relation: str,
) -> RelationDefinitionFingerprintV1:
    row = (
        connection.execute(
            RELATION_DEFINITION_FINGERPRINT_SQL_V1,
            {"relation": relation},
        )
        .mappings()
        .one()
    )
    return RelationDefinitionFingerprintV1(
        constraints=str(row["constraints"]),
        indexes=str(row["indexes"]),
        policies=str(row["policies"]),
        triggers=str(row["triggers"]),
        rls=str(row["rls"]),
    )
