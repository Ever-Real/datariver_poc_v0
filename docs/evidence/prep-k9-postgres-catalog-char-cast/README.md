# PREP K9 PostgreSQL catalog `"char"` portability evidence

Recorded: 2026-08-31 (Asia/Seoul)  
Product: `6f2374fb37f1243f0eaba6c025b8d2fb4e0cbc40`

## Preserved PREP state and bounded correction

The prior Product `631a4f5df4dd64104a0668490e4f942d78af587c` successfully converged the preserved
canonical V1 pre-receipt PostgreSQL surface to V5, then failed closed during K9 smoke when
PostgreSQL resolved `text || pg_constraint.contype` ambiguously. Actual PREP was not accessed and
its database, graph, receipts, volumes and failed deployment evidence were not changed.

The runtime correction is one explicit cast in
`frontend/poc-postgres-schema-integrity.mjs`: `constraint_value.contype::text`. No catalog query,
schema DDL, migration ordering, fingerprint constant or acceptance classification was otherwise
changed. A bounded audit found no other reachable system-catalog internal `"char"` value used by
this query family through the failing text `||` operator path.

## Real PostgreSQL regression

PostgreSQL 17 with pgvector 0.8.2 reproduced the uncast statement as SQLSTATE `42725` with
`operator is not unique: text || "char"`. The explicitly cast statement passed twice with the same
deterministic row. The complete real-PostgreSQL schema-integrity suite passed `12/12` and proved:

- the V5 fingerprint remains
  `94708241e9aae3f87a89388a9c86adac3214054c0a37be0f7595544e012eabc5`;
- the already-current V5 state reruns without DDL, receipt rewrite or row mutation;
- canonical pre-receipt V1 still migrates transactionally to V5 with rows and CAS versions intact;
- immutable schema receipts are neither duplicated nor reset;
- missing, malformed, partial, drifted and newer unsupported states remain fail-closed; and
- injected migration or receipt failure still rolls back completely.

Verification results:

- schema-integrity unit tests: `10/10 PASS`;
- real PostgreSQL 17 / pgvector schema-integrity tests: `12/12 PASS`;
- full POC Node suite with isolated PostgreSQL: `248 tests / 247 PASS / 1 isolated Airflow skip / 0 FAIL`;
- touched-file ESLint: PASS;
- `scripts/verify_static.py`: PASS.

The disposable PostgreSQL container and databases were removed after verification. No reset,
resecret, volume deletion, manual DDL, direct receipt change or user-metadata mutation occurred.

## Exact build-once artifact

- image: `datariver-poc:6f2374fb37f1243f0eaba6c025b8d2fb4e0cbc40`
- platform: `linux/amd64`
- archive: `datariver-poc-6f2374fb37f1243f0eaba6c025b8d2fb4e0cbc40-linux-amd64.tar`
- archive size: `124296704` bytes
- archive SHA-256: `5cd925ad91efcf370896a547c23052c3c6c28438abeb059aeb8d52ae3d25f3e3`
- manifest: `sha256:a2eb2383a5e368de77b1c5c5aa234266d363c50862cd5dcb0268911cf143fcad`
- config: `sha256:0dcfa200b24b42da2fde8dcd844fc37afa2f8aed6473c4bac6b27efb3217c46d`
- OCI revision: `6f2374fb37f1243f0eaba6c025b8d2fb4e0cbc40`
- runtime command: `node poc-server.mjs`
- required Node runtime files and entrypoint preflight: PASS

The canonical artifact script built this archive from a separate clean exact `dev` clone. No
previous artifact, frontend-only image, manual Dockerfile or target-side build was used. Actual
PREP doctor, deploy and rerun remain **NOT EXECUTED** by the Control Plane. `origin/main` remains
unchanged at `17f32a52de79077c433bf0beaabac81a48e46062`.
