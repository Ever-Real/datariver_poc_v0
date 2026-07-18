from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID

from pydantic import Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "DataRiver Next"
    app_log_level: str = "INFO"
    app_public_origin: HttpUrl = HttpUrl("http://localhost:8080")
    app_cors_origins: tuple[str, ...] = ("http://localhost:8080",)
    app_trusted_hosts: tuple[str, ...] = (
        "localhost",
        "127.0.0.1",
        "api",
    )
    deployment_tier: Literal["SINGLE_NODE_PILOT", "HA_CANDIDATE", "HA_ACCEPTED"] = (
        "SINGLE_NODE_PILOT"
    )
    deployment_evidence_reference: str | None = Field(default=None, max_length=500)

    database_url: str
    database_secret_ref: str
    migration_database_url: str
    migration_database_secret_ref: str
    relay_database_url: str
    relay_database_secret_ref: str
    upload_database_url: str
    upload_database_secret_ref: str
    governance_database_url: str
    governance_database_secret_ref: str
    export_database_url: str | None = None
    export_database_secret_ref: str | None = None
    bootstrap_database_url: str
    bootstrap_database_secret_ref: str
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_pool_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60)
    database_readiness_timeout_seconds: float = Field(default=1.5, ge=0.1, le=10)
    worker_database_pool_size: int = Field(default=5, ge=1, le=50)
    worker_database_pool_max_overflow: int = Field(default=5, ge=0, le=50)
    worker_database_pool_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60)
    oidc_issuer: str
    oidc_audience: str
    oidc_jwks_url: str
    oidc_allowed_algorithms: tuple[str, ...] = ("RS256", "ES256")
    oidc_hardware_acr_values: tuple[str, ...] = ("2",)
    oidc_step_up_acr: str = "2"
    oidc_hardware_amr_values: tuple[str, ...] = ("webauthn", "hwk")
    oidc_password_reauth_acr_values: tuple[str, ...] = ("1",)
    oidc_password_amr_values: tuple[str, ...] = ("pwd",)
    high_risk_auth_max_age_seconds: int = Field(default=300, ge=60, le=900)
    admin_password_fallback_enabled: bool = False
    admin_password_fallback_ttl_seconds: int = Field(default=300, ge=60, le=300)
    # Development-only: return an ABAC-authorized, no-store Chat exchange when
    # a security administrator is exercising the local UI before retention
    # policy governance is configured. This never permits durable Chat writes.
    chat_ephemeral_admin_without_retention_enabled: bool = False

    datahub_base_url: str
    datahub_secret_ref: str
    # The approved DataHub release is an environment-owned deployment contract.
    # It must never be silently substituted by an application default.
    datahub_expected_version: str
    # A deployment may explicitly allow a numbered release candidate for the
    # same exact stable release while its external DataHub owner completes an
    # upgrade.  This is intentionally empty by default.
    datahub_allowed_versions: tuple[str, ...] = ()
    datahub_version_enforcement: Literal["report", "enforce"] = "report"
    datahub_version_probe_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    datahub_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60)
    datahub_max_concurrency: int = Field(default=20, ge=1, le=200)
    datahub_queue_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30)
    datahub_circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    datahub_circuit_open_seconds: float = Field(default=30.0, ge=1, le=300)
    datahub_stale_ttl_seconds: int = Field(default=900, ge=30, le=86_400)
    ui_datahub_url: HttpUrl | None = None
    ui_airflow_url: HttpUrl | None = None
    ui_grafana_url: HttpUrl | None = None
    ui_prometheus_url: HttpUrl | None = None
    ui_graph_url: HttpUrl | None = None
    datahub_embed_base_url: HttpUrl | None = None
    datahub_embed_enabled: bool = False

    valkey_cache_url: str
    valkey_queue_url: str
    valkey_cache_secret_ref: str
    valkey_queue_secret_ref: str
    cache_default_ttl_seconds: int = Field(default=60, ge=1, le=3600)
    cache_max_value_bytes: int = Field(default=1_048_576, ge=1024, le=1_048_576)
    catalog_search_cache_ttl_seconds: int = Field(default=30, ge=1, le=300)
    catalog_search_minimum_query_length: int = Field(default=2, ge=1, le=20)
    catalog_export_access_ttl_seconds: int = Field(default=86_400, ge=300, le=604_800)
    catalog_export_download_ttl_seconds: int = Field(default=60, ge=60, le=60)
    catalog_export_lease_seconds: int = Field(default=900, ge=60, le=3600)
    catalog_export_maximum_attempts: int = Field(default=4, ge=1, le=20)
    catalog_export_page_size: int = Field(default=1000, ge=100, le=5000)
    catalog_export_maximum_rows: int = Field(default=1_000_000, ge=1, le=5_000_000)
    catalog_export_maximum_bytes: int = Field(
        default=1_073_741_824,
        ge=1_048_576,
        le=5_368_709_120,
    )
    catalog_export_worker_enabled: bool = False
    worker_poll_seconds: float = Field(default=0.5, ge=0.1, le=10)
    outbox_lease_seconds: int = Field(default=30, ge=5, le=300)
    outbox_maximum_attempts: int = Field(default=20, ge=1, le=100)
    event_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        description="Target online retention only; it never enables automatic deletion.",
    )
    upload_lease_seconds: int = Field(default=120, ge=30, le=900)
    upload_maximum_attempts: int = Field(default=8, ge=1, le=20)
    upload_validation_lease_seconds: int = Field(default=300, ge=30, le=3600)
    upload_validation_maximum_attempts: int = Field(default=4, ge=1, le=20)
    governance_apply_lease_seconds: int = Field(default=120, ge=30, le=900)
    governance_apply_maximum_attempts: int = Field(default=8, ge=1, le=20)
    governance_worker_subject_id: UUID = UUID("00000000-0000-7000-8000-000000000001")
    export_worker_subject_id: UUID = UUID("00000000-0000-7000-8000-000000000002")

    s3_endpoint_url: str
    s3_public_endpoint_url: str
    s3_region: str = "us-east-1"
    s3_bucket_quarantine: str
    s3_bucket_accepted: str
    s3_bucket_exports: str = "datariver-exports"
    # Deployment-owned only: no source fallback chooses a metadata bucket.
    s3_bucket_infoschema: str | None = None
    s3_access_key_file: str
    s3_secret_key_file: str
    s3_export_access_key_file: str | None = None
    s3_export_secret_key_file: str | None = None
    presigned_url_ttl_seconds: int = Field(default=900, ge=60, le=900)

    seed_profile: Literal["none", "semiconductor"] = "none"

    @field_validator(
        "app_cors_origins",
        "app_trusted_hosts",
        "oidc_allowed_algorithms",
        "oidc_hardware_acr_values",
        "oidc_hardware_amr_values",
        "oidc_password_reauth_acr_values",
        "oidc_password_amr_values",
        "datahub_allowed_versions",
        mode="before",
    )
    @classmethod
    def parse_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("datahub_expected_version")
    @classmethod
    def require_exact_stable_datahub_version(cls, value: str) -> str:
        normalized = value.strip()
        if re.fullmatch(r"v\d+\.\d+\.\d+", normalized) is None:
            raise ValueError(
                "DataHub expected version must be an exact stable release such as v1.6.0."
            )
        return normalized

    @field_validator("datahub_allowed_versions")
    @classmethod
    def normalize_allowed_datahub_versions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("DataHub allowed versions must be non-empty and unique.")
        return normalized

    @field_validator(
        "ui_datahub_url",
        "ui_airflow_url",
        "ui_grafana_url",
        "ui_prometheus_url",
        "ui_graph_url",
        "datahub_embed_base_url",
    )
    @classmethod
    def reject_ui_link_credentials(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is None:
            return None
        parsed = urlsplit(str(value))
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("External UI links cannot contain user information.")
        return value

    def datahub_lineage_embed_url(self, external_urn: str) -> str | None:
        if not self.datahub_embed_enabled or self.datahub_embed_base_url is None:
            return None
        parsed = urlsplit(str(self.datahub_embed_base_url))
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                f"/dataset/{quote(external_urn, safe='')}/Lineage",
                "",
                "",
            )
        )

    @model_validator(mode="after")
    def validate_security_posture(self) -> Self:
        if "*" in self.app_cors_origins:
            raise ValueError("Wildcard CORS origins are not permitted.")
        if self.valkey_cache_url == self.valkey_queue_url:
            raise ValueError("Cache and queue must use separate Valkey endpoints/databases.")
        if self.datahub_stale_ttl_seconds < self.cache_default_ttl_seconds:
            raise ValueError("The DataHub stale TTL cannot be shorter than the fresh cache TTL.")
        for allowed_version in self.datahub_allowed_versions:
            if (
                re.fullmatch(
                    rf"{re.escape(self.datahub_expected_version)}rc[1-9]\d*", allowed_version
                )
                is None
            ):
                raise ValueError(
                    "DataHub allowed versions must be numbered release candidates for the "
                    "configured exact stable release."
                )
        if self.database_readiness_timeout_seconds > self.database_pool_timeout_seconds:
            raise ValueError("The database readiness timeout cannot exceed the API pool timeout.")
        if self.datahub_embed_enabled and self.datahub_embed_base_url is None:
            raise ValueError(
                "Enabled DataHub embedding requires one configured DataHub embed origin."
            )
        if self.datahub_embed_base_url is not None:
            parsed_embed_url = urlsplit(str(self.datahub_embed_base_url))
            if (
                parsed_embed_url.path not in ("", "/")
                or parsed_embed_url.query
                or parsed_embed_url.fragment
            ):
                raise ValueError(
                    "The DataHub embed URL must be one exact origin without a path or query."
                )
        assurance_sets = {
            "hardware ACR": set(self.oidc_hardware_acr_values),
            "hardware AMR": set(self.oidc_hardware_amr_values),
            "password ACR": set(self.oidc_password_reauth_acr_values),
            "password AMR": set(self.oidc_password_amr_values),
        }
        if any(not values for values in assurance_sets.values()):
            raise ValueError("OIDC assurance claim allowlists cannot be empty.")
        if assurance_sets["hardware ACR"] & assurance_sets["password ACR"]:
            raise ValueError("Hardware and password ACR allowlists must not overlap.")
        if not self.oidc_step_up_acr or any(
            character.isspace() for character in self.oidc_step_up_acr
        ):
            raise ValueError("The OIDC step-up ACR must be one non-empty value.")
        if self.oidc_step_up_acr not in assurance_sets["hardware ACR"]:
            raise ValueError("The OIDC step-up ACR must be in the hardware ACR allowlist.")
        if assurance_sets["hardware AMR"] & assurance_sets["password AMR"]:
            raise ValueError("Hardware and password AMR allowlists must not overlap.")
        unsafe_hardware_references = {"mfa", "otp", "pwd", "password"}
        if assurance_sets["hardware AMR"] & unsafe_hardware_references:
            raise ValueError("Generic MFA, OTP and password cannot assert hardware assurance.")
        credential_urls = {
            "database_url": self.database_url,
            "migration_database_url": self.migration_database_url,
            "relay_database_url": self.relay_database_url,
            "upload_database_url": self.upload_database_url,
            "governance_database_url": self.governance_database_url,
            "bootstrap_database_url": self.bootstrap_database_url,
            "valkey_cache_url": self.valkey_cache_url,
            "valkey_queue_url": self.valkey_queue_url,
        }
        if self.export_database_url is not None:
            credential_urls["export_database_url"] = self.export_database_url
        embedded_passwords = [
            name for name, url in credential_urls.items() if urlsplit(url).password is not None
        ]
        if embedded_passwords:
            raise ValueError(
                "Passwords must not be embedded in URLs: " + ", ".join(sorted(embedded_passwords))
            )
        references = {
            "database": self.database_secret_ref,
            "migration_database": self.migration_database_secret_ref,
            "relay_database": self.relay_database_secret_ref,
            "upload_database": self.upload_database_secret_ref,
            "governance_database": self.governance_database_secret_ref,
            "bootstrap_database": self.bootstrap_database_secret_ref,
            "datahub": self.datahub_secret_ref,
            "valkey_cache": self.valkey_cache_secret_ref,
            "valkey_queue": self.valkey_queue_secret_ref,
        }
        if self.export_database_secret_ref is not None:
            references["export_database"] = self.export_database_secret_ref
        invalid_references = [
            name for name, reference in references.items() if not reference.startswith("file:")
        ]
        if invalid_references:
            raise ValueError(
                "This deployment supports file-mounted secret references only: "
                + ", ".join(sorted(invalid_references))
            )
        if self.catalog_export_worker_enabled:
            if (
                self.export_database_url is None
                or self.export_database_secret_ref is None
                or self.s3_export_access_key_file is None
                or self.s3_export_secret_key_file is None
            ):
                raise ValueError(
                    "Enabled catalog export worker requires separately provisioned "
                    "DB and S3 credentials."
                )
            other_database_urls = {
                self.database_url,
                self.migration_database_url,
                self.relay_database_url,
                self.upload_database_url,
                self.governance_database_url,
                self.bootstrap_database_url,
            }
            other_database_principals = {urlsplit(url).username for url in other_database_urls}
            if (
                self.export_database_url in other_database_urls
                or urlsplit(self.export_database_url).username in other_database_principals
                or self.export_database_secret_ref
                in {
                    self.database_secret_ref,
                    self.migration_database_secret_ref,
                    self.relay_database_secret_ref,
                    self.upload_database_secret_ref,
                    self.governance_database_secret_ref,
                    self.bootstrap_database_secret_ref,
                }
            ):
                raise ValueError(
                    "Catalog export worker database credentials must use a separate principal."
                )
            export_s3_files = {
                self.s3_export_access_key_file,
                self.s3_export_secret_key_file,
            }
            if len(export_s3_files) != 2 or export_s3_files & {
                self.s3_access_key_file,
                self.s3_secret_key_file,
            }:
                raise ValueError(
                    "Catalog export worker S3 credentials must use separate secret files."
                )
        if self.app_env == "production":
            if self.chat_ephemeral_admin_without_retention_enabled:
                raise ValueError("Development-only ephemeral Chat must be disabled in production.")
            if any(value == "*" or value.startswith("*.") for value in self.app_trusted_hosts):
                raise ValueError("Production trusted hosts cannot contain wildcards.")
            external_urls = {
                "app_public_origin": str(self.app_public_origin),
                "oidc_issuer": self.oidc_issuer,
                "oidc_jwks_url": self.oidc_jwks_url,
                "datahub_base_url": self.datahub_base_url,
                "s3_public_endpoint_url": self.s3_public_endpoint_url,
                **{
                    name: str(url)
                    for name, url in {
                        "ui_datahub_url": self.ui_datahub_url,
                        "ui_airflow_url": self.ui_airflow_url,
                        "ui_grafana_url": self.ui_grafana_url,
                        "ui_prometheus_url": self.ui_prometheus_url,
                        "ui_graph_url": self.ui_graph_url,
                        "datahub_embed_base_url": self.datahub_embed_base_url,
                    }.items()
                    if url is not None
                },
            }
            insecure = [
                name for name, url in external_urls.items() if not url.startswith("https://")
            ]
            if insecure:
                raise ValueError(f"Production requires HTTPS for: {', '.join(sorted(insecure))}.")
            if self.seed_profile != "none":
                raise ValueError("Seed profiles cannot be enabled in production mode.")
            if self.datahub_version_enforcement != "enforce":
                raise ValueError("Production must enforce the approved DataHub version contract.")
        if self.deployment_tier == "HA_ACCEPTED" and not self.deployment_evidence_reference:
            raise ValueError("HA_ACCEPTED requires an accepted deployment evidence reference.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
