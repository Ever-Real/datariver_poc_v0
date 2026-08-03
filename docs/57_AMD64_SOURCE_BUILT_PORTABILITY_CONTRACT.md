# AMD64 source-built portability contract

## Status and scope

P0-A implements the preparation-PC readiness contract. It does not change DataRiver's daily
operator commands, topology, Dockerfiles, Compose files or host-local environment schema. P0-B
(target-native build/cache) and P0-C (topology/backup/selective health) are deliberately deferred.

The delivery boundary is fixed:

- Mac development publishes a clean, verified `dev` commit to `origin/dev`.
- Linux/WSL amd64 preparation fast-forwards that source with the existing `prep-update` command.
- The target host runs source with its own pinned runtime and dependency artifacts.
- Application images, containers and registries are never transferred from development to
  preparation.
- `.env.wsl-intranet-development`, `secrets/`, persistent data and readiness evidence are
  host-local and ignored.

## Stable commands

The operator interface remains:

```bash
./scripts/development_cycle.py prep-update \
  --env-file .env.wsl-intranet-development

./scripts/development_cycle.py prep-check \
  --env-file .env.wsl-intranet-development

# No intervening source, environment or runtime change:
./scripts/development_cycle.py prep-check \
  --env-file .env.wsl-intranet-development
```

`prep-update` alone fetches `origin/dev`, proves a fast-forward, applies migration and identity
bootstrap, starts the source host, checks status and health, and then atomically publishes the
readiness manifest. `prep-check` performs no fetch and no write. It requires the current runtime
evidence to equal the prior successful manifest. The unchanged second `prep-check` is the
idempotence proof. A second `prep-update` is not equivalent because update deliberately reapplies
the host schema, migration, identity bootstrap and runtime start sequence.

## Main checkpoint and operations handoff

The preparation checkout continues to consume only `origin/dev`. After one successful
`prep-update` and two unchanged successful `prep-check` runs, the accepted exact SHA may be promoted
through the reviewed fast-forward checkpoint to `main`. Operations releases are built on a native
Linux amd64 preparation host from that exact clean main checkout with the existing
`scripts/export_release.sh`; the isolated operations PC applies the resulting archive with the
existing `scripts/deploy_pilot.sh`.

This boundary does not permit Docker transfer from Mac development to preparation. The operations
archive is a checksum-bound set of images built natively for the approved main release, not a
`docker export`/`docker commit` capture of running containers. The operations deployer performs no
build or pull and changes its `current` pointer only after migration, bootstrap and health succeed.
Reusing the same archive with the same deploy command is the accepted redeploy interface.

The source-host PostgreSQL prerequisite
`pgvector/pgvector:0.8.2-pg17-bookworm` is separately preloaded and verified as `linux/amd64` on the
preparation host. It is runtime dependency evidence, not application source delivery. Environment
files, secret files, readiness/applied state and persistent volumes remain ignored and host-local
at every boundary.

## Readiness manifest

Path: `runtime/portability/amd64-readiness.json`

The directory and file are private to the host (`0700` and `0600`). The manifest contract is
`DATARIVER_PREPARATION_READINESS_V1` and contains:

| Section | Evidence |
|---|---|
| `source` | `dev`, exact `HEAD`, exact `origin/dev`, approved repository identity |
| `platform` | normalized Linux/amd64 host and Docker server identity |
| `locks` | SHA-256 of `uv.lock`, frontend `package-lock.json`, combined lock hash |
| `toolchain` | Python, uv, Node, npm, Docker and Compose versions plus canonical hash |
| `environment` | file name and key-name-only hashes for canonical/selected schemas |
| `topology` | operator profile and an explicit allowlist of boolean feature switches |
| `database` | sole Alembic head and API-readiness-backed `current=head` proof |
| `capabilities` | allowlisted output of the existing source-host Settings preflight |
| `health` | successful API readiness, Web and loopback OIDC URL/status evidence |
| `recorded_at` | UTC time of the successful atomic publication |

Environment values and their hashes, secret references, credentials, inference model identifiers
and unknown future preflight fields are excluded from both the manifest and operator logs. Only
canonical JSON produced from the explicit capability allowlist is printed; parse failures never
echo raw preflight content. The timestamp is the only field ignored by `prep-check` comparison.

## Failure and retry rules

- Any failure before atomic replacement leaves the last successful manifest untouched.
- A manifest never claims that a failed new checkout is running; its source SHA continues to name
  the last successful runtime.
- A retry through `prep-update` accepts that prior SHA only when it is an ancestor of the current
  checkout. Divergent or malformed evidence fails closed.
- `prep-check` fails when the manifest is missing, when `HEAD` differs from local `origin/dev`, or
  when any recorded evidence differs. The recovery action is a successful `prep-update`, not a
  manual manifest edit.
- The manifest is diagnostic readiness evidence, not production release approval, backup proof or
  an AMD64 performance/soak result.

## P0-A verification checklist

- [x] Daily command names, action choices, default env file and fast-forward semantics preserved.
- [x] Exact source/origin SHA and Linux/amd64 Docker identity bound.
- [x] Lock, toolchain and key-name-only environment schema hashes recorded.
- [x] Bounded topology and existing preflight capabilities recorded without secrets.
- [x] Sole Alembic head compared with packaged revision; API readiness proves current revision.
- [x] Existing API/Web/OIDC health results recorded.
- [x] Atomic/private manifest and failed-replacement preservation directly tested.
- [x] Static contract rejects Docker image transfer commands in the daily workflow.
- [ ] Actual Linux amd64/WSL `prep-update`, first `prep-check` and unchanged second `prep-check`
      evidence captured for one exact `origin/dev` SHA.
- [ ] The accepted preparation SHA is promoted to an exact `main` checkpoint before native amd64
      release export.
- [ ] The operations host verifies and redeploys the same archive with build/pull disabled, health
      success and `current` pointer evidence.
- [ ] P0-B dependency-cache OS/arch/toolchain/lock compatibility evidence implemented.
- [ ] P0-C topology selection, backup checksum and restore evidence implemented.

## Source-only focused gates

These gates can run on the Mac without claiming target readiness:

```bash
.venv/bin/ruff format --check \
  scripts/development_cycle.py backend/tests/unit/test_development_cycle.py \
  scripts/verify_static.py
.venv/bin/ruff check \
  scripts/development_cycle.py backend/tests/unit/test_development_cycle.py \
  scripts/verify_static.py
.venv/bin/mypy scripts/development_cycle.py backend/tests/unit/test_development_cycle.py
.venv/bin/pytest backend/tests/unit/test_development_cycle.py -q
.venv/bin/python scripts/verify_static.py
```

Passing them establishes the P0-A source contract only. Linux amd64 runtime proof remains OPEN
until the preparation operator runs both stable commands on the intended target.
