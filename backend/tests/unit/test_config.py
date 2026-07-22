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
        "datahub_expected_version": "v1.6.0",
        "datahub_allowed_versions": (),
        "datahub_embed_enabled": False,
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
        "catalog_export_worker_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_rejects_shared_cache_and_queue_endpoint() -> None:
    with pytest.raises(ValidationError):
        settings(valkey_queue_url="redis://cache:6379/0")


def test_legacy_valkey_environment_names_map_to_redis_contract() -> None:
    configured = settings()

    assert configured.redis_cache_url == "redis://cache:6379/0"
    assert configured.redis_delivery_url == "redis://queue:6379/0"
    assert configured.redis_cache_secret_ref.endswith("valkey_cache_password")
    assert configured.redis_delivery_secret_ref.endswith("valkey_queue_password")


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


def test_external_ui_links_are_optional_and_cannot_embed_credentials() -> None:
    configured = settings(
        ui_datahub_url="https://catalog.example.com/datahub",
        ui_grafana_url="https://observe.example.com/grafana",
    )

    assert str(configured.ui_datahub_url) == "https://catalog.example.com/datahub"
    assert configured.ui_airflow_url is None
    with pytest.raises(ValidationError, match="cannot contain user information"):
        settings(ui_grafana_url="https://admin:secret@observe.example.com")


def test_identity_administration_is_opt_in_and_requires_a_file_secret() -> None:
    defaults = settings()
    assert defaults.identity_admin_enabled is False
    assert defaults.identity_admin_base_url is None

    with pytest.raises(ValidationError, match="requires a Keycloak URL"):
        settings(identity_admin_enabled=True)
    with pytest.raises(ValidationError, match="file-mounted"):
        settings(
            identity_admin_enabled=True,
            identity_admin_base_url="http://keycloak:8080",
            identity_admin_client_secret_ref="literal:secret",
        )
    with pytest.raises(ValidationError, match="one origin"):
        settings(
            identity_admin_enabled=True,
            identity_admin_base_url="http://keycloak:8080/admin",
            identity_admin_client_secret_ref=(
                "file:/run/secrets/keycloak_identity_admin_client_secret"
            ),
        )

    configured = settings(
        identity_admin_enabled=True,
        identity_admin_base_url="http://keycloak:8080",
        identity_admin_client_secret_ref=(
            "file:/run/secrets/keycloak_identity_admin_client_secret"
        ),
        identity_password_change_action_enabled=True,
    )
    assert configured.identity_admin_enabled is True
    assert configured.identity_password_change_action_enabled is True


def test_platform_security_switches_are_explicit_and_fail_closed_by_default() -> None:
    configured = settings(
        oidc_hardware_webauthn_enabled=False,
        workspace_selection_enabled=False,
    )

    assert configured.oidc_hardware_webauthn_enabled is False
    assert configured.workspace_selection_enabled is False
    assert configured.admin_password_fallback_enabled is False


def test_datahub_embed_is_disabled_first_and_uses_one_exact_origin() -> None:
    assert settings().datahub_lineage_embed_url("urn:li:dataset:(a,b,c)") is None
    with pytest.raises(ValidationError, match="requires one configured"):
        settings(datahub_embed_enabled=True)
    with pytest.raises(ValidationError, match="exact origin"):
        settings(datahub_embed_base_url="https://datahub.example.com/legacy")

    configured = settings(
        datahub_embed_enabled=True,
        datahub_embed_base_url="https://datahub.example.com",
    )

    assert configured.datahub_lineage_embed_url("urn:li:dataset:(a,b,c)") == (
        "https://datahub.example.com/dataset/urn%3Ali%3Adataset%3A%28a%2Cb%2Cc%29/Lineage"
    )


def test_grafana_embed_is_disabled_first_and_requires_deployment_evidence() -> None:
    assert settings().grafana_embed_url() is None
    with pytest.raises(ValidationError, match="requires a configured Grafana page"):
        settings(grafana_embed_enabled=True)
    with pytest.raises(ValidationError, match="exact origin"):
        settings(grafana_embed_base_url="https://grafana.example.com/d/overview")
    with pytest.raises(ValidationError, match="same scheme and host"):
        settings(
            ui_grafana_url="https://grafana.example.com/d/overview",
            grafana_embed_base_url="https://other-grafana.example.com",
        )

    configured = settings(
        ui_grafana_url="https://grafana.example.com/d/overview",
        grafana_embed_base_url="https://grafana.example.com",
        grafana_embed_enabled=True,
        grafana_embed_evidence_reference="SEC-REVIEW-1234",
    )

    assert configured.grafana_embed_url() == "https://grafana.example.com/d/overview"


def test_production_external_ui_links_require_tls() -> None:
    with pytest.raises(ValidationError, match="ui_grafana_url"):
        settings(
            app_env="production",
            app_public_origin="https://catalog.example.com",
            app_cors_origins=("https://catalog.example.com",),
            oidc_issuer="https://idp.example.com/realms/data",
            oidc_jwks_url="https://idp.example.com/realms/data/certs",
            datahub_base_url="https://datahub.example.com",
            datahub_version_enforcement="enforce",
            s3_public_endpoint_url="https://objects.example.com",
            ui_grafana_url="http://observe.example.com",
        )


def test_production_requires_tls_and_disables_seed() -> None:
    with pytest.raises(ValidationError):
        settings(app_env="production", seed_profile="semiconductor")


def test_production_rejects_development_only_ephemeral_chat() -> None:
    with pytest.raises(ValidationError, match="Development-only ephemeral Chat"):
        settings(
            app_env="production",
            app_public_origin="https://catalog.example.com",
            app_cors_origins=("https://catalog.example.com",),
            oidc_issuer="https://idp.example.com/realms/data",
            oidc_jwks_url="https://idp.example.com/realms/data/certs",
            datahub_base_url="https://datahub.example.com",
            datahub_version_enforcement="enforce",
            s3_public_endpoint_url="https://objects.example.com",
            chat_ephemeral_admin_without_retention_enabled=True,
        )


def test_local_ollama_chat_is_development_only_and_host_gateway_bound() -> None:
    configured = settings(
        local_ollama_chat_enabled=True,
        local_ollama_chat_base_url="http://host.docker.internal:11434/v1",
        local_ollama_chat_model="datariver-gemma4-dev:0.1",
    )

    assert configured.local_ollama_chat_context_tokens == 8192
    with pytest.raises(ValidationError, match=r"host\.docker\.internal"):
        settings(
            local_ollama_chat_enabled=True,
            local_ollama_chat_base_url="http://example.test:11434/v1",
            local_ollama_chat_model="datariver-gemma4-dev:0.1",
        )
    with pytest.raises(ValidationError, match="only in development"):
        settings(
            app_env="production",
            app_public_origin="https://catalog.example.com",
            app_cors_origins=("https://catalog.example.com",),
            oidc_issuer="https://idp.example.com/realms/data",
            oidc_jwks_url="https://idp.example.com/realms/data/certs",
            datahub_base_url="https://datahub.example.com",
            datahub_version_enforcement="enforce",
            s3_public_endpoint_url="https://objects.example.com",
            local_ollama_chat_enabled=True,
            local_ollama_chat_base_url="http://host.docker.internal:11434/v1",
            local_ollama_chat_model="datariver-gemma4-dev:0.1",
        )


def test_intranet_openai_compatible_inference_is_development_private_tls_only() -> None:
    configured = settings(
        intranet_openai_compatible_allowed_hosts=("10.42.0.15",),
        intranet_openai_compatible_chat_enabled=True,
        intranet_openai_compatible_chat_base_url="https://10.42.0.15/v1",
        intranet_openai_compatible_chat_model="gemma4:latest",
        intranet_openai_compatible_chat_api_key_secret_ref=(
            "file:/run/secrets/intranet_llm_chat_api_key"
        ),
    )

    assert configured.intranet_openai_compatible_chat_enabled is True
    with pytest.raises(ValidationError, match="HTTPS origins"):
        settings(
            intranet_openai_compatible_allowed_hosts=("10.42.0.15",),
            intranet_openai_compatible_chat_enabled=True,
            intranet_openai_compatible_chat_base_url="http://10.42.0.15/v1",
            intranet_openai_compatible_chat_model="gemma4:latest",
            intranet_openai_compatible_chat_api_key_secret_ref=(
                "file:/run/secrets/intranet_llm_chat_api_key"
            ),
        )
    with pytest.raises(ValidationError, match="only in development"):
        settings(
            app_env="production",
            app_public_origin="https://catalog.example.com",
            app_cors_origins=("https://catalog.example.com",),
            oidc_issuer="https://idp.example.com/realms/data",
            oidc_jwks_url="https://idp.example.com/realms/data/certs",
            datahub_base_url="https://datahub.example.com",
            datahub_version_enforcement="enforce",
            s3_public_endpoint_url="https://objects.example.com",
            intranet_openai_compatible_allowed_hosts=("10.42.0.15",),
            intranet_openai_compatible_chat_enabled=True,
            intranet_openai_compatible_chat_base_url="https://10.42.0.15/v1",
            intranet_openai_compatible_chat_model="gemma4:latest",
            intranet_openai_compatible_chat_api_key_secret_ref=(
                "file:/run/secrets/intranet_llm_chat_api_key"
            ),
        )


def test_accepts_secure_production_configuration() -> None:
    configured = settings(
        app_env="production",
        app_public_origin="https://catalog.example.com",
        app_cors_origins=("https://catalog.example.com",),
        oidc_issuer="https://idp.example.com/realms/data",
        oidc_jwks_url="https://idp.example.com/realms/data/certs",
        datahub_base_url="https://datahub.example.com",
        datahub_version_enforcement="enforce",
        s3_public_endpoint_url="https://objects.example.com",
    )

    assert configured.app_env == "production"


def test_production_requires_datahub_version_enforcement() -> None:
    with pytest.raises(ValidationError, match="DataHub version contract"):
        settings(
            app_env="production",
            app_public_origin="https://catalog.example.com",
            app_cors_origins=("https://catalog.example.com",),
            oidc_issuer="https://idp.example.com/realms/data",
            oidc_jwks_url="https://idp.example.com/realms/data/certs",
            datahub_base_url="https://datahub.example.com",
            s3_public_endpoint_url="https://objects.example.com",
        )


@pytest.mark.parametrize("version", ("v1.6.0rc1", "v1.6.0-rc.1", "v1.6", "latest"))
def test_rejects_non_exact_stable_datahub_contract(version: str) -> None:
    with pytest.raises(ValidationError, match="exact stable release"):
        settings(datahub_expected_version=version)


def test_production_uses_the_deployment_configured_stable_datahub_contract() -> None:
    configured = settings(
        app_env="production",
        app_public_origin="https://catalog.example.com",
        app_cors_origins=("https://catalog.example.com",),
        oidc_issuer="https://idp.example.com/realms/data",
        oidc_jwks_url="https://idp.example.com/realms/data/certs",
        datahub_base_url="https://datahub.example.com",
        datahub_version_enforcement="enforce",
        datahub_expected_version="v1.7.0",
        s3_public_endpoint_url="https://objects.example.com",
    )

    assert configured.datahub_expected_version == "v1.7.0"


def test_allows_an_explicit_numbered_rc_for_the_configured_datahub_release() -> None:
    configured = settings(datahub_allowed_versions=("v1.6.0rc1",))

    assert configured.datahub_allowed_versions == ("v1.6.0rc1",)


@pytest.mark.parametrize("allowed_version", ("v1.6.0rc", "v1.6.1rc1", "v1.6.0", "latest"))
def test_rejects_datahub_exceptions_outside_the_configured_release(allowed_version: str) -> None:
    with pytest.raises(ValidationError, match="numbered release candidates"):
        settings(datahub_allowed_versions=(allowed_version,))


def test_ha_accepted_requires_an_explicit_evidence_reference() -> None:
    with pytest.raises(ValidationError, match="deployment evidence"):
        settings(deployment_tier="HA_ACCEPTED")

    configured = settings(
        deployment_tier="HA_ACCEPTED",
        deployment_evidence_reference="release-2026-07-17-ha-drill",
    )
    assert configured.deployment_tier == "HA_ACCEPTED"


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


def test_database_pool_budgets_preserve_current_defaults_and_allow_overrides() -> None:
    defaults = settings()
    configured = settings(
        database_pool_size=6,
        database_pool_max_overflow=2,
        database_pool_timeout_seconds=8,
        database_readiness_timeout_seconds=1,
        worker_database_pool_size=3,
        worker_database_pool_max_overflow=1,
        worker_database_pool_timeout_seconds=7,
    )

    assert (defaults.database_pool_size, defaults.database_pool_max_overflow) == (10, 10)
    assert (
        defaults.worker_database_pool_size,
        defaults.worker_database_pool_max_overflow,
    ) == (5, 5)
    assert (configured.database_pool_size, configured.database_pool_max_overflow) == (6, 2)
    assert (
        configured.worker_database_pool_size,
        configured.worker_database_pool_max_overflow,
    ) == (3, 1)


def test_rejects_readiness_timeout_longer_than_pool_timeout() -> None:
    with pytest.raises(ValidationError, match="readiness timeout"):
        settings(
            database_pool_timeout_seconds=1,
            database_readiness_timeout_seconds=2,
        )


def test_catalog_export_worker_is_disabled_by_default_and_requires_isolated_credentials() -> None:
    assert settings().catalog_export_worker_enabled is False
    with pytest.raises(ValidationError, match="separately provisioned"):
        settings(catalog_export_worker_enabled=True)

    isolated = settings(
        catalog_export_worker_enabled=True,
        export_database_url="postgresql+asyncpg://export@localhost/db",
        export_database_secret_ref="file:/run/secrets/postgres_export_password",
        s3_export_access_key_file="/run/secrets/s3_export_access_key",
        s3_export_secret_key_file="/run/secrets/s3_export_secret_key",
    )
    assert isolated.catalog_export_worker_enabled is True


@pytest.mark.parametrize(
    ("override", "message"),
    [
        (
            {"export_database_url": "postgresql+asyncpg://u@localhost/another"},
            "database credentials must use a separate principal",
        ),
        (
            {"export_database_secret_ref": "file:/run/secrets/postgres_password"},
            "database credentials must use a separate principal",
        ),
        (
            {"s3_export_access_key_file": "/run/secrets/s3_access_key"},
            "S3 credentials must use separate secret files",
        ),
    ],
)
def test_catalog_export_worker_rejects_reused_credentials(
    override: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "catalog_export_worker_enabled": True,
        "export_database_url": "postgresql+asyncpg://export@localhost/db",
        "export_database_secret_ref": "file:/run/secrets/postgres_export_password",
        "s3_export_access_key_file": "/run/secrets/s3_export_access_key",
        "s3_export_secret_key_file": "/run/secrets/s3_export_secret_key",
    }
    values.update(override)
    with pytest.raises(ValidationError, match=message):
        settings(**values)


def test_rejects_ambiguous_or_unsafe_oidc_assurance_mappings() -> None:
    defaults = settings()
    assert defaults.high_risk_auth_max_age_seconds == 300
    assert defaults.admin_password_fallback_enabled is False
    assert defaults.admin_password_fallback_ttl_seconds == 300
    with pytest.raises(ValidationError, match="ACR allowlists must not overlap"):
        settings(oidc_password_reauth_acr_values=("2",))
    with pytest.raises(ValidationError, match="cannot assert hardware assurance"):
        settings(oidc_hardware_amr_values=("webauthn", "otp"))
    with pytest.raises(ValidationError, match="step-up ACR must be in"):
        settings(oidc_step_up_acr="gold")
    with pytest.raises(ValidationError, match="step-up ACR must be one"):
        settings(oidc_step_up_acr="2 gold", oidc_hardware_acr_values=("2 gold",))
