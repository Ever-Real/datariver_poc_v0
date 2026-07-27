from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RENDERER = ROOT / "scripts" / "render_wsl_intranet_nginx.py"


def _write_environment(tmp_path: Path, **overrides: str) -> Path:
    values = {
        "APP_ENV": "development",
        "INTRANET_SOURCE_HOST_ENABLED": "true",
        "APP_PUBLIC_ORIGIN": "https://datariver-prep.example.internal",
        "OIDC_PUBLIC_ORIGIN": "https://identity-prep.example.internal",
        "OIDC_PUBLIC_AUTHORITY": ("https://identity-prep.example.internal/realms/datariver"),
        "WEB_PORT": "38102",
        "KEYCLOAK_PORT": "18081",
    }
    values.update(overrides)
    environment = tmp_path / "source-host.env"
    environment.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    return environment


def _run_renderer(
    tmp_path: Path,
    *,
    environment: Path,
    cidr: str = "10.44.0.0/16",
) -> subprocess.CompletedProcess[str]:
    certificate = tmp_path / "test.crt"
    certificate_key = tmp_path / "test.key"
    certificate.write_text("test certificate\n", encoding="utf-8")
    certificate_key.write_text("test key\n", encoding="utf-8")
    return subprocess.run(  # noqa: S603 - fixed repository script and arguments
        [
            str(ROOT / ".venv" / "bin" / "python"),
            str(RENDERER),
            "--env-file",
            str(environment),
            "--certificate",
            str(certificate),
            "--certificate-key",
            str(certificate_key),
            "--allowed-cidr",
            cidr,
            "--output",
            str(tmp_path / "nginx.conf"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_renderer_keeps_private_upstreams_on_loopback(tmp_path: Path) -> None:
    result = _run_renderer(tmp_path, environment=_write_environment(tmp_path))

    assert result.returncode == 0, result.stderr
    output = tmp_path / "nginx.conf"
    content = output.read_text(encoding="utf-8")
    assert "server_name datariver-prep.example.internal;" in content
    assert "server_name identity-prep.example.internal;" in content
    assert "proxy_pass http://127.0.0.1:38102;" in content
    assert "proxy_pass http://127.0.0.1:18081;" in content
    assert "allow 10.44.0.0/16;" in content
    assert content.count("deny all;") == 2
    assert content.count("Strict-Transport-Security") == 2
    assert "test certificate" not in content
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"APP_PUBLIC_ORIGIN": "http://datariver-prep.example.internal"},
            "APP_PUBLIC_ORIGIN must be one HTTPS origin",
        ),
        (
            {
                "OIDC_PUBLIC_ORIGIN": "https://datariver-prep.example.internal",
                "OIDC_PUBLIC_AUTHORITY": (
                    "https://datariver-prep.example.internal/realms/datariver"
                ),
            },
            "distinct hostnames",
        ),
        (
            {"INTRANET_SOURCE_HOST_ENABLED": "false"},
            "INTRANET_SOURCE_HOST_ENABLED=true",
        ),
        (
            {"APP_ENV": "production"},
            "permitted only with APP_ENV=development",
        ),
    ],
)
def test_renderer_rejects_unsafe_publication(
    tmp_path: Path,
    overrides: dict[str, str],
    message: str,
) -> None:
    result = _run_renderer(
        tmp_path,
        environment=_write_environment(tmp_path, **overrides),
    )

    assert result.returncode == 2
    assert message in result.stderr
    assert not (tmp_path / "nginx.conf").exists()


def test_renderer_rejects_unrestricted_client_network(tmp_path: Path) -> None:
    result = _run_renderer(
        tmp_path,
        environment=_write_environment(tmp_path),
        cidr="0.0.0.0/0",
    )

    assert result.returncode == 2
    assert "unrestricted" in result.stderr
    assert not (tmp_path / "nginx.conf").exists()
