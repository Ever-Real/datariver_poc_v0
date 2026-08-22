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
    # Add to studio_drafts
    op.add_column("studio_drafts", sa.Column("managed_intent", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("studio_drafts", sa.Column("managed_graph_type", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("studio_drafts", sa.Column("accepted_proposal_id", sa.String(255), nullable=True), schema="knowledge")
    op.add_column("studio_drafts", sa.Column("accepted_proposal_hash", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("studio_drafts", sa.Column("source_contract_hash", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("studio_drafts", sa.Column("mapping_contract_hash", sa.String(64), nullable=True), schema="knowledge")

    # Add to studio_releases
    op.add_column("studio_releases", sa.Column("managed_intent", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("studio_releases", sa.Column("managed_graph_type", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("studio_releases", sa.Column("accepted_proposal_id", sa.String(255), nullable=True), schema="knowledge")
    op.add_column("studio_releases", sa.Column("accepted_proposal_hash", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("studio_releases", sa.Column("source_contract_hash", sa.String(64), nullable=True), schema="knowledge")
    op.add_column("studio_releases", sa.Column("mapping_contract_hash", sa.String(64), nullable=True), schema="knowledge")


def downgrade() -> None:
    # Drop from studio_releases
    op.drop_column("studio_releases", "mapping_contract_hash", schema="knowledge")
    op.drop_column("studio_releases", "source_contract_hash", schema="knowledge")
    op.drop_column("studio_releases", "accepted_proposal_hash", schema="knowledge")
    op.drop_column("studio_releases", "accepted_proposal_id", schema="knowledge")
    op.drop_column("studio_releases", "managed_graph_type", schema="knowledge")
    op.drop_column("studio_releases", "managed_intent", schema="knowledge")

    # Drop from studio_drafts
    op.drop_column("studio_drafts", "mapping_contract_hash", schema="knowledge")
    op.drop_column("studio_drafts", "source_contract_hash", schema="knowledge")
    op.drop_column("studio_drafts", "accepted_proposal_hash", schema="knowledge")
    op.drop_column("studio_drafts", "accepted_proposal_id", schema="knowledge")
    op.drop_column("studio_drafts", "managed_graph_type", schema="knowledge")
    op.drop_column("studio_drafts", "managed_intent", schema="knowledge")
