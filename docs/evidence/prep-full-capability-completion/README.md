# PREP Full Capability Completion Evidence

Recorded at `2026-08-27T03:05:17Z` for Product
`322e149a25c3643099e4503f9d8d94def7fa5266` on `dev`. The controlled PREP branch
`main` remained fixed at `a36974981494d6a02bfa5e9168f33652d3acc650`.

## Capability contract

- PREP and OPS publish only DataRiver web on `0.0.0.0:39083`. PostgreSQL, Neo4j and Redis host
  ports remain on `127.0.0.1`. Literal RFC1918 or IPv6-ULA HTTP origins are accepted for the
  deliberate intranet-only mode; public HTTP origins remain rejected.
- The two default managed graphs use Product-owned `K9_POLICIES`, local PostgreSQL policy/run
  state, one shared DataHub snapshot, the existing semantic generation fence and local Neo4j.
  The former `POC_K9_STUDIO_DATABASE_URL` and its `SELECT 1`-only preflight are not production
  requirements. PREP fixes K9 to DAILY/required, bootstraps its distinct service identity, starts
  an initial refresh and requires both graphs plus the semantic index to be READY in smoke.
- Change History uses the configured DataHub Kafka. The Product discovers the cluster identity,
  exactly one supported versioned MCL topic, GMS-internal or explicit external Schema Registry,
  exact value subject/schema hash, provider version and source identity. Only a sanitized receipt
  is persisted. A new source begins at the earliest retained offset; existing checkpoints are
  preserved and bounded backfill resumes from them.
- Quality Read retrieves DataHub Assertion metadata and latest result state through GMS. Zero
  assertions is a valid READY response. Quality Execution checks and reuses the existing fixed
  Airflow `datariver_quality_dispatch` path when configured; otherwise it is DEFERRED. No Kafka,
  Schema Registry, GX, DataHub, Airflow or MinIO container was added.

## Verification

- Node Product server: `145/145 PASS`.
- UI: `90 files / 663 tests PASS`.
- MCL discovery/capture, provider preflight and local-auth focused suite: `30/30 PASS`.
- PREP authenticated smoke suite: `20/20 PASS`.
- PREP deployment/handoff/network suite: `68/68 PASS`.
- K9/bootstrap/change-history scheduler focused suite: `29/29 PASS`.
- Exact DataHub Assertion detail/read projection: `24/24 provider-contract tests PASS`.
- Isolated Docker fresh/residual/running/stopped/ambiguous state matrix: `1/1 PASS` in `202.96s`;
  only the test-owned project was removed during cleanup.
- ESLint, TypeScript, standard build, POC build, Ruff lint, strict mypy over 587 files, static
  verification, Compose parse, source diff and secret/proxy leak scan: `PASS`.
- The repository-wide Python run observed `3930 passed / 118 skipped / 55 failed`; the 55 failures
  are unchanged strict-schema/migration-revision test doubles, DEV-host secret fixtures and
  unrelated legacy environment expectations. All affected PREP deployment tests passed in the
  independent focused suites above.
- Router/retrieval semantics changed: `NO`; Router 60 plus Boundary 8 was not rerun.

The exact image is `linux/amd64`, carries OCI revision
`322e149a25c3643099e4503f9d8d94def7fa5266`, has image ID
`sha256:b3eff730023ef327b15d7e5b7a20e9319fce5384952dbd04e70797c7522510ee`, contains the MCL discovery
runtime adapter, and contains no credential-bearing proxy configuration in its final config/history.

## Deployment

After the target-owned provider/Kafka connectivity values are configured, the only Product command
remains:

```bash
./scripts/prep39083 deploy
```

The V5 environment contract retains V3/V4 attempt-receipt reconstruction, generated secrets,
accepted volumes, retry/resume and 39080 isolation. No database reset, volume deletion, receipt
deletion or separate migration/bootstrap command is introduced.

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
