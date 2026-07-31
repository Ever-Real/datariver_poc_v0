# ADR-0091: Managed Governance Document viewer, hierarchy and export

- Status: Accepted
- Date: 2026-07-31
- Owners: Data governance, application architecture, security and platform storage

## Context

The Governance page previously mixed three hard-coded policy status presentations with the
immutable Governance Document library. Those presentations were not document aggregates, could not
be versioned or approved, and therefore could not be reused consistently by other services.
Administrators also need readable MinIO object names, explicit parent/child metadata and a bounded
content-plus-metadata export without weakening the existing immutable evidence and ABAC boundary.

## Decision

1. The Governance tabs are `문서 조회` and `문서 관리`. `문서 조회` lists only permission-pruned
   `ACTIVE` `DOCUMENT` aggregates and renders their exact current `PUBLISHED` version.
   `문서 관리` is advertised only when at least one create/edit/review/publish/archive or Template
   management capability is available. Server authorization remains authoritative.
2. `데이터 분류·접근 정책`, `보존·파기 정책` and `Legal Hold 관리` are controlled
   `STARTER_DOCUMENT` blueprints. An authorized human creates each Draft and an independent reviewer
   must approve it before the viewer displays it. No read request silently creates or activates
   business policy.
3. A parent link is immutable metadata of `governance.document_versions`, not mutable metadata of
   the aggregate. The service rejects missing, archived, cross-Workspace, self-referential and
   cyclic parent choices. Parent and child summaries are filtered by the same Workspace,
   classification and System/Domain scope as the document read.
4. The `datariver-filefolder` bucket remains private, versioned and create-only. UUID directories
   continue to prevent collisions and information inference. New document artifact basenames use
   `doc_governance_<normalized-title>_<YYYYMMDD>_<version-serial>.html`; separate Draft-version
   attachments use
   `ref_governance_<normalized-title>_<YYYYMMDD>_<attachment-serial>.<safe-extension>`.
   Provider VersionId, checksum read-back and immutable receipts remain required. Existing V1
   objects are not renamed or copied.
5. `GET /api/v1/governance/documents/{document_id}/export` returns a bounded JSON contract containing
   the selected exact version content, version history, review and attachment metadata, and
   permission-pruned parent/child summaries. It does not expose bucket keys, provider credentials,
   internal endpoints or Presigned URLs.
6. User-facing deletion remains logical `Archive`. Versions, approvals and object evidence are
   never physically deleted or overwritten through the application.

## Consequences

- Revision `0079` adds the versioned parent foreign key and attachment serial/storage filename
  metadata. Existing attachment rows receive deterministic serials and retain a null
  `storage_filename` to identify the legacy physical object layout.
- A fresh Workspace receives controlled starter choices but no falsely approved policy. Deployment
  acceptance creates and approves the three documents with distinct human identities.
- Export consumers receive a stable authorized JSON snapshot and must not treat it as a mutation
  interface or as a substitute for reauthorization at use time.
- Unicode titles are normalized and bounded before forming a basename; UUID path segments and
  exact-version receipts remain the collision and integrity authority.

## Rejected alternatives

- Hard-coded viewer documents were rejected because they bypass version, approval and audit history.
- Automatic ACTIVE seeding was rejected because it would fabricate an approver and violate
  maker-checker publication.
- Using readable names as the entire object key was rejected because renames and concurrent
  registration would create collision and inference risks.
- Physical delete was rejected because it breaks the accepted immutable evidence and recovery
  contract.
