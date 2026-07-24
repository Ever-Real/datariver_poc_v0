# Phase 6A WSL bootstrap and connector-network PRD/checklist

## Decision and scope

This phase closes normalized backlog item `R5-DEP-01` and the source-controlled portion of
`NFR-PORT-001`. It corrects two reproducible clean-install blockers without claiming that the
Windows/WSL target has been exercised:

- a non-Mac bootstrap required a DataHub token only after it had copied the environment file and
  generated unrelated secrets; and
- DataRiver Compose models use one externally owned connector network, while documented raw
  state-changing Compose commands did not create that network.

The phase preserves ADR-0033 and ADR-0034. Redis, S3/MinIO, DataHub, Airflow, Neo4j and LLM
providers remain independently placeable. The connector network remains external and is never
removed by a DataRiver Compose project. Native runtime architecture is not forced to `amd64`;
`linux/amd64` remains an explicit release-build/import target.

| Normalized ID | Phase relationship |
|---|---|
| `R5-DEP-01` | implemented source correction and primary exit gate |
| `R1-02` | preserves native `arm64` runtime and explicit `linux/amd64` release/render distinction |
| `R1-05` | preserves optional local or external placement for every connector |
| `R1-08` | improves the runbook but remains open for actual WSL import/restore/start evidence |
| `NFR-PORT-001` | closes the repository-controlled blank-bootstrap defect only |

## Requirements

| ID | Requirement | Acceptance |
|---|---|---|
| WSL-BS-01 | Fail before mutation when a required DataHub token file is absent | no environment, secret or runtime artifact exists after the rejected blank WSL run |
| WSL-BS-02 | Never accept a token value in process arguments | Bash rejects positional input; PowerShell accepts a file path, not a token value |
| WSL-BS-03 | Accept an approved non-empty token file or preserve the installed token | token content is copied with restricted permissions or remains byte-identical and is absent from output |
| WSL-BS-04 | Preserve the development-only Mac placeholder behavior | `--mac-development` can initialize without a production/provider token |
| WSL-NET-01 | Validate the connector-network name before Docker execution | empty, leading-option, dot-only or characters outside `[A-Za-z0-9_.-]` fail before a Docker call |
| WSL-NET-02 | Create the external network before `up`, `run`, `create` or `start` | wrapper order is inspect, conditional create, then Compose |
| WSL-NET-03 | Make network provisioning idempotent and non-destructive | an existing network is reused; wrappers never modify or delete it |
| WSL-NET-04 | Use the same ownership model in core and optional connector Compose files | both models declare the named network `external: true` |
| WSL-DOC-01 | Give blank Linux/WSL and Windows operators a secret-safe first-use path | documentation stages an approved file and uses the platform wrapper |
| WSL-PORT-01 | Keep evidence architecture-honest | local source/render checks do not close WSL Docker Desktop, ACL or runtime gates |

## Operational contract

On Linux, macOS and WSL, operators invoke `scripts/compose.sh`; native Windows uses
`scripts/compose.ps1`. Both wrappers read the selected environment file, validate
`DATARIVER_CONNECTOR_NETWORK`, create it only when a state-changing Compose command needs it, and
then delegate to Docker Compose. Read-only `config` does not mutate Docker state.

First-use DataHub credentials are supplied as files:

```bash
install -d -m 700 secrets
./scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --datahub-token-file /approved-secure-transfer/datahub_token
```

```powershell
./scripts/bootstrap.ps1 -DataHubTokenFile 'C:\approved-secure-transfer\datahub_token'
```

The source file path is safe to appear in process metadata; the token content is not. Operators
must not use a command-line token value, `.env`, source control or logs as a secret channel.

## TDD checklist

- [x] Reproduce the blank WSL failure and its pre-fix environment/runtime/25-secret residue.
- [x] Add a negative test requiring a missing token failure before all persistent mutation.
- [x] Add a positive test for a preinstalled token and verify it is preserved and not printed.
- [x] Add file-path ingestion and positional-token rejection tests.
- [x] Add a mocked-Docker ordering test for inspect, first create, Compose and idempotent replay.
- [x] Add invalid-network rejection before Docker execution.
- [x] Add Bash/PowerShell source-contract parity coverage.
- [x] Make the optional connector Compose model use the same external network owner.
- [x] Run shell syntax checks. `pwsh` is unavailable on the current Mac, so PowerShell
  parser/execution remains an explicit target gate.
- [x] Run focused and full backend quality gates plus static verification.
- [x] Render native and `DOCKER_DEFAULT_PLATFORM=linux/amd64` Compose matrices.
- [x] Obtain independent final security, portability and PM/traceability P0/P1 reviews.

## Local executed evidence

- Bootstrap/wrapper unit tests: `15 passed`; the new cases cover no-mutation rejection,
  preinstalled/file-sourced token handling, output non-disclosure, positional rejection, Docker
  call ordering, repeat/config-only execution, invalid names, same-file preservation,
  symlink/reparse rejection, PowerShell source parity and external-network declarations.
- Full backend: Ruff format over `377` files, Ruff lint, strict mypy over `370` source files,
  static verification and `1,380 passed / 84 environment-gated skipped`.
- Frontend regression: TypeScript, zero-warning ESLint, `45 files / 243 tests` and production build.
- Shell parsing: `bootstrap.sh`, `compose.sh` and `ensure_connector_network.sh` pass `sh -n`.
- Compose configuration: native and `DOCKER_DEFAULT_PLATFORM=linux/amd64` base, local-connector
  and full-overlay models all pass `config --quiet`.
- Native PowerShell parsing and execution were not run because `pwsh` is absent. Actual Docker
  network creation was tested through a deterministic fake-Docker call log; target-daemon
  execution remains external.
- Independent security and portability re-reviews report `P0=0`, `P1=0`; accepted findings were
  corrected and the focused gates rerun. PM/traceability review confirms no raw legacy
  prompt/attachment content entered the change set.

## Residual hardening

- `R5-DEP-05`: existing external-network driver/scope/ownership conformance is a target operations
  check; wrappers deliberately do not mutate an existing external network.
- `R5-DEP-02`: existing token hard-link detection and exact native Windows reparse/ACL behavior
  require platform-specific evidence. Symbolic links and reparse points are rejected in source.
- `R5-DEP-05`: argument scanning can conservatively provision the network when a later argument
  equals a state-changing command; this is an idempotent extra check, not an authorization bypass.

## External acceptance

The following remain `EXTERNAL_GATE`:

- a clean clone and first bootstrap inside the target WSL distribution;
- Windows filesystem/WSL mount permission and native PowerShell ACL verification;
- target Docker Desktop network creation and container attachment;
- exact amd64 image import, PostgreSQL restore/Alembic head, Keycloak issuer and browser sign-in;
- external DataHub, S3/MinIO, Redis, Neo4j and private OpenAI-compatible provider DNS/TLS/IAM; and
- representative target resource, restart, rollback and soak evidence.

No local arm64 test or Compose render is reported as evidence for those gates.
