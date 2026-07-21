from __future__ import annotations

from pathlib import Path


class SecretResolutionError(RuntimeError):
    pass


class SecretResolver:
    """Resolve secrets without persisting or logging their values."""

    def __init__(self, *, virtual_secret_root: str | None = None) -> None:
        self._virtual_secret_root = (
            Path(virtual_secret_root).resolve() if virtual_secret_root is not None else None
        )

    def _path(self, reference: str) -> Path:
        if not reference.startswith("file:"):
            raise SecretResolutionError("This deployment supports file secret references only.")
        raw_path = reference.removeprefix("file:")
        virtual_prefix = "/run/secrets/"
        if self._virtual_secret_root is not None and raw_path.startswith(virtual_prefix):
            name = raw_path.removeprefix(virtual_prefix)
            if not name or "/" in name or "\\" in name:
                raise SecretResolutionError("The virtual secret reference is invalid.")
            return self._virtual_secret_root / name
        return Path(raw_path)

    def resolve(self, reference: str) -> str:
        path = self._path(reference)
        try:
            if not path.is_file():
                raise SecretResolutionError("The referenced secret file does not exist.")
            if path.stat().st_size > 16_384:
                raise SecretResolutionError("The referenced secret file exceeds the size limit.")
            value = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise SecretResolutionError("The referenced secret file cannot be read.") from error
        if not value:
            raise SecretResolutionError("The referenced secret is empty.")
        return value
