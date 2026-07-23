from __future__ import annotations

from datariver.domain.common import DomainError


class ExternalDependencyError(DomainError):
    code = "external_dependency_error"

    def __init__(
        self,
        message: str,
        *,
        dependency: str,
        retryable: bool,
        provider_code: str | None = None,
        ambiguous_commit: bool = False,
    ) -> None:
        super().__init__(
            message,
            details={
                "dependency": dependency,
                "retryable": retryable,
                "provider_code": provider_code,
                "ambiguous_commit": ambiguous_commit,
            },
        )


class AuthenticationError(DomainError):
    code = "authentication_failed"
