# Administrator runtime completion checklist

This checklist records the local implementation evidence for the administrator issues completed
under ADR-0046. Target-environment OIDC/WebAuthn ceremonies remain external acceptance gates.

- [x] Document Docker-to-native Ollama Chat base URL as
  `http://host.docker.internal:11434/v1`; document source-host API base URL as
  `http://127.0.0.1:11434/v1`.
- [x] Route deployment-managed PostgreSQL, OIDC, DataHub, Redis, S3, configured LLM, Neo4j and
  UI-link probes through server-owned runtime settings with no client URL or raw exception.
- [x] Keep unsaved draft TEST evidence separate from saved revision TEST evidence.
- [x] Provision three matching local Keycloak identities and Local Development memberships with
  balanced human roles; exclude them from the semiconductor sample Workspace.
- [x] Require WebAuthn, confirmation, idempotency, Workspace locking and outbox evidence for System
  creation.
- [x] Retain Workspace and WebAuthn security boundaries and explain their behavior in My Profile.
- [x] Add bounded per-member CR activity and owned-table APIs with item-level authorization and
  stale/cross-subject cursor rejection.
- [x] Replace the administrator profile placeholders with live, paged CR/table data.
- [ ] Complete a real multi-human OIDC/WebAuthn browser ceremony in the target deployment.
- [ ] Record target-environment provider probes and operational evidence after promotion.
