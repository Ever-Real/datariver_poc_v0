# ruff: noqa: E501

"""Add managed studio intents fields.

Revision ID: 0097
Revises: 0096
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0097"
down_revision: str | Sequence[str] | None = "0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add to knowledge_studio_draft
    op.add_column("knowledge_studio_draft", sa.Column("managed_intent", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_draft", sa.Column("managed_graph_type", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_draft", sa.Column("accepted_proposal_id", sa.String(255), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_draft", sa.Column("accepted_proposal_hash", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_draft", sa.Column("source_contract_hash", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_draft", sa.Column("mapping_contract_hash", sa.String(64), nullable=True), schema="knowledge")

    # Add to knowledge_studio_release
    op.add_column("knowledge_studio_release", sa.Column("managed_intent", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_release", sa.Column("managed_graph_type", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_release", sa.Column("accepted_proposal_id", sa.String(255), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_release", sa.Column("accepted_proposal_hash", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_release", sa.Column("source_contract_hash", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("knowledge_studio_release", sa.Column("mapping_contract_hash", sa.String(64), nullable=True), schema="knowledge")


def downgrade() -> None:
    # Drop from knowledge_studio_release
    op.drop_column("knowledge_studio_release", "mapping_contract_hash", schema="knowledge")
    op.drop_column("knowledge_studio_release", "source_contract_hash", schema="knowledge")
    op.drop_column("knowledge_studio_release", "accepted_proposal_hash", schema="knowledge")
    op.drop_column("knowledge_studio_release", "accepted_proposal_id", schema="knowledge")
    op.drop_column("knowledge_studio_release", "managed_graph_type", schema="knowledge")
    op.drop_column("knowledge_studio_release", "managed_intent", schema="knowledge")

    # Drop from knowledge_studio_draft
    op.drop_column("knowledge_studio_draft", "mapping_contract_hash", schema="knowledge")
    op.drop_column("knowledge_studio_draft", "source_contract_hash", schema="knowledge")
    op.drop_column("knowledge_studio_draft", "accepted_proposal_hash", schema="knowledge")
    op.drop_column("knowledge_studio_draft", "accepted_proposal_id", schema="knowledge")
    op.drop_column("knowledge_studio_draft", "managed_graph_type", schema="knowledge")
    op.drop_column("knowledge_studio_draft", "managed_intent", schema="knowledge")
