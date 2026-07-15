from __future__ import annotations

from pathlib import Path


class SecretResolutionError(RuntimeError):
    pass


class SecretResolver:
    """Resolve secrets without persisting or logging their values."""

    def resolve(self, reference: str) -> str:
        if not reference.startswith("file:"):
            raise SecretResolutionError("This deployment supports file secret references only.")
        path = Path(reference.removeprefix("file:"))
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
