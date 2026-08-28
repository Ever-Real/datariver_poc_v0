"""support Unicode T-Box names and named hierarchy relations

Revision ID: 0065
Revises: 0064
Create Date: 2026-07-29 16:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065"
down_revision: str | Sequence[str] | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical_contract_is_complete() -> bool:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"] for column in inspector.get_columns("tbox_classes", schema="knowledge")
    }
    if "hierarchy_relation" not in columns:
        return False
    index = next(
        (
            value
            for value in inspector.get_indexes("tbox_classes", schema="knowledge")
            if value["name"] == "ix_tbox_classes_parent"
        ),
        None,
    )
    if index is None or index["column_names"] != [
        "workspace_id",
        "draft_id",
        "parent_stable_class_id",
        "stable_class_id",
    ]:
        raise RuntimeError("Canonical named T-Box hierarchy index is incomplete.")
    return True


def upgrade() -> None:
    if _canonical_contract_is_complete():
        return
    op.add_column(
        "tbox_classes",
        sa.Column(
            "hierarchy_relation",
            sa.String(length=255),
            server_default=sa.text("'SUBCLASS_OF'"),
            nullable=False,
        ),
        schema="knowledge",
    )
    op.alter_column(
        "tbox_classes",
        "hierarchy_relation",
        server_default=None,
        schema="knowledge",
    )
    op.drop_index(
        "ix_tbox_classes_parent",
        table_name="tbox_classes",
        schema="knowledge",
    )
    op.create_index("ix_tbox_classes_parent",
        "tbox_classes",
        ["workspace_id", "draft_id", "parent_stable_class_id", "stable_class_id"],
        schema="knowledge",
     if_not_exists=True)


def downgrade() -> None:
    renamed_hierarchy_count = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM knowledge.tbox_classes
                WHERE hierarchy_relation <> 'SUBCLASS_OF'
                """
            )
        )
        .scalar_one()
    )
    if renamed_hierarchy_count:
        raise RuntimeError(
            "Named T-Box hierarchy relations must be archived before downgrading revision 0065."
        )
    op.drop_index(
        "ix_tbox_classes_parent",
        table_name="tbox_classes",
        schema="knowledge",
    )
    op.create_index("ix_tbox_classes_parent",
        "tbox_classes",
        ["workspace_id", "draft_id", "parent_stable_class_id"],
        schema="knowledge",
     if_not_exists=True)
    op.drop_column("tbox_classes", "hierarchy_relation", schema="knowledge")
