# ADR-0028: Development system-configuration startup activation

- Status: Accepted
- Date: 2026-07-20
- Refines and supersedes the runtime-source limitation in: ADR-0024

## Context

ADR-0024 allowed safe development YAML persistence and fixed probes but deliberately kept every
long-lived client on deployment Settings. The Mac development installation now needs an explicit,
auditable path from a tested Admin configuration to API and worker clients without hot reload,
browser credentials or a production control-plane claim.

## Decision

Keep the feature development-only. SAVE creates an immutable profile revision containing validated
non-secret YAML and file-mounted secret reference names. Literal passwords, tokens and API keys are
rejected. TEST probes the exact saved revision through a server-owned connector route and records
its status, scope, latency, actor and time. Only an AVAILABLE current revision can be ACTIVATEd;
activation requires the existing eligible global administrator and recent hardware-WebAuthn gate.

ACTIVATE only selects a revision. It does not mutate an existing client or restart a process. When
`SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED=true`, each API/worker process reads the exact
activated revisions for the operator-selected Workspace once during startup using its own
least-privilege, RLS-scoped database principal. The process validates the stored content hash and
then constructs normal typed Settings/clients. A later SAVE, TEST or ACTIVATE has no effect until
the relevant process is explicitly restarted.

The implemented runtime consumers are:

| Profile | Startup consumer |
|---|---|
| DataHub GMS | API and governance-apply worker |
| S3 storage | API and upload/export workers |
| Local OpenAI-compatible Ollama Chat | API |
| DataHub UI, Airflow UI, Prometheus UI, Grafana page | API-published external links |

Embedding, reranker and Neo4j remain storable/testable inventory entries, but ACTIVATE is disabled
until typed runtime adapters exist. Neo4j TEST remains transport-only and cannot be called an
authenticated query test. PostgreSQL bootstrap/OIDC/Valkey and the database used to resolve the
configuration cannot source themselves from this table. Production remains deployment/provider
controlled.

The API reports the version it loaded on its own startup. It does not infer worker restart success;
operators must restart and check each relevant worker. Rollback is an explicit re-save, TEST,
ACTIVATE and restart of a known prior document; version history is retained as evidence.

## Consequences

- TEST, ACTIVATE and APPLIED are distinct states. A successful probe is not a hot-reload or worker
  health claim.
- Runtime processes never receive bootstrap credentials merely to read configuration.
- Adding a new centrally activated connector requires a typed Settings mapping, secret-reference
  boundary, process ownership and tests; adding a menu entry alone is insufficient.
