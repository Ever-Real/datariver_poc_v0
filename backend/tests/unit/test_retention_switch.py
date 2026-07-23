from pathlib import Path

from datariver.workers.retention_switch import ReloadableRetentionSwitch


def test_reloadable_retention_switch_is_fail_closed_and_live(tmp_path: Path) -> None:
    control_file = tmp_path / "retention.enabled"
    switch = ReloadableRetentionSwitch(
        deployment_enabled=True,
        control_file=str(control_file),
    )

    assert switch.enabled() is False
    control_file.write_text("DISABLED\n", encoding="utf-8")
    assert switch.enabled() is False
    control_file.write_text("ENABLED\n", encoding="utf-8")
    assert switch.enabled() is True
    control_file.write_text("enabled\n", encoding="utf-8")
    assert switch.enabled() is False


def test_reloadable_retention_switch_cannot_override_deployment_disable(tmp_path: Path) -> None:
    control_file = tmp_path / "retention.enabled"
    control_file.write_text("ENABLED\n", encoding="utf-8")

    assert (
        ReloadableRetentionSwitch(
            deployment_enabled=False,
            control_file=str(control_file),
        ).enabled()
        is False
    )
