#!/usr/bin/env python3
"""Exercise the rendered web Nginx security-header boundary without network pulls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NGINX_VERSION = "nginx version: nginx/1.30.3"
ORIGINS = {
    "S3_PUBLIC_ORIGIN": "https://s3.phase6e.test",
    "OIDC_PUBLIC_ORIGIN": "https://idp.phase6e.test",
    "DATAHUB_EMBED_BASE_URL": "https://datahub.phase6e.test",
    "GRAFANA_EMBED_BASE_URL": "https://grafana.phase6e.test",
}
EXPECTED_CSP = (
    "default-src 'self'; base-uri 'self'; object-src 'none'; "
    "frame-ancestors 'none'; img-src 'self' data:; "
    "style-src 'self'; script-src 'self'; "
    f"connect-src 'self' {ORIGINS['S3_PUBLIC_ORIGIN']} {ORIGINS['OIDC_PUBLIC_ORIGIN']}; "
    f"frame-src {ORIGINS['OIDC_PUBLIC_ORIGIN']} {ORIGINS['DATAHUB_EMBED_BASE_URL']} "
    f"{ORIGINS['GRAFANA_EMBED_BASE_URL']} http: https:; "
    f"form-action 'self' {ORIGINS['OIDC_PUBLIC_ORIGIN']}"
)
EXPECTED_SECURITY_HEADERS = {
    "Content-Security-Policy": EXPECTED_CSP,
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
IMAGE_SOURCE_FILES = {
    ROOT / "frontend" / "nginx.conf.template": "/etc/nginx/templates/default.conf.template",
    ROOT / "frontend" / "nginx-main.conf": "/etc/nginx/nginx.conf",
    ROOT / "frontend" / "docker-entrypoint.sh": "/usr/local/bin/datariver-entrypoint",
}
HEADER_PATTERN = re.compile(r"^\s*([!#$%&'*+\-.^_`|~0-9A-Za-z]+):\s*(.*?)\s*$")
STATUS_PATTERN = re.compile(r"^\s*HTTP/\S+\s+([0-9]{3})(?:\s|$)")
ASSET_PATTERN = re.compile(rb'(?:src|href)="(/assets/[^"]+)"')

UPSTREAM_CONFIG = """\
worker_processes 1;
pid /tmp/nginx-fixture.pid;
error_log /dev/stderr notice;

events {
    worker_connections 64;
}

http {
    access_log /dev/stdout;
    client_body_temp_path /tmp/client_temp;
    proxy_temp_path /tmp/proxy_temp;
    fastcgi_temp_path /tmp/fastcgi_temp;
    uwsgi_temp_path /tmp/uwsgi_temp;
    scgi_temp_path /tmp/scgi_temp;
    add_header_inherit merge;

    server {
        listen 8000;
        server_tokens off;
        default_type application/json;

        add_header Content-Security-Policy "default-src *" always;
        add_header Permissions-Policy "camera=*" always;
        add_header Referrer-Policy "unsafe-url" always;
        add_header X-Content-Type-Options "upstream-conflict" always;
        add_header X-Frame-Options "SAMEORIGIN" always;

        location = /api/v1/success {
            add_header Cache-Control "private, max-age=17" always;
            add_header Content-Disposition 'attachment; filename="fixture.json"' always;
            add_header ETag '"fixture-success"' always;
            add_header Vary "Accept-Encoding" always;
            add_header X-Request-Id "fixture-success" always;
            return 200 '{"state":"ok"}';
        }

        location = /api/v1/error {
            add_header Cache-Control "private, no-store" always;
            add_header Retry-After "17" always;
            add_header WWW-Authenticate 'Bearer error="temporarily_unavailable"' always;
            add_header X-Request-Id "fixture-error" always;
            return 503 '{"state":"unavailable"}';
        }
    }
}
"""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, tuple[str, ...]]
    body: bytes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an offline, native-platform Nginx header acceptance matrix "
            "against the current repository templates."
        )
    )
    parser.add_argument(
        "--web-image",
        default="datariver-next-web:latest",
        help="Already-loaded native web image; the verifier never pulls it.",
    )
    return parser


def _run(
    arguments: list[str],
    *,
    check: bool = True,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(  # noqa: S603 - arguments are fixed or validated Docker identifiers
        arguments,
        cwd=ROOT,
        check=False,
        capture_output=True,
        input=input_data,
    )
    if check and result.returncode != 0:
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
    return result


def _text(arguments: list[str], *, check: bool = True) -> str:
    return _run(arguments, check=check).stdout.decode("utf-8", errors="strict").strip()


def _parse_http_response(raw: bytes) -> HttpResponse:
    header_bytes, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        header_bytes, separator, body = raw.partition(b"\n\n")
    if not separator:
        raise AssertionError(
            f"raw HTTP response has no header boundary:\n{raw.decode('utf-8', errors='replace')}"
        )
    header_text = header_bytes.decode("iso-8859-1")
    status: int | None = None
    headers: dict[str, list[str]] = {}
    for line in header_text.splitlines():
        status_match = STATUS_PATTERN.match(line)
        if status_match:
            status = int(status_match.group(1))
            headers = {}
            continue
        if status is None:
            continue
        header_match = HEADER_PATTERN.match(line)
        if not header_match:
            continue
        name = header_match.group(1).lower()
        headers.setdefault(name, []).append(header_match.group(2))
    if status is None:
        raise AssertionError(f"raw response returned no HTTP status:\n{header_text}")
    return HttpResponse(
        status=status,
        headers={name: tuple(values) for name, values in headers.items()},
        body=body,
    )


def _header_values(response: HttpResponse, name: str) -> tuple[str, ...]:
    return response.headers.get(name.lower(), ())


def _assert_single_header(response: HttpResponse, name: str, value: str) -> None:
    actual = _header_values(response, name)
    assert actual == (value,), (
        f"{name} must appear exactly once with {value!r}; "
        f"status={response.status}, actual={actual!r}"
    )


def _assert_security_headers(response: HttpResponse, csp: str = EXPECTED_CSP) -> None:
    for name, value in EXPECTED_SECURITY_HEADERS.items():
        _assert_single_header(
            response,
            name,
            csp if name == "Content-Security-Policy" else value,
        )


def _request(
    container: str,
    path: str,
    *,
    port: int = 8080,
    request_headers: tuple[str, ...] = (),
    write_hold_seconds: float = 0.25,
) -> HttpResponse:
    if "\r" in path or "\n" in path:
        raise ValueError("HTTP path must not contain a line break")
    for header in request_headers:
        if "\r" in header or "\n" in header:
            raise ValueError("HTTP request header must not contain a line break")
    request = (
        "\r\n".join(
            (
                f"GET {path} HTTP/1.1",
                "Host: localhost",
                "Connection: close",
                *request_headers,
                "",
                "",
            )
        )
    ).encode("ascii")
    arguments = [
        "docker",
        "exec",
        "-i",
        container,
        "nc",
        "-w",
        "6",
        "127.0.0.1",
        str(port),
    ]
    process = subprocess.Popen(  # noqa: S603 - fixed Docker exec and validated port
        arguments,
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    try:
        process.stdin.write(request)
        process.stdin.flush()
        # Give Nginx enough time to dispatch an immediate fixture upstream
        # before closing the client write side. Immediate stdin EOF makes
        # BusyBox nc abort a proxied request and Nginx records 499; leaving it
        # open indefinitely makes nc wait for its final-read timeout.
        time.sleep(write_hold_seconds)
        process.stdin.close()
        raw = process.stdout.read()
        stderr = process.stderr.read()
        process.wait(timeout=8)
    finally:
        if not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
    if not raw:
        raise AssertionError(
            f"raw HTTP probe returned no bytes:\n{stderr.decode('utf-8', errors='replace')}"
        )
    return _parse_http_response(raw)


def _wait_for(
    container: str,
    path: str,
    expected_status: int,
    *,
    port: int = 8080,
) -> HttpResponse:
    deadline = time.monotonic() + 10
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = _request(container, path, port=port)
            if response.status == expected_status:
                return response
        except (AssertionError, RuntimeError) as error:
            last_error = error
        time.sleep(0.1)
    raise RuntimeError(f"{container}{path} did not reach HTTP {expected_status}") from last_error


def _hardened_container_arguments() -> list[str]:
    return [
        "--pull=never",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",  # noqa: S108 - isolated container tmpfs
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
    ]


def _remove_container(name: str) -> None:
    _run(["docker", "rm", "-f", name], check=False)


def _remove_network(name: str) -> None:
    _run(["docker", "network", "rm", name], check=False)


def _assert_cache_tokens(response: HttpResponse, expected: set[str]) -> None:
    tokens = {
        token.strip()
        for value in _header_values(response, "cache-control")
        for token in value.split(",")
        if token.strip()
    }
    assert tokens == expected, (
        f"unexpected Cache-Control tokens for status {response.status}: {tokens}"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_embedded_sources(web_image: str) -> dict[str, str]:
    expected = {
        image_path: _sha256(source_path) for source_path, image_path in IMAGE_SOURCE_FILES.items()
    }
    result = _text(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--entrypoint",
            "sha256sum",
            web_image,
            *expected,
        ]
    )
    actual: dict[str, str] = {}
    for line in result.splitlines():
        digest, separator, image_path = line.partition("  ")
        if not separator:
            raise RuntimeError(f"unexpected sha256sum output: {line!r}")
        actual[image_path] = digest
    if actual != expected:
        raise RuntimeError(
            "web image does not embed the current Nginx source boundary: "
            f"expected={expected}, actual={actual}"
        )
    return actual


def verify(web_image: str) -> dict[str, object]:
    if shutil.which("docker") is None:
        raise RuntimeError("docker executable is required")
    daemon_platform = _text(["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"])
    image_platform = _text(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Os}}/{{.Architecture}}",
            web_image,
        ]
    )
    if daemon_platform != image_platform:
        raise RuntimeError(
            "native-platform evidence is required: "
            f"daemon={daemon_platform}, image={image_platform}"
        )
    image_id = _text(["docker", "image", "inspect", "--format", "{{.Id}}", web_image])
    version_result = _run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network",
            "none",
            "--entrypoint",
            "nginx",
            web_image,
            "-v",
        ]
    )
    version = (
        (version_result.stdout + version_result.stderr).decode("utf-8", errors="strict").strip()
    )
    if version != EXPECTED_NGINX_VERSION:
        raise RuntimeError(f"expected {EXPECTED_NGINX_VERSION!r}, received {version!r}")
    embedded_source_hashes = _verify_embedded_sources(web_image)

    suffix = uuid.uuid4().hex[:12]
    network = f"datariver-nginx-headers-{suffix}"
    upstream = f"datariver-nginx-upstream-{suffix}"
    web = f"datariver-nginx-web-{suffix}"
    created_containers: list[str] = []
    network_created = False
    statuses: dict[str, int] = {}

    with tempfile.TemporaryDirectory(prefix="datariver-nginx-headers-") as temp:
        upstream_config = Path(temp) / "nginx-upstream.conf"
        upstream_config.write_text(UPSTREAM_CONFIG, encoding="utf-8")
        try:
            empty_render = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    *_hardened_container_arguments(),
                    "--network",
                    "none",
                    web_image,
                    "nginx",
                    "-t",
                ]
            )
            empty_render_output = (empty_render.stdout + empty_render.stderr).decode(
                "utf-8", errors="replace"
            )
            if "syntax is ok" not in empty_render_output:
                raise AssertionError("empty-origin rendered Nginx configuration was not accepted")

            _run(["docker", "network", "create", "--internal", network])
            network_created = True
            _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    *_hardened_container_arguments(),
                    "--network",
                    "none",
                    "--entrypoint",
                    "nginx",
                    "-v",
                    f"{upstream_config}:/etc/nginx/nginx.conf:ro",
                    web_image,
                    "-t",
                    "-c",
                    "/etc/nginx/nginx.conf",
                ]
            )
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    upstream,
                    *_hardened_container_arguments(),
                    "--network",
                    network,
                    "--network-alias",
                    "api",
                    "--entrypoint",
                    "nginx",
                    "-v",
                    f"{upstream_config}:/etc/nginx/nginx.conf:ro",
                    web_image,
                    "-g",
                    "daemon off;",
                ]
            )
            created_containers.append(upstream)
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    web,
                    *_hardened_container_arguments(),
                    "--network",
                    network,
                    "-e",
                    "API_PROXY_READ_TIMEOUT_SECONDS=1",
                    *[
                        item
                        for name, value in ORIGINS.items()
                        for item in ("-e", f"{name}={value}")
                    ],
                    web_image,
                ]
            )
            created_containers.append(web)
            _wait_for(upstream, "/api/v1/success", 200, port=8000)
            health = _wait_for(web, "/healthz", 200)

            rendered = _text(["docker", "exec", web, "nginx", "-T"])
            if "${" in rendered:
                raise AssertionError("rendered Nginx configuration contains a placeholder")
            if "add_header_inherit merge;" not in rendered:
                raise AssertionError("rendered Nginx configuration lost header merge")

            root = _request(web, "/")
            runtime = _request(web, "/runtime-config.js")
            spa = _request(web, "/deep/spa/route?case=phase6e")
            asset_match = ASSET_PATTERN.search(root.body)
            if asset_match is None:
                raise AssertionError("index.html contains no hashed asset")
            asset_path = asset_match.group(1).decode("ascii")
            asset = _request(web, asset_path)
            missing_asset = _request(web, "/assets/does-not-exist-phase6e.js")
            api_success = _request(web, "/api/v1/success")
            api_error = _request(web, "/api/v1/error")

            responses = {
                "health": health,
                "runtime": runtime,
                "root": root,
                "spa": spa,
                "asset": asset,
                "missing_asset": missing_asset,
                "api_success": api_success,
                "api_error": api_error,
            }
            expected_statuses = {
                "health": 200,
                "runtime": 200,
                "root": 200,
                "spa": 200,
                "asset": 200,
                "missing_asset": 404,
                "api_success": 200,
                "api_error": 503,
            }
            for name, response in responses.items():
                assert response.status == expected_statuses[name], (
                    f"{name} returned {response.status}, expected {expected_statuses[name]}"
                )
                _assert_security_headers(response)
                assert not _header_values(response, "strict-transport-security"), (
                    f"{name} must not emit Strict-Transport-Security from the inner HTTP server"
                )
                statuses[name] = response.status

            assert root.body == spa.body
            for response in (health, runtime, root, spa):
                _assert_cache_tokens(response, {"no-store"})
            _assert_cache_tokens(
                asset,
                {"public", "immutable", "max-age=31536000"},
            )
            missing_cache = {
                token.strip()
                for value in _header_values(missing_asset, "cache-control")
                for token in value.split(",")
            }
            assert "public" not in missing_cache and "immutable" not in missing_cache
            _assert_single_header(api_success, "Cache-Control", "private, max-age=17")
            _assert_single_header(api_success, "X-Request-Id", "fixture-success")
            _assert_single_header(api_success, "ETag", '"fixture-success"')
            _assert_single_header(api_success, "Vary", "Accept-Encoding")
            _assert_single_header(
                api_success,
                "Content-Disposition",
                'attachment; filename="fixture.json"',
            )
            _assert_single_header(api_error, "Cache-Control", "private, no-store")
            _assert_single_header(api_error, "Retry-After", "17")
            _assert_single_header(
                api_error,
                "WWW-Authenticate",
                'Bearer error="temporarily_unavailable"',
            )
            _assert_single_header(api_error, "X-Request-Id", "fixture-error")

            etag = _header_values(asset, "etag")
            assert len(etag) == 1
            not_modified = _request(
                web,
                asset_path,
                request_headers=(f"If-None-Match: {etag[0]}",),
            )
            assert not_modified.status == 304
            _assert_security_headers(not_modified)
            assert not _header_values(not_modified, "strict-transport-security")
            statuses["asset_not_modified"] = not_modified.status

            _remove_container(upstream)
            created_containers.remove(upstream)
            proxy_down = _request(
                web,
                "/api/v1/success",
                write_hold_seconds=4,
            )
            assert proxy_down.status in {502, 504}, (
                f"proxy-down request returned {proxy_down.status}, expected 502 or 504"
            )
            _assert_security_headers(proxy_down)
            assert not _header_values(proxy_down, "strict-transport-security")
            statuses["api_proxy_down"] = proxy_down.status
        except BaseException:
            if web in created_containers:
                logs = _run(["docker", "logs", web], check=False)
                print(logs.stdout.decode("utf-8", errors="replace"))
                print(logs.stderr.decode("utf-8", errors="replace"))
            raise
        finally:
            for name in reversed(created_containers):
                _remove_container(name)
            if network_created:
                _remove_network(network)

    return {
        "daemon_platform": daemon_platform,
        "image_id": image_id,
        "image_platform": image_platform,
        "nginx_version": version,
        "routes": statuses,
        "source_hashes": embedded_source_hashes,
    }


def main() -> int:
    arguments = _parser().parse_args()
    print(json.dumps(verify(arguments.web_image), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
