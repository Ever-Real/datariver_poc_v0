# Phase 9 Governance Document library implementation record

- Date: 2026-07-31
- Scope: document and Template authoring, immutable versions, approval, attachments, safe HTML,
  MinIO artifacts, vector/Neo4j projection and evidence retrieval
- Decision: [ADR-0080](adr/0080-governance-document-library-and-knowledge-projection.md)

## Implemented boundary

Revision `0072` adds eight Governance Document tables with forced RLS, immutable evidence triggers,
maker-checker publication and logical Archive. The browser supports a permission-pruned list,
detail/version history, native rich-text editing, HTML/Markdown/DOCX import, attachments, review,
publish, Archive, published Template instantiation and the three controlled starter blueprints.
HTML is sanitized on the server and rendered through an allowlisted DOM-to-React projection.

The dedicated worker uses its own PostgreSQL and MinIO identities. It stores exact version HTML,
manifest and attachments below `governance/documents/v1/`, records provider VersionIds and verified
checksums, embeds only published text and creates a fixed Neo4j document/version/chunk projection.
The RAG evidence API embeds the server-bounded query using the exact active projection binding and
returns only current authorized published chunks.

## Verification record

Repository Ruff format/lint passed over `511` files, strict mypy passed over `502` source/test
files, and `scripts/verify_static.py` passed the Compose, role, architecture, source-integrity and
documentation checks. The complete backend suite passed `1,955` tests with `104` explicitly
environment-gated skips. Frontend TypeScript and ESLint passed; `68` files / `367` tests passed and
the production build emitted the lazy Policy/Governance chunk at `49.36 kB` (`14.22 kB` gzip).

Two consecutive canonical `0001` generations were byte-identical at SHA-256
`bbe25ca8451f60720c353e5bd70461ef2885fa6b8b5f36ea19732ff4ccdab030`. The running PostgreSQL
`17.10` database accepted the actual `0071 -> 0072` upgrade. Its catalog reported revision `0072`,
all eight Phase 9 tables with both RLS and forced RLS, and both deferred document/version foreign
keys. The `datariver_governance_document` login reported `rolbypassrls=false` and
`rolsuper=false`; it can update only the bounded projection columns and cannot update document
content or delete versions. A live worker claim initially demonstrated that an unscoped joined
`FOR UPDATE` exceeded those grants; the query now locks only `document_versions`, preserving the
least-privilege role.

The local `datariver-filefolder` MinIO bucket reported versioning enabled. The dedicated
governance-document identity passed the real adapter's create, exact-version read-back and
idempotent replay contract, while both prefix listing and exact-version deletion returned
`AccessDenied`. The API reported `{"status":"ready"}` and the dedicated worker remained running
through repeated idle DB/Redis cycles without an error log after the lock-scope and bounded stream
read fixes.

Target production WORM/Object Lock, representative retrieval/load, WSL amd64 and target human
identity evidence remain separate gates; local versioning and create-only application behavior do
not claim regulatory immutability.

## Deferred medium/low items

- adopt a capacity-owner-approved pgvector/ANN profile after extension, dimension, rebuild and
  representative recall/latency evidence are accepted;
- add an operator-owned orphan inventory/reconciliation workflow without granting the application
  list or delete authority;
- add target screen-reader, 200% zoom and 320-CSS-pixel acceptance with real human identities;
- add regulatory Object Lock only after retention duration, legal-hold mapping and storage-owner
  approval exist.
- reconcile the pre-existing Alembic autogenerate drift for
  `governance.manual_metadata_submissions.lease_epoch` and the Knowledge Studio base-release
  deferred foreign key in a later schema-maintenance change; neither operation belongs to the
  Phase 9 tables or the successful `0071 -> 0072` upgrade.
