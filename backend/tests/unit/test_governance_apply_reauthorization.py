from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_apply_reauthorizer_uses_only_the_narrow_database_function() -> None:
    source = (
        ROOT / "src/datariver/infrastructure/db/governance_apply_reauthorization.py"
    ).read_text(encoding="utf-8")

    assert "governance.reauthorize_datahub_apply" in source
    assert "SubjectModel" not in source
    assert "WorkspaceMembershipModel" not in source
    assert "AssetProjectionModel" not in source
    assert "ClassificationAccessResolver" not in source
    assert "session.begin()" in source
    assert "requested_at" not in source
