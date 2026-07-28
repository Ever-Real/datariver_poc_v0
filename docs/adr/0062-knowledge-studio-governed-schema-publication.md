# ADR-0062: Knowledge Studio governed schema and mapping publication

- Status: Accepted
- Date: 2026-07-28
- Owners: Product, Data Architecture, Security, Knowledge Platform
- Refines: ADR-0043, ADR-0058, ADR-0060, ADR-0061

## Context

A passing A-Box pre-flight is useful only when it is tied to the exact Draft, T-Box, mapping and
reviewer that were checked. Publishing the current mutable Draft directly, treating an advisory
response as an approval, or creating an empty `knowledge.releases` instance snapshot would make
schema governance indistinguishable from graph-instance ingestion.

Knowledge Studio also needs a safe physical-source extension point. Browser-supplied file paths,
SQL, connection URLs or credentials cannot become an adapter contract, and a development mock must
not silently make the production runtime appear ready.

## Decision

1. A Studio Draft follows `DRAFT -> REVIEW -> PUBLISHED`, with `DISCARDED` as an audited terminal
   transition available to its author from DRAFT or REVIEW. DRAFT content remains mutable and
   auto-saved; REVIEW content is read-only.
2. Review is maker-checker. The publisher must be a different active human Subject with
   `kg.review` and `kg.publish`, sufficient classification/domain scope and a fresh
   `HARDWARE_WEBAUTHN` assurance. A service account, author self-review or browser-asserted
   assurance cannot publish.
3. Every pre-flight creates an append-only `studio_preflight_checks` receipt for the exact Draft
   version and canonical Studio contract hash. Publication requires a `PASS` receipt created by the
   same independent reviewer. A changed Draft, T-Box, A-Box mapping, source pin or reviewer makes
   the receipt unusable. A composite database foreign key binds the Release source Draft/version,
   contract hash, reviewer and receipt ID; restrictive RLS limits Release insert/archive to the
   current independent publisher.
4. Publication is one database transaction. It materializes one immutable ontology version and
   element index, immutable A-Box binding/rule versions, one `studio_releases` manifest, the
   PUBLISHED Draft evidence, graph schema pointer, outbox event and idempotency result. Canonical
   T-Box and A-Box hashes are read back before commit; any failure rolls back all of them.
5. A graph has a separate `active_studio_release_id`. The previous ACTIVE Studio Release is changed
   to ARCHIVED when a replacement is committed. This does not create or activate a
   `knowledge.releases` instance snapshot, does not change `active_release_id`, does not enqueue
   ingestion and does not write Neo4j. Schema/mapping publication and instance publication remain
   separate truths.
6. CREATE materialization creates the graph only inside the successful publish transaction. EDIT
   publication requires exact graph, ontology, instance-release and active Studio Release base pins;
   drift fails closed. The published endpoint alias remains immutable.
7. Physical row access is exposed through a typed `KnowledgeStudioPhysicalSourceAdapter`. Trusted
   bootstrap code registers an exact Workspace/Asset/source-version/projection-version/field
   allowlist and adapter pair. The application port accepts no query text, path, endpoint or
   credential. CSV and SQLite shells remain explicitly unavailable until an operator-owned
   manifest and credential boundary are approved and injected.
8. Test cleanup uses the ordinary idempotent Discard API and exact ETags. File cleanup is limited to
   manifest-listed, hash-matched, Git-untracked, regular non-symlink files under an explicit
   repository test-artifact root. There is no recursive delete or direct SQL cleanup.

## Consequences

- A PUBLISHED Studio Release is the immutable T-Box/A-Box mapping contract, not evidence that any
  row reached Neo4j. The UI continues to report ingestion as `NOT_RUN`.
- Existing active instance releases remain available while a new schema/mapping contract is
  reviewed or published. A later ingestion pipeline must pin the exact Studio Release and create
  its own fenced job, attempt and instance-release evidence.
- Failed, stale or unavailable pre-flights remain immutable evidence but grant no capability.
- The default runtime continues to return `SOURCE_ROW_READER_UNAVAILABLE` until deployment-owned
  registration exists. Adapter shells are testable interfaces, not mock success paths.
- Revision `0061` is additive and refuses to migrate legacy PUBLISHED Studio Drafts that lack the
  independent-review evidence required by this decision. A downgrade refuses to destroy any
  publication evidence.

## Verification

- Service tests cover independent reviewer success, author/service-account denial and phishing-
  resistant assurance denial.
- Persistence/model checks cover exact receipt/release hashes, immutable version tables, active
  Studio Release linkage, FORCE RLS, least privilege and fail-closed migration/downgrade guards.
- Frontend tests cover REVIEW read-only behavior, exact pre-flight receipt gating, publish/discard
  confirmation, ETag headers and explicit `Ingestion: NOT_RUN`.
- Connection-registry tests cover exact source/version/field/clearance fences, bounded scalar rows,
  unavailable shells and fail-closed probes.
- Cleanup tests cover dry-run-by-default behavior, manifest hash confirmation and exact untracked
  file deletion.
