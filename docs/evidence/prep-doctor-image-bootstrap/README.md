# PREP doctor exact-image bootstrap evidence

Recorded at `2026-08-27T08:22:48Z` for Product
`2fe96238a0bd9f40bfd26f78e45e6cd215f82637` on `dev`. The PREP promotion branch
`origin/main` remained fixed at `d81da424862979a6261a0fee22003edc31125258`.

## Proven root cause and correction

The actual PREP diagnostic established that
`datariver-poc:6021f591d2e47ade387b40d6174d896795126f12` did not exist. Doctor attempted
to start the collect-all child from that absent image, then incorrectly surfaced the launch
failure as `PREP_PREFLIGHT_MATRIX_RESULT_INVALID`. Provider matrix execution never began. This is
the proven root cause; no provider URL, token, proxy, CIDR, DataHub, K9, MCL, GX, Airflow, or MinIO
configuration was changed.

`./scripts/prep39083 doctor` now resolves only `datariver-poc:<Product SHA>` from the canonical
Compose contract. It inspects an existing image before reuse and requires the exact tag,
`linux/amd64`, and matching `org.opencontainers.image.revision`. When the exact image is absent,
doctor builds it through the same canonical Compose build definition and bounded build arguments
used by deploy, then repeats the exact inspection. It never falls back to `latest`, `local`, or an
older Product image. Deploy uses the same preparation/inspection helper and retains its existing
build -> inspect -> read-only provider preflight -> persistent mutation ordering.

Doctor then starts hardened, disposable exact-image children directly with `docker run --rm`, a
read-only root filesystem, the non-root Product user, dropped capabilities, and
`no-new-privileges`. Separate probes distinguish container creation, pinned Node startup, module
startup, and the collect-all process. Only a successfully launched child whose output is not a
bounded matrix can become `PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID`.

The bounded classifications are:

- `PREP_DOCTOR_IMAGE_BUILD_FAILED`
- `PREP_DOCTOR_IMAGE_MISSING`
- `PREP_DOCTOR_IMAGE_IDENTITY_MISMATCH`
- `PREP_DOCTOR_IMAGE_PLATFORM_MISMATCH`
- `PREP_DOCTOR_IMAGE_REVISION_MISMATCH`
- `PREP_DOCTOR_PREFLIGHT_CONTAINER_START_FAILED`
- `PREP_DOCTOR_PREFLIGHT_NODE_START_FAILED`
- `PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID`

Raw Docker or provider stderr is not copied into the operator-facing failure contract.

## Zero Product persistent-state mutation

The isolated Docker regression began with no exact Product image, no runtime environment file, no
PREP project containers, and no PREP project volumes. Doctor built the exact image and executed the
full collect-all matrix. After completion there were still zero project containers and zero
project volumes; no PostgreSQL row, Neo4j node, Redis state, runtime secret, deployment attempt,
accepted marker, or Product service was created. Docker image/cache creation is the only allowed
diagnostic preparation.

The shared helper also passed the forced authenticated-smoke failure -> same-command resume Docker
regression and the historical accepted-release -> descendant upgrade regression. Those tests
preserved target secrets, volumes, bootstrap identities, and durable state. Actual PREP state was
not accessed.

## Verification

- PREP deploy/handoff focused contract: `92/92 PASS`.
- Exact absent-image doctor Docker regression: `1/1 PASS`.
- Forced smoke failure -> same-command resume Docker regression: `1/1 PASS`.
- Historical accepted-state descendant upgrade Docker regression: `1/1 PASS`.
- Node Product server: `167/167 PASS`.
- UI: `90 files / 663 tests PASS`.
- ESLint, TypeScript, standard build, POC build, changed-file Ruff format/lint, strict mypy over
  `578` files, static verification, Python compile, diff-check, and image secret/proxy scan:
  `PASS`.
- Repository-wide Python aggregate: `3962 passed / 120 skipped / 55 known baseline failures`.
  The 55 unchanged failures remain in pre-existing migration-schema/source-host/legacy contract
  test doubles outside this correction. All affected PREP tests passed independently; no global
  all-green claim is made.
- Router/retrieval/reranking semantics changed: `NO`; Router 60 plus Boundary 8 was not rerun.

The exact Product OCI image is `linux/amd64`, carries revision
`2fe96238a0bd9f40bfd26f78e45e6cd215f82637`, and has image ID
`sha256:d1eab70b6c0deb4a00544000bca1565d21b0e609ad47d1e958aadfb4412875cc`. The
pinned Node runtime imports the provider-preflight module successfully. Its final configuration
and history contain no provider credential or credential-bearing proxy value.

The only Product deployment command remains:

```bash
./scripts/prep39083 deploy
```

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
