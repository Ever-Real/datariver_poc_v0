import pytest
from pydantic import ValidationError

from datariver.config import Settings


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://u@localhost/db",
        "database_secret_ref": "file:/run/secrets/postgres_password",
        "migration_database_url": "postgresql+asyncpg://owner@localhost/db",
        "migration_database_secret_ref": "file:/run/secrets/postgres_owner_password",
        "relay_database_url": "postgresql+asyncpg://relay@localhost/db",
        "relay_database_secret_ref": "file:/run/secrets/postgres_relay_password",
        "upload_database_url": "postgresql+asyncpg://upload@localhost/db",
        "upload_database_secret_ref": "file:/run/secrets/postgres_upload_password",
        "governance_database_url": "postgresql+asyncpg://governance@localhost/db",
        "governance_database_secret_ref": "file:/run/secrets/postgres_governance_password",
        "bootstrap_database_url": "postgresql+asyncpg://bootstrap@localhost/db",
        "bootstrap_database_secret_ref": "file:/run/secrets/postgres_bootstrap_password",
        "oidc_issuer": "http://idp/realms/test",
        "oidc_audience": "datariver-api",
        "oidc_jwks_url": "http://idp/jwks",
        "datahub_base_url": "http://datahub",
        "datahub_secret_ref": "file:/run/secrets/datahub_token",
        "valkey_cache_url": "redis://cache:6379/0",
        "valkey_queue_url": "redis://queue:6379/0",
        "valkey_cache_secret_ref": "file:/run/secrets/valkey_cache_password",
        "valkey_queue_secret_ref": "file:/run/secrets/valkey_queue_password",
        "s3_endpoint_url": "http://s3",
        "s3_public_endpoint_url": "http://localhost:8333",
        "s3_bucket_quarantine": "quarantine",
        "s3_bucket_accepted": "accepted",
        "s3_access_key_file": "/run/secrets/s3_access_key",
        "s3_secret_key_file": "/run/secrets/s3_secret_key",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_rejects_shared_cache_and_queue_endpoint() -> None:
    with pytest.raises(ValidationError):
        settings(valkey_queue_url="redis://cache:6379/0")


def test_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError):
        settings(app_cors_origins=("*",))


def test_rejects_wildcard_trusted_host_in_production() -> None:
    with pytest.raises(ValidationError, match="trusted hosts"):
        settings(
            app_env="production",
            app_trusted_hosts=("*",),
            app_public_origin="https://catalog.example.com",
            app_cors_origins=("https://catalog.example.com",),
            oidc_issuer="https://idp.example.com/realms/data",
            oidc_jwks_url="https://idp.example.com/realms/data/certs",
            datahub_base_url="https://datahub.example.com",
            s3_public_endpoint_url="https://objects.example.com",
        )


def test_rejects_passwords_embedded_in_connection_urls() -> None:
    with pytest.raises(ValidationError):
        settings(upload_database_url="postgresql+asyncpg://upload:secret@localhost/db")


def test_rejects_unimplemented_secret_provider() -> None:
    with pytest.raises(ValidationError):
        settings(datahub_secret_ref="vault:secret/data/datariver")


def test_production_requires_tls_and_disables_seed() -> None:
    with pytest.raises(ValidationError):
        settings(app_env="production", seed_profile="semiconductor")


def test_accepts_secure_production_configuration() -> None:
    configured = settings(
        app_env="production",
        app_public_origin="https://catalog.example.com",
        app_cors_origins=("https://catalog.example.com",),
        oidc_issuer="https://idp.example.com/realms/data",
        oidc_jwks_url="https://idp.example.com/realms/data/certs",
        datahub_base_url="https://datahub.example.com",
        s3_public_endpoint_url="https://objects.example.com",
    )

    assert configured.app_env == "production"


def test_parses_comma_separated_collection_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "APP_CORS_ORIGINS",
        "http://localhost:8080,https://catalog.example.com",
    )
    monkeypatch.setenv("APP_TRUSTED_HOSTS", "localhost,api")
    monkeypatch.setenv("OIDC_ALLOWED_ALGORITHMS", "RS256,ES256")

    configured = settings()

    assert configured.app_cors_origins == (
        "http://localhost:8080",
        "https://catalog.example.com",
    )
    assert configured.app_trusted_hosts == ("localhost", "api")
    assert configured.oidc_allowed_algorithms == ("RS256", "ES256")
