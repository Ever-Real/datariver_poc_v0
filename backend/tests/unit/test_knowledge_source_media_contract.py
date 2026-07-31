from __future__ import annotations

import runpy
from pathlib import Path

from sqlalchemy import CheckConstraint

from datariver.domain.knowledge_pipeline import KNOWLEDGE_SOURCE_MEDIA_TYPES
from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0082_knowledge_source_media_type_vocabulary.py"

_LEGACY_AND_MACRO_MEDIA_TYPES = frozenset(
    {
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.ms-word.document.macroEnabled.12",
        "application/vnd.ms-excel.sheet.macroEnabled.12",
        "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
        "application/octet-stream",
    }
)


def test_source_snapshot_model_uses_the_exact_governed_media_vocabulary() -> None:
    table = Base.metadata.tables["knowledge.source_snapshots"]
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    media_check = constraints["ck_source_snapshots_media_type_vocabulary"]
    assert "ck_source_snapshots_pdf_media_type" not in constraints
    for media_type in KNOWLEDGE_SOURCE_MEDIA_TYPES:
        assert f"'{media_type}'" in media_check
    for media_type in _LEGACY_AND_MACRO_MEDIA_TYPES:
        assert f"'{media_type}'" not in media_check
    assert media_check.count("'") == len(KNOWLEDGE_SOURCE_MEDIA_TYPES) * 2


def test_0082_migration_snapshots_the_domain_vocabulary_and_safe_downgrade() -> None:
    migration = runpy.run_path(str(MIGRATION))

    assert migration["revision"] == "0082"
    assert migration["down_revision"] == "0081"
    assert frozenset(migration["_SOURCE_MEDIA_TYPES"]) == KNOWLEDGE_SOURCE_MEDIA_TYPES
    assert "media_type IN (" in migration["_media_type_check"]()

    source = MIGRATION.read_text(encoding="utf-8")
    assert "ck_source_snapshots_pdf_media_type" in source
    assert "ck_source_snapshots_media_type_vocabulary" in source
    assert "WHERE media_type <> 'application/pdf'" in source
    assert "explicit reconciliation of non-PDF source snapshots" in source
