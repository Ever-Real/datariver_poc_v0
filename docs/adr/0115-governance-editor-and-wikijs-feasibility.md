# ADR-0115: Preserve the governed TipTap editor; do not adopt Wiki.js

- Status: Accepted
- Date: 2026-08-30
- Owners: Product, Governance, Architecture, Security

## Decision

Keep the current embedded TipTap/ProseMirror editor and make bounded corrections in the
existing governed document workflow. Do not embed, deploy, proxy, or migrate to Wiki.js.

The current editor is intentionally a component inside the existing document aggregate, not an
independent content system. Its actual package inventory is TipTap `3.30.0`, ProseMirror through
`@tiptap/pm` `3.30.0`, `@tiptap/starter-kit` `3.30.0`, and `@tiptap/extension-table` `3.30.0`.
It uses a bounded presentation-token extension and a React safe-node reader. The server receives
canonical HTML, applies its separate allowlist sanitizer, and persists immutable version, review,
hash and object/projection receipts under the existing PostgreSQL-owned contract.

## Current capability assessment

| Requirement | Current state | Decision |
|---|---|---|
| Italic, headings, rich paste | Available through StarterKit, safe paste transform and canonical `<em>` | Retain; exercise the full serialization/sanitization/read path. |
| Tables, row/column operations, cell color | Available through TableKit, bounded commands/context menu and static cell tokens | Retain; no inline CSS or CSP exception. |
| Files | Immutable attachment flow and bounded HTML/Markdown/DOCX ingress already exist | Retain existing object receipts; do not use editor-owned asset storage. |
| Save/load | Immutable versions, optimistic concurrency and exact content hashes | Retain. |
| Approval/versioning | Existing maker-checker lifecycle and audit events | Retain; this is not delegated to an editor. |

## Wiki.js comparison

Wiki.js is a full Node.js wiki application, not a drop-in React editor. Its official materials
advertise visual editing, page history, authentication, storage and search modules, and it is
licensed AGPL-v3. The publicly advertised stable line is 2.5.312 while its 3.x documentation is
explicitly beta/unstable. [Wiki.js product site](https://js.wiki/)
[Wiki.js 3.x Docker guidance](https://beta.js.wiki/docs/install-using-docker)

| Option | Compatibility and governance effect | Decision |
|---|---|---|
| Improve current TipTap/ProseMirror | Preserves canonical HTML, current approvals, versioning, RLS, audit, CSP and closed-network OCI | Chosen. |
| Another embeddable OSS editor | Requires a fresh serializer/sanitizer/table/paste compatibility and migration proof without solving lifecycle ownership | Not justified. |
| Wiki.js as independent service | Requires a new DB/service/auth/role/search/storage/audit integration, synchronization and rollback contracts; introduces operational ownership and AGPL review | Rejected for this program. |
| Replace governance with Wiki.js | Would move or duplicate document truth, approval/versioning and evidence; violates the existing accepted ownership model | Rejected. |

## Required gate before revisiting

Revisit only with an architecture decision that specifies: exact document and approval ownership;
DataRiver-to-Wiki.js identity/role mapping; classification/RLS enforcement point; immutable audit
and version reconciliation; attachment/object receipt ownership; search and file boundaries;
closed-network exact OCI/SBOM/CSP support; AGPL obligations; reversible migration and tested
rollback. A visual-editor gap alone is not sufficient.

## Consequences

- No additional service, database, browser credential, direct DataHub mutation or source of truth
  is introduced.
- User-facing editor work remains a small UI/serializer/sanitizer correction with focused tests.
- Existing TipTap table context-menu behavior remains in scope only when directly needed for its
  accepted table contract; it is not a reason to expand the editor platform.
