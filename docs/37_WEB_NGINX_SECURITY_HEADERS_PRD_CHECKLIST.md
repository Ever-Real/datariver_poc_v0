# Phase 6E web Nginx security-header inheritance PRD and checklist

## Purpose and scope

This package closes the local-source portion of `R5-FE-03`. It ensures that the five existing
browser defense-in-depth headers survive every web Nginx `location`, including a location that adds
its own cache header and an Nginx-generated or upstream error response.

It does not change application authorization, CSP trust sources, cross-origin isolation, TLS
ownership or HSTS policy. No API payload, database metadata or migration changes.

## Product, security and operations requirements

| ID | Requirement | Local disposition |
|---|---|---|
| NSH-01 | The exact pinned Nginx `1.30.3` runtime must recursively merge server-level `add_header` values into every nested location. An older or cross-platform image is not accepted by the behavior verifier. | Implemented |
| NSH-02 | CSP, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` and the restricted `Permissions-Policy` each have one canonical `always` rule. | Implemented |
| NSH-03 | CSP retains the existing exact directive vocabulary and deployment variables. This phase adds no wildcard, `unsafe-eval`, credential, browser override or new origin. Runtime-origin validation remains `R5-FE-04`. | Implemented without widening trust |
| NSH-04 | Successful, redirect/not-modified, client-error, upstream-error and Nginx-generated error responses retain all five headers exactly once. | Implemented and locally exercised |
| NSH-05 | The web edge hides only the five upstream browser-security fields before adding its canonical copies. `Cache-Control`, `WWW-Authenticate`, `Retry-After`, `ETag`, `Content-Disposition`, `Vary` and request IDs remain upstream-owned and pass through. | Implemented |
| NSH-06 | Health, runtime configuration and the SPA shell are `no-store`. Hashed asset success remains public/immutable; a missing asset does not receive immutable negative caching; API cache policy remains upstream-owned. | Implemented and locally exercised |
| NSH-07 | Empty optional-origin rendering and populated sentinel-origin rendering must pass `nginx -t/-T`, and the populated output must contain no unresolved `${...}` placeholder. | Implemented and locally exercised |
| NSH-08 | The verifier must use an already-loaded native image with `--pull=never`, an internal temporary network, read-only containers, no added capabilities and exact-name cleanup. Mac arm64 evidence cannot substitute for WSL amd64 evidence. | Implemented |
| NSH-09 | HSTS remains owned and tested by the real HTTPS termination edge. The inner HTTP `:8080` container neither emits HSTS nor proves external TLS policy. | Inner absence locally enforced; external presence remains gated |
| NSH-10 | Source/static/full relevant gates, controlled documents, independent P0/P1 reviews, a focused commit and exclusion of legacy prompt text are required before local closure. | Implemented locally |

## Corrected failure mode

Nginx normally inherits parent `add_header` rules only when the child level declares no
`add_header`. The previous `/runtime-config.js`, `/assets/` and `/` locations each declared only
`Cache-Control`, so they silently replaced the server-level CSP, nosniff, referrer, frame and
permissions rules.

The pinned Nginx version supports `add_header_inherit merge`. A single server-level merge rule is
inherited recursively, so location-specific cache policy can coexist with the canonical five-header
set and future header-defining locations cannot silently recreate the same shadowing behavior.

The API emits four matching defense-in-depth headers for direct access. The web edge now hides all
five canonical browser-security names from the upstream, including any unexpected upstream CSP,
then supplies its own exact values once. This does not hide application cache, authentication,
retry, concurrency, download or trace headers.

## TDD and verification record

### RED evidence

- Before the fix, an actual local Nginx `1.30.3` container returned all five headers on
  `/healthz`, but none on `/runtime-config.js`, `/`, the SPA fallback, a real hashed asset or a
  missing asset `404`.
- The new focused source/parser/safety suite initially failed `3/3`: recursive merge and API
  normalization were absent and the offline live verifier did not exist.

### Current GREEN evidence

| Gate | Result |
|---|---|
| Focused source/parser/safety tests | `3/3` passed |
| Repository static verifier | Passed with recursive merge, exact `always` header, exact five-name API hide set, inner-HSTS rejection and cache-owner checks |
| Empty-origin render | Pinned Nginx `1.30.3` accepted the rendered source with `nginx -t` |
| Populated-origin render | `nginx -T` contained the four sentinel exact origins and no unresolved placeholder |
| Current-source image build/matrix | Local image `datariver-next-web:phase6e`, `linux/arm64`, ID `sha256:d61cabbcf73c731829476f09572ed2b5c9157fb0f44be0cdded4b862613ad88f`, all route/status checks passed. The verifier matched the image-embedded template/main/entrypoint SHA-256 to current source before running without bind-mounted replacements. |
| HTTP status matrix | health/runtime/root/SPA/asset/API success `200`; asset conditional `304`; missing asset `404`; upstream error `503`; removed-upstream timeout `504`. Every direct-inner response omitted HSTS; API success preserved exact `ETag` and `Vary` in addition to cache/download/trace fields. |
| Whole backend | `1,424 passed / 97 environment-gated skipped` |
| Whole frontend | `47` files / `266` tests; strict TypeScript, zero-warning ESLint and production build passed |
| Backend static | Ruff format passed over `384` files; Ruff lint passed; strict mypy passed over `377` source/test/script files |
| Regression stabilization | Existing Governance detail tests now await server detail and attachment-control rendering before asserting. The file passed `18/18` in three concurrent processes, followed by the whole frontend pass. |
| Independent audits | Final security, SRE/test and PM/traceability re-audits independently report `P0=0`, `P1=0` |
| Schema/migration | Not applicable; no metadata or DDL changed |

The local image ID is test evidence, not a promoted multi-architecture release artifact. The current
Dockerfile's moving `apk upgrade` result also remains inside the supply-chain pinning backlog and is
not represented as a reproducible release digest.

## Adversarial checklist

- [x] A location-level `Cache-Control` can no longer shadow the five server security headers.
- [x] Each security field has one exact `always` rule.
- [x] A conflicting upstream CSP/frame/referrer/permissions/nosniff value is removed.
- [x] The API hide set is exactly the canonical five names; an extra hidden application field fails static and unit gates.
- [x] API cache, retry, authentication, `ETag`, `Vary`, request-ID and download headers remain visible.
- [x] Health/runtime/SPA remain no-store.
- [x] Hashed asset success remains immutable while asset `404` is not immutable.
- [x] `200`, `304`, `404`, `503` and Nginx-generated `504` retain the five fields exactly once.
- [x] Empty and populated envsubst render paths pass the pinned runtime parser.
- [x] The verifier rejects a daemon/image platform mismatch and never pulls an image.
- [x] Temporary containers and network use random exact names and are removed without prune/glob.
- [x] Static and live gates reject HSTS emitted by the direct inner HTTP container; they do not
  claim that external TLS/HSTS is configured.
- [x] Full regressions pass with exact current-source counts.
- [x] Final independent security/SRE/traceability audits report `P0=0`, `P1=0`.
- [x] This checklist and its accepted source/test changes form one isolated focused commit.

## Reproduction

Build the native test image from the exact source state and run the offline behavior verifier:

```bash
docker build --pull=false -f frontend/Dockerfile -t datariver-next-web:phase6e .
uv run python scripts/verify_nginx_headers.py --web-image datariver-next-web:phase6e
```

The command refuses an image whose OS/architecture differs from the current Docker daemon. Run it
again on the preparation PC with the loaded `linux/amd64` image; do not force QEMU amd64 on the Mac
and call that WSL acceptance.

## External acceptance gates

The following remain `EXTERNAL_GATE`:

- exact release-source and promoted-image execution on the preparation PC's native
  `linux/amd64` Docker daemon;
- real TLS ingress/load balancer and APISIX preservation or intentional strengthening of every
  header across `2xx/3xx/4xx/5xx`, including one approved HSTS value on HTTPS only;
- Chrome, Firefox and Safari CSP/network-console inspection;
- real OIDC callback/silent-renewal and approved DataHub/Grafana embedding journeys;
- accountable security/operator review of actual public origins and CSP values, which is not
  replaced by the sentinel-origin render test.

## Decision record

This corrects an implementation-level Nginx inheritance defect while preserving the accepted CSP,
embed, proxy and TLS ownership decisions. No new ADR is required. A new ADR is required if a later
change adds a CSP trust source/wildcard, changes nonce/hash policy, enables `unsafe-eval`, moves TLS
or HSTS ownership, introduces cross-origin isolation or changes which edge owns browser security
headers.
