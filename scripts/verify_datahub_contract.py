from __future__ import annotations

import argparse
import sys

import httpx


def _reported_version(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("response root is not an object")
    versions = payload.get("versions")
    product = versions.get("acryldata/datahub") if isinstance(versions, dict) else None
    version = product.get("version") if isinstance(product, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError("versions.acryldata/datahub.version is missing")
    return version.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify an external DataHub runtime against an approved stable release."
    )
    parser.add_argument("--base-url", required=True, help="DataHub base URL")
    parser.add_argument("--expected-version", default="v1.6.0")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        response = httpx.get(
            f"{args.base_url.rstrip('/')}/config",
            timeout=args.timeout_seconds,
            follow_redirects=False,
        )
        response.raise_for_status()
        observed = _reported_version(response.json())
    except (httpx.HTTPError, ValueError) as error:
        print(f"DataHub version probe failed: {type(error).__name__}", file=sys.stderr)
        return 2
    if observed != args.expected_version:
        print(
            f"DataHub version mismatch: expected={args.expected_version}, observed={observed}",
            file=sys.stderr,
        )
        return 1
    print(f"DataHub version contract matched: {observed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
