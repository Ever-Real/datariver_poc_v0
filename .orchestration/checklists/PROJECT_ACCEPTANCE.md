# PROJECT_ACCEPTANCE.md

| Area | Current Classification | Acceptance Evidence Required | Owner | Dependency |
|---|---|---|---|---|
| 1 POC principles/scope | PARTIAL | legacy design/function parity, Keycloak-only simplification, real data/open POC permissions and compact badge | 10 | CP-RECON-DOC-001 |
| 2 Deployment/runtime | PARTIAL | npm run poc/native+Compose/LAN bind/env/offline AMD64 source-artifact procedure | 20 | 1 |
| 3 Containers/state stores | IMPLEMENTED_UNVERIFIED | pgvector+Redis+Neo4j Compose/network/health/optional-cache/projection | 20 | 2 |
| 4 Env/external services | IMPLEMENTED_UNVERIFIED | server-side DataHub/Airflow/MinIO/LLM/Grafana contracts without credential exposure | 40 | 2 |
| 5 Dashboard | IMPLEMENTED_UNVERIFIED | live full-inventory counts and provider-failure-vs-zero | 60 | 4 |
| 6 Search/catalog | IMPLEMENTED_UNVERIFIED | live cursor search/autocomplete/tree/detail/profile/lineage | 40 | 4 |
| 7 Registration | PARTIAL | Manual and BULK DataHub readback with MinIO/Airflow state | 40 | 6 |
| 8 CR process | PARTIAL | full CR revision/attachment/return/reapply/test/approval/completion E2E | 40 | 7 |
| 9 Chat | PARTIAL | grounded GENERAL/VECTOR/GRAPH routing, vector/lineage evidence, citations/session memory | 40 | 8 |
| 10 Quality | PARTIAL | DataHub profile/assertion and GX-Airflow-DataHub evidence, no dummy success | 30 | 9 |
| 11 Governance docs | PARTIAL | safe document CRUD/version/publication/editor rendering and sandbox policy | 30 | 10 |
| 12 Glossary | PARTIAL | real DataHub glossary hierarchy and table/column assignments | 40 | 11 |
| 13 Knowledge Studio | PARTIAL | real Knowledge CRUD/version/archive/DataHub/Neo4j projection, no fabricated evidence | 40 | 12 |
| 14 Admin | PARTIAL | persisted user/system/permission/security/retention state with open-POC catalog | 30 | 13 |
| 15 Monitoring | IMPLEMENTED_UNVERIFIED | safe env-driven Grafana tabs and CSP/frame guidance | 50 | 14 |
| 16 Legacy restoration audit | PARTIAL | exact read-only datariver_v0 parity matrix for pages/buttons/API/persistence/error/provider states | 60 | 15 |
| 17 Integrated E2E | MISSING | per-domain current-SHA PASS/FAIL/PRE_EXISTING/NOT_EXECUTED E2E | 50 | 16 |
| 18 Git/PREP/OPS delivery | PARTIAL | clean exact-SHA dev publication plus G3 PREP AMD64 and G4 OPS artifact/checksum evidence | 20 | 17 |
