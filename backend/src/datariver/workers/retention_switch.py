from __future__ import annotations

from pathlib import Path


class ReloadableRetentionSwitch:
    """Fail-closed runtime switch layered under the deployment enable flag."""

    def __init__(self, *, deployment_enabled: bool, control_file: str | None) -> None:
        self._deployment_enabled = deployment_enabled
        self._control_file = Path(control_file) if control_file is not None else None

    def enabled(self) -> bool:
        if not self._deployment_enabled or self._control_file is None:
            return False
        try:
            return self._control_file.read_text(encoding="utf-8").strip() == "ENABLED"
        except OSError:
            return False
