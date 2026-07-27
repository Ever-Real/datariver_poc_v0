#!/usr/bin/env python3
"""Render the WSL source-host HTTPS ingress without exposing private upstreams."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "runtime" / "wsl-intranet" / "nginx.conf"
SAFE_NGINX_PATH = re.compile(r"^[A-Za-z0-9_./+@:=,-]+$")


class ConfigurationError(ValueError):
    """The selected environment cannot be published safely."""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Render a CIDR-restricted TLS reverse proxy for WSL source-host development.")
    )
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--certificate", required=True, type=Path)
    parser.add_argument("--certificate-key", required=True, type=Path)
    parser.add_argument(
        "--allowed-cidr",
        action="append",
        required=True,
        help="Approved intranet client CIDR. Repeat for each network.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def read_environment(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(
            f"Environment file must be an existing non-symlink regular file: {path}"
        )
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ConfigurationError(f"Invalid environment assignment at {path}:{line_number}")
        values[key] = value.strip().strip('"')
    return values


def require_https_origin(values: dict[str, str], key: str) -> tuple[str, str]:
    value = values.get(key, "")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(
            f"{key} must be one HTTPS origin on the standard port without a path"
        )
    hostname = parsed.hostname
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if (
            not re.fullmatch(r"[A-Za-z0-9.-]+", hostname)
            or hostname.startswith(".")
            or hostname.endswith(".")
        ):
            raise ConfigurationError(f"{key} contains an invalid hostname") from None
    else:
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ConfigurationError(
                f"{key} cannot use a loopback, unspecified or multicast address"
            )
    return value.rstrip("/"), hostname


def require_port(values: dict[str, str], key: str, default: int) -> int:
    raw_value = values.get(key, str(default))
    try:
        port = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{key} must be an integer") from error
    if not 1 <= port <= 65535:
        raise ConfigurationError(f"{key} must be in the range 1..65535")
    return port


def require_safe_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(f"{label} must be an existing non-symlink regular file: {path}")
    resolved = path.resolve()
    if not SAFE_NGINX_PATH.fullmatch(str(resolved)):
        raise ConfigurationError(f"{label} path contains unsupported characters")
    return resolved


def validate_cidrs(raw_cidrs: list[str]) -> tuple[str, ...]:
    networks: list[str] = []
    for raw_cidr in raw_cidrs:
        try:
            network = ipaddress.ip_network(raw_cidr, strict=False)
        except ValueError as error:
            raise ConfigurationError(f"Invalid --allowed-cidr value: {raw_cidr}") from error
        if network.prefixlen == 0:
            raise ConfigurationError(
                "An unrestricted 0.0.0.0/0 or ::/0 client network is forbidden"
            )
        if network.is_loopback or network.is_unspecified or network.is_multicast:
            raise ConfigurationError(
                f"Loopback, unspecified and multicast client networks are forbidden: {network}"
            )
        canonical = str(network)
        if canonical not in networks:
            networks.append(canonical)
    return tuple(networks)


def proxy_headers() -> str:
    return """\
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
"""


def render_configuration(
    *,
    web_hostname: str,
    oidc_hostname: str,
    web_port: int,
    keycloak_port: int,
    certificate: Path,
    certificate_key: Path,
    allowed_cidrs: tuple[str, ...],
) -> str:
    allow_rules = "\n".join(f"        allow {network};" for network in allowed_cidrs)
    return f"""\
map $http_upgrade $connection_upgrade {{
    default upgrade;
    '' close;
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {web_hostname};
    server_tokens off;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_certificate {certificate};
    ssl_certificate_key {certificate_key};
    client_max_body_size 55m;
    add_header Strict-Transport-Security "max-age=31536000" always;

{allow_rules}
        deny all;

    location / {{
        proxy_pass http://127.0.0.1:{web_port};
{proxy_headers()}    }}
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {oidc_hostname};
    server_tokens off;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_certificate {certificate};
    ssl_certificate_key {certificate_key};
    add_header Strict-Transport-Security "max-age=31536000" always;

{allow_rules}
        deny all;

    location / {{
        proxy_pass http://127.0.0.1:{keycloak_port};
{proxy_headers()}    }}
}}
"""


def write_configuration(output: Path, content: str) -> None:
    if output.exists() and output.is_symlink():
        raise ConfigurationError(f"Output path must not be a symbolic link: {output}")
    output_parent = output.parent
    output_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output_parent.is_symlink():
        raise ConfigurationError(f"Output directory must not be a symbolic link: {output_parent}")
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise ConfigurationError(f"Temporary output already exists: {temporary}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    arguments = parse_arguments()
    try:
        values = read_environment(arguments.env_file)
        if values.get("INTRANET_SOURCE_HOST_ENABLED", "").lower() != "true":
            raise ConfigurationError(
                "INTRANET_SOURCE_HOST_ENABLED=true is required in the selected environment"
            )
        if values.get("APP_ENV", "") != "development":
            raise ConfigurationError(
                "WSL intranet source-host ingress is permitted only with APP_ENV=development"
            )
        web_origin, web_hostname = require_https_origin(values, "APP_PUBLIC_ORIGIN")
        oidc_origin, oidc_hostname = require_https_origin(values, "OIDC_PUBLIC_ORIGIN")
        if web_hostname == oidc_hostname:
            raise ConfigurationError("Web and OIDC public origins must use distinct hostnames")
        expected_authority = f"{oidc_origin}/realms/datariver"
        if values.get("OIDC_PUBLIC_AUTHORITY", "").rstrip("/") != expected_authority:
            raise ConfigurationError(
                "OIDC_PUBLIC_AUTHORITY must match OIDC_PUBLIC_ORIGIN and realm datariver"
            )
        certificate = require_safe_file(arguments.certificate, "Certificate")
        certificate_key = require_safe_file(arguments.certificate_key, "Certificate key")
        allowed_cidrs = validate_cidrs(arguments.allowed_cidr)
        content = render_configuration(
            web_hostname=web_hostname,
            oidc_hostname=oidc_hostname,
            web_port=require_port(values, "WEB_PORT", 38102),
            keycloak_port=require_port(values, "KEYCLOAK_PORT", 18081),
            certificate=certificate,
            certificate_key=certificate_key,
            allowed_cidrs=allowed_cidrs,
        )
        write_configuration(arguments.output, content)
    except (ConfigurationError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"Rendered {arguments.output}")
    print(f"Web origin: {web_origin}")
    print(f"OIDC origin: {oidc_origin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
