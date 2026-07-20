# Enterprise UI completion checklist

Status values are `TODO`, `IN PROGRESS`, `DONE`, `BLOCKED API` and `EXTERNAL GATE`.

## Foundation

- [x] `DONE` Read v1 controlled requirements/architecture and inventory v0 reference screens.
- [x] `DONE` Add pinned Tailwind CSS and `@xyflow/react` dependencies.
- [x] `DONE` Configure Tailwind Vite integration and shared navy enterprise utility tokens.
- [x] `DONE` Add reusable Stepper, governed unavailable-state and React Flow canvas components.
- [x] `DONE` Add component tests for role filtering, Stepper mapping and non-zero graph viewport.

## Change Management

- [x] `DONE` Restructure new-CR dialog fields and requester presentation.
- [x] `DONE` Render target table/column hierarchy with inline descriptions and requested changes.
- [x] `DONE` Add safe header-only template download and explicit typed-import capability state.
- [x] `DONE` Preserve private attachment upload and error handling.
- [x] `DONE` Rebuild detail as four-stage Stepper panels.
- [x] `DONE` Load authorized target lineage and render React Flow impact analysis.
- [x] `DONE` Bind reviewer comment to governed action confirmation.
- [ ] `BLOCKED API` Persist edits to an existing intake item; no version-fenced edit endpoint exists.
- [ ] `BLOCKED API` Show generated SQL/result rows; no typed sandbox-test evidence read model exists.

## Knowledge Management

- [x] `DONE` Registry metrics, TanStack asset table, create dialog and selected-asset inspector.
- [x] `DONE` React Flow release preview from authorized snapshots.
- [x] `DONE` Mode A source/direct-definition layout and local safe-subset ontology draft editor.
- [x] `DONE` Mode A visual graph editing, controls and generated non-executing Cypher preview.
- [x] `DONE` Mode B existing-schema/dynamic-one-pass layout with asset/source selection.
- [ ] `BLOCKED API` File/DB extraction, LLM proposal and A-Box job execution; typed proposal/job API
  is absent.
- [x] `DONE` Separate Knowledge GraphRAG Chat route and bounded graph analysis experience.
- [ ] `BLOCKED API` General Chat asset-routing prompt administration; governed prompt/profile contract
  is absent.

## Profile and Admin

- [x] `DONE` Add separate My Profile route and verified profile/capability cards.
- [ ] `EXTERNAL GATE` Name, email and password lifecycle remain organization-IdP managed.
- [x] `DONE` Recompose Users/System tabs from real membership and system-directory APIs.
- [x] `DONE` Consolidate Users, Systems, simple Role, classification, RESTRICTED Search grant,
  provider eligibility and recovery approval under the server-authorized Account/Access workspace.
- [x] `DONE` Collapse full ABAC editing behind an advanced disclosure while retaining its existing
  ETag, confirmation and assurance controls.
- [x] `DONE` Persist workspace Role definitions and assignment through server APIs, RLS, optimistic
  versions and the existing governed membership update service; do not ship client Role fixtures.
- [x] `DONE` Add user inspector with real CR/table counts and access facts.
- [x] `DONE` Keep system assignee writes ETag/assurance/idempotency protected.
- [x] `DONE` Group retention policy, Legal Hold and erasure review under one governance entry;
  preserve their canonical workflows because they are not document-only duplicates.
- [x] `DONE` Add development-only, server-owned secret-free YAML templates and a server-redacted
  saved configuration summary. Reject new browser-supplied secret values and support optimistic
  creation from configuration version zero.
- [x] `DONE` Group Chat/Embedding/Reranker under one LLM selector and add SAVE plus a fixed
  server-side TEST of the saved development profile; do not accept arbitrary probe URLs.
- [x] `DONE` Limit the profile dropdown to grouped server-derived administration entries.
- [ ] `BLOCKED API` IdP user create, system CRUD and schema-scope mapping contracts are absent.
- [x] `DONE` Consolidate Metadata Log and Security Log under one Audit/Log entry with internal tabs;
  keep real empty/error capability states and leave Dictionary separate.
- [x] `DONE` Present classification policy as a four-row table and add real catalog/System target
  selection to RESTRICTED grants. Domain lookup remains blocked until its typed directory API exists.
- [x] `DONE` Replace USB-specific UI wording with device-neutral WebAuthn wording without weakening
  the accepted high-risk mutation assurance contract.
- [x] `DONE` Keep exactly two system responsibilities, `DEVELOPER` and `DATA_STEWARD`, in the canonical
  directory and label both consistently. REVIEW and TEST now require Developer evidence for every
  routed System; FINAL requires role-separated Developer/Data Steward per System plus global Admin.
- [x] `DONE` Retain all four classification policy rows while documenting CONFIDENTIAL/RESTRICTED as
  the current primary operating profile; do not delete or silently remap PUBLIC/INTERNAL.
- [x] `DONE` Add operator-owned single-Workspace presentation and WebAuthn-disable modes. The former
  keeps the server default plus ABAC/RLS; the latter hides enrollment/step-up and refuses hardware
  assurance without creating a password downgrade.
- [x] `DONE` Keep the API client stable across silent token renewal so feature load effects do not
  produce periodic screen-wide flicker; verify the client identity and latest request credentials.
- [ ] `BLOCKED API` Audit export, security-audit read/export and global dictionary mutation contracts
  are absent.
- [x] `DONE` Add server-owned six-calendar-month human membership expiry, final-30-day self-request,
  shared Admin queue and independent WebAuthn-gated decision. Browser time is display-only.
- [x] `DONE` Add versioned development System Settings revisions, persisted TEST evidence and
  explicit ACTIVATE. Implemented connectors load exact activated versions only on API/relevant
  worker restart; unsupported Neo4j/Embedding/Reranker activation remains disabled and explicit.
- [x] `DONE` Resolve CR authority from canonical System assignees and persist immutable snapshots.
  Multi-System REVIEW/TEST/FINAL completion checks fail closed until every required role is covered.

## Verification and delivery

- [x] `DONE` Focused component/API tests for the new shared workflow, CR, Knowledge Chat, profile,
  grouped administrator boundaries and redacted System Settings YAML flow.
- [x] `DONE` Frontend typecheck, ESLint, 36 files / 148 Vitest tests and production build pass.
  The build emitted the existing non-fatal chunk-size warning (`838.50 kB`, gzip `241.83 kB`).
- [ ] `EXTERNAL GATE` Authenticated administrator browser acceptance remains open for the CR modal,
  KG registry/ingestion/chat, Profile, USERS/SYSTEMS, user inspector, logs and dictionary. A separate
  ordinary-user live session and a populated four-stage CR remain target-session gates; component
  tests cover non-admin menu removal and Stepper state without substituting credentials or records.
- [x] `DONE` Update README and completion record with executed evidence and open API gates.
- [x] `DONE` Define separate functional/documentation and test-only commit scopes. Do not mix the
  read-only `datariver_v0` reference or unrelated infrastructure worktree changes into those commits.

## Deliberately open contracts

The `BLOCKED API` and `EXTERNAL GATE` entries above are not incomplete UI placeholders. Their
controls are rendered in a disabled or unavailable state because enabling them would otherwise
fabricate records, bypass canonical ownership or introduce a raw execution/mutation path. Closing
one requires a separately reviewed server contract and its authorization, audit and failure tests.

The post-minification main bundle warning remains a performance backlog item. It does not affect
correctness, but route-level lazy loading should be evaluated separately so that chunking work does
not get mixed into the functional completion commit.
