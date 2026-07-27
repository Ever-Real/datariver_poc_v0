# ADR-0051: WSL intranet source-host HTTPS ingress

- Status: Accepted
- Date: 2026-07-27
- Refines: ADR-0013, ADR-0032, ADR-0034, ADR-0047, ADR-0048

## Context

The preparation PC needs a rapid `linux/amd64` source-validation loop before a version is promoted
to immutable production images. The mutable API, workers and Vite therefore run from the WSL
checkout while PostgreSQL and Keycloak remain containerized. This source-host topology previously
supported only one local browser: every mutable listener and both infrastructure ports were bound
to loopback.

Publishing Uvicorn, PostgreSQL, Redis or Keycloak directly to the corporate LAN would turn a
development convenience into an unreviewed shared deployment. Reusing one hostname for both the
browser and OIDC provider would also make origin, redirect and forwarded-host behavior ambiguous.
The WSL networking layer adds another boundary: mirrored networking can accept LAN traffic
directly, while NAT mode requires a Windows port proxy whose WSL destination address can change.

## Decision

Add an explicit Linux/WSL-only source-host mode:

```text
bootstrap.sh --host-development --intranet-source-host \
  --web-public-origin https://<web-dns-name> \
  --oidc-public-origin https://<identity-dns-name>
```

Both arguments are mandatory, distinct HTTPS origins using the standard port and no path. The
bootstrap writes them only to the operator-selected ignored environment, generates the matching
Keycloak redirect contract and keeps WebAuthn disabled by default under the existing development
policy. It does not choose a DNS name, certificate, CIDR, model or provider credential.

The source API and Vite continue to bind `127.0.0.1`. PostgreSQL, Redis and Keycloak are likewise
reachable from WSL only through loopback host publications. A repository renderer validates the
selected environment, a non-symlink certificate/key, two distinct public names and at least one
bounded client CIDR, then emits two Nginx TLS virtual hosts:

- the Web hostname proxies to loopback Vite;
- the identity hostname proxies to loopback Keycloak;
- both enforce the same explicit client CIDR allowlist, deny all other sources and emit HSTS.

Nginx port `443` is the only DataRiver listener admitted through the WSL/Windows inbound firewall.
The generated file contains certificate paths, not certificate or key bytes. Corporate DNS or a
managed hosts entry maps both names to the preparation PC; the certificate contains both names and
chains to a client-trusted internal CA. The operator must not disable TLS verification.

Windows 11 mirrored networking is preferred for this shared test shape. The Hyper-V firewall uses
one port-443 allow rule scoped to the approved client networks; it does not set a broad default
allow. NAT mode is a documented fallback only: its port proxy publishes 443 and must be refreshed
when the WSL IP changes. Because the TCP proxy does not preserve the original client address, its
Windows Domain firewall becomes the client-CIDR enforcement boundary and Nginx admits only the
exact Windows gateway address observed from WSL. Neither choice changes application authorization,
ABAC, RLS or provider credential boundaries.

The `wsl-preparation` profile remains the immutable offline image/release acceptance profile. This
new mode is `development` source validation and is not production or HA.

## Consequences

- Intranet users can exercise the latest WSL source through stable HTTPS names without exposing
  database, cache, API or identity upstream ports.
- A PostgreSQL container displayed only as `5432/tcp` is diagnosed before migration; it must be
  recreated with `compose.source-host.yaml`, which publishes only WSL loopback and preserves its
  named volume.
- Containerized API/workers must be stopped before source workers start, preventing duplicate
  relays and queue consumers against the same database.
- Keycloak must be recreated and reconciled after the public OIDC origin changes.
- The Nginx renderer rejects production mode, HTTP, same-host Web/OIDC, unrestricted CIDRs,
  symbolic-link inputs and nonstandard public ports.
- Target WSL, corporate DNS/CA, Windows firewall, real browser/OIDC and concurrent user acceptance
  remain external evidence gates. Local source tests cannot close them.
