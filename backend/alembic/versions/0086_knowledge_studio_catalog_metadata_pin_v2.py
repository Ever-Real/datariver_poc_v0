"""Pin bounded Catalog field metadata for Knowledge Studio Proposal jobs.

Revision ID: 0086
Revises: 0085
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.knowledge_studio_proposal_job_sql import (
    TBOX_PROPOSAL_JOB_CATALOG_PIN_V2_FUNCTION_SQL,
    TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SQL,
    TBOX_PROPOSAL_JOB_GUARD_FUNCTION_SQL,
)

revision: str = "0086"
down_revision: str | Sequence[str] | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOWNGRADE_REFUSAL_SQL = """
DO $datariver$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM knowledge.tbox_proposal_jobs
        WHERE input_kind = 'CATALOG_SCHEMA'
          AND catalog_source_document ? 'contract_version'
    ) THEN
        RAISE EXCEPTION
            '0086 downgrade requires explicit reconciliation of versioned Catalog pins';
    END IF;
END
$datariver$;
""".strip()


def split_postgresql_statements(sql: str) -> tuple[str, ...]:
    """Split PostgreSQL without breaking quoted or dollar-quoted bodies."""

    statements: list[str] = []
    statement_start = 0
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None
    block_comment_depth = 0
    in_line_comment = False
    while index < len(sql):
        if in_line_comment:
            if sql[index] == "\n":
                in_line_comment = False
            index += 1
            continue
        if block_comment_depth:
            if sql.startswith("/*", index):
                block_comment_depth += 1
                index += 2
            elif sql.startswith("*/", index):
                block_comment_depth -= 1
                index += 2
            else:
                index += 1
            continue
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
            else:
                index += 1
            continue
        if quote is not None:
            if sql[index] == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if sql.startswith("--", index):
            in_line_comment = True
            index += 2
            continue
        if sql.startswith("/*", index):
            block_comment_depth = 1
            index += 2
            continue
        if sql[index] in {"'", '"'}:
            quote = sql[index]
            index += 1
            continue
        if sql[index] == "$":
            tag_end = sql.find("$", index + 1)
            if tag_end != -1:
                candidate = sql[index : tag_end + 1]
                tag_body = candidate[1:-1]
                if not tag_body or (
                    (tag_body[0].isalpha() or tag_body[0] == "_")
                    and all(character.isalnum() or character == "_" for character in tag_body)
                ):
                    dollar_tag = candidate
                    index = tag_end + 1
                    continue
        if sql[index] == ";":
            statement = sql[statement_start : index + 1].strip()
            if statement:
                statements.append(statement)
            statement_start = index + 1
        index += 1
    remainder = sql[statement_start:].strip()
    if remainder:
        statements.append(remainder)
    if quote is not None or dollar_tag is not None or block_comment_depth:
        raise ValueError("Unterminated quoted PostgreSQL migration script")
    return tuple(statements)


def _execute_sql_script(sql: str) -> None:
    for statement in split_postgresql_statements(sql):
        op.execute(statement)


def upgrade() -> None:
    _execute_sql_script(TBOX_PROPOSAL_JOB_CATALOG_PIN_V2_FUNCTION_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_REFUSAL_SQL)
    _execute_sql_script(TBOX_PROPOSAL_JOB_GUARD_FUNCTION_SQL)
    _execute_sql_script(TBOX_PROPOSAL_JOB_COMMAND_FUNCTION_SQL)
