# ADR-0010: Governed retention, Legal Hold and immutable archive boundary

- Status: Accepted
- Date: 2026-07-16
- Refines: ADR-0002, ADR-0005

## Decision

Treat retention policy, Legal Hold, explicit erasure and immutable audit archive as a distinct
governed boundary. PostgreSQL remains canonical for approved policy versions, hold state and
history, erasure requests and approvals, execution attempts, and archive verification receipts.
An object store contains archive bytes but never decides whether data is eligible for retention,
release or erasure.

Retention durations are authored, independently approved, versioned and activated as deployment or
workspace operating data. Values discussed for one installation, including the proposed
30-day/90-day/13-month/7-year profile, are examples of an operating policy input and are not
portable source defaults. No duration value, object lifecycle rule or expired timestamp enables a
delete by itself.

Legal Hold takes precedence over every ordinary expiry and deletion policy. The UI may present a
toggle, but the application translates it into typed place or governed release commands with an
append-only history. Hold release and explicit erasure re-resolve the target, re-evaluate policy and
bind the target version and canonical payload hash. Destructive erasure requires a distinct human
maker and checker, strong authentication, optimistic concurrency and atomic one-time consumption.
Provider keys, bucket names, table names, SQL, HTTP or arbitrary executable payloads are not client
commands.

Define an `ImmutableArchiveStore` application port separate from the existing upload-oriented S3
port. It uses a separate private endpoint, bucket and least-privilege writer credential and exposes
no delete or retention-bypass operation. A successful archive requires a deterministic manifest,
row and byte counts, SHA-256 checksums, an immutable object version identifier, a full content
read-back, and retention/Object-Lock read-back. PostgreSQL records the verified receipt only after
all values agree.

A provider product name, S3 compatibility claim or configured endpoint is not a WORM capability.
The target deployment must prove bucket versioning, Object Lock, compliance-mode retention,
checksum/version behavior, read-back, and rejection of retention shortening and protected-version
deletion. Missing, stale, unsupported or contradictory evidence is an unavailable capability and
fails closed. This rule applies equally to SeaweedFS, MinIO and every other S3-compatible provider.

Automatic deletion, monthly-partition detach/drop and expiry-driven object lifecycle deletion remain
disabled. A future dedicated retention worker may perform a destructive action only when all of the
following are true in the same governed decision:

1. an independently approved policy version is active;
2. no applicable active or release-pending Legal Hold exists;
3. the exact range or resource has a verified immutable archive receipt where archive is required;
4. the provider capability evidence is current and matches the configured endpoint and bucket;
5. the erasure or retention command has valid maker-checker approval and has not been consumed;
6. target version, policy, authorization and worker workspace/correlation scope are revalidated.

Until that worker and its target-environment evidence exist, the observable state is
`DISABLED_NOT_READY`; operators must not restore relay delete privileges or substitute manual
partition drops.

## Rationale

General upload storage permits quarantine cleanup and therefore cannot safely be treated as an
immutable archive merely by enabling a deployment option. Object-store metadata is also neither a
legal decision nor authorization evidence. Separating the port, credentials and canonical receipt
prevents an upload worker, API process or provider label from becoming a deletion or compliance
authority.

Raw personal, confidential or trade-secret content is not automatically placed into a long-lived
WORM archive. The approved policy identifies which audit evidence must be archived, while erasure
receipts retain only the minimum pseudonymized evidence legally permitted. This avoids turning an
audit-preservation control into an unreviewed extension of sensitive-content retention.

## Consequences

- Retention policy and Legal Hold administration require typed APIs, immutable history, ABAC,
  strong authentication and independent approval before destructive execution is introduced.
- Archive capability and restore/conformance tests are deployment gates. Unit tests or a successful
  S3 health check do not establish WORM compliance.
- Archive credentials are not mounted into the API, relay or upload workers and cannot delete an
  archive object or bypass governance retention.
- Explicit approved erasure and automatic expiry retention are separate workflows and may be
  enabled independently; both remain fail-closed on dependency or evidence failure.
- Monthly partitioning is introduced table family by table family. Primary/unique keys, foreign
  keys, late events, future/default partitions, Legal Hold and restore behavior must be proven
  before any detach/drop path exists.
- A partition containing any applicable active hold is initially over-retained rather than partly
  moved or dropped. Optimization cannot weaken the conservative rule.
