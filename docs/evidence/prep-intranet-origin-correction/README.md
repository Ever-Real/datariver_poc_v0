# PREP intranet origin correction evidence

Recorded at `2026-08-27T05:04:23Z` for Product
`661e0a0c571c446ae9c147923a01474065592b2f` on `dev`. The controlled PREP branch `main`
remained fixed at `f042d0d05ac8b57eacd9f9b113b42759b0ac570e` throughout this work.

## Corrected policy

- PREP/OPS continue to publish only DataRiver web on `0.0.0.0:39083`; PostgreSQL, Neo4j and
  Redis host ports remain loopback-only on `127.0.0.1`.
- HTTP requires a literal IP. Loopback, RFC1918 and IPv6 ULA remain accepted defaults.
  `POC_INTRANET_HTTP_ALLOWED_CIDRS` is an operator-owned, comma-separated bounded list of exact
  IPv4/IPv6 CIDRs for reviewed company ranges outside those defaults. Blank adds no range and
  one-host `/32` and `/128` allowances are supported.
- Hostnames, credentials, path/query/fragment, unspecified or multicast addresses, wildcard,
  malformed and unbounded CIDRs fail closed. HTTPS behavior is unchanged.
- The local-authenticator remains the single origin parser used by Product auth and provider
  preflight. Request Origin still has to match `POC_PUBLIC_ORIGIN` exactly.
- Provider preflight/deploy diagnostics preserve distinct sanitized classifications for malformed
  origin, unapproved HTTP origin, and invalid CIDR configuration.
- The setting is operator-owned, not generated or FIXED. Adding it to an accepted target preserves
  PostgreSQL/Neo4j/MCP secrets and does not alter volume, receipt, admin or service identity.

## Verification

- Local auth/provider preflight focused suite: `15/15 PASS`, including RFC1918, approved
  non-RFC1918 `/32`, corporate IPv4 CIDR, corporate IPv6 CIDR, outside-range, malformed CIDR,
  unsafe origin and exact-Origin cases.
- PREP deploy/handoff unit contract: `67/67 PASS`, including typed diagnostic propagation,
  `0.0.0.0` web plus three loopback state binds, loopback health and non-destructive accepted-state
  operator configuration upgrade.
- Node Product server: `146/146 PASS`.
- UI: `90 files / 663 tests PASS`.
- Isolated Docker state/recovery matrix: `1/1 PASS` in `209.52s`, covering fresh, failed-first
  residual, accepted running/stopped and ambiguous fail-closed paths; only the test-owned Compose
  project was cleaned.
- ESLint, TypeScript, standard build, POC build, Ruff check, changed-file Ruff format, strict mypy
  over 580 files, static verification, Python compile, Compose parse, OPS no-build, source diff and
  image credential/proxy scan: `PASS`.
- Repository-wide Python aggregate: `3937 passed / 118 skipped / 55 known baseline failures`.
  The 55 are the same pre-existing strict migration-schema test doubles, DEV-host fixtures and
  unrelated legacy expectations recorded by the prior accepted Evidence; all affected PREP tests
  passed.
- The optional legacy-V4 full-Docker simulation remains unable to create a historical V4 release
  through the current V5 deployer test harness. Current accepted-state upgrade is covered by the
  targeted secret-preservation gate and the isolated accepted running/stopped matrix; Product
  receipt/volume deletion or reset was not introduced.

The exact Product image is `linux/amd64`, carries OCI revision
`661e0a0c571c446ae9c147923a01474065592b2f`, and has image ID
`sha256:2a007791e69db77a703c546d087ed58261f2791139afa3fb35fff39285012ce1`.
The built image imported the exact local-auth and provider-preflight modules and accepted an
operator-approved non-RFC1918 address.

## Deployment

The only Product deployment command remains:

```bash
./scripts/prep39083 deploy
```

No database reset, volume deletion, receipt deletion, runtime-secret regeneration, Windows
Firewall mutation or separate migration/bootstrap command is introduced.

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
