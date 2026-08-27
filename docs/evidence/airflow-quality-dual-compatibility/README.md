# Airflow Quality DAG dual-compatibility evidence

Recorded at `2026-08-27T10:17:46Z` for Product
`10f2a1fc8436aa8c8e35f2c8a1e0dc8dcf7b0ad8` on `dev`. `origin/main` remained fixed at
`997224da6616f21b34d4efb5fa2e9fd45d106bde`.

## Compatibility boundary

`quality_dispatch.py` imports `dag`, `task`, and `get_current_context` from `airflow.sdk` when the
Airflow 3 public SDK is present. When that module is absent on Airflow 2.10.x, it uses the public
`airflow.decorators` and `airflow.operators.python` locations. The DAG ID, schedule, pause state,
retry policy, timeout, task body, and helper call are unchanged.

`datariver_quality_dispatch.py` and `datariver_quality_auth.py` have identical Git object hashes to
the preceding Handoff. Their HTTP request, response validation, dedicated OIDC client, token cache,
Workspace binding, timeouts, and secret handling were not changed.

## Actual Airflow parse proof

The repository DAG directory was mounted read-only into the official images and the single
`quality_dispatch.py` file was loaded with `DagBag` under the normal DAG-folder Python path.

| Runtime | Official image digest | DAG IDs | Import errors | Result |
|---|---|---|---:|---|
| Airflow 2.10.3 / Python 3.12 | `sha256:a297f7672778ba65d4d95cd1fee0213133ae8d8dd176fe9a697af918f945368f` | `datariver_quality_dispatch` | 0 | PASS |
| Airflow 3.3.0 / Python 3.12 | `sha256:96e99f25815f533b298a4d53f283adf5c84c27334ea16ef232777cb800bddf10` | `datariver_quality_dispatch` | 0 | PASS |

Both parses also verified `is_paused_upon_creation=True` and `max_active_runs=1`. The 2.10.3 and
3.x import surfaces are independently covered by unit tests so removal or accidental reversal of
the compatibility fallback fails deterministically.

## Verification

- Quality DAG/auth/helper focused tests: `9/9 PASS`.
- Local import/compile for `quality_dispatch.py`, `datariver_quality_dispatch.py`, and
  `datariver_quality_auth.py`: `PASS`.
- Actual Airflow 2.10.3 DagBag import/parse: one expected DAG, zero import errors, `PASS`.
- Actual Airflow 3.3.0 DagBag import/parse: one expected DAG, zero import errors, `PASS`.
- Changed-file Ruff format/lint, mypy, static verification and diff-check: `PASS`.
- Repository-wide Python aggregate: `3979 passed / 120 skipped / 55 known baseline failures`.
  The unchanged 55 migration/source-host/legacy failures predate this bounded Airflow correction;
  no global all-green claim is made.
- UI/Node Product runtime source changed: `NO`.

The exact Product OCI is `linux/amd64`, carries revision
`10f2a1fc8436aa8c8e35f2c8a1e0dc8dcf7b0ad8`, and has image ID
`sha256:694c17dd1a27c3d8609a583ad9e919b0af1a1e04df64164046997b7d971cb795`.

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
