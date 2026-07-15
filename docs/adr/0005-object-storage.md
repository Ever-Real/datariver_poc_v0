# ADR-0005: S3 port with SeaweedFS default

- Status: Accepted
- Date: 2026-07-14

## Decision

Define an S3-compatible object port and use SeaweedFS as the maintained Apache-2.0 local default. Keep external S3/legacy MinIO endpoints as conformance-tested deployment choices, not code assumptions.

## Consequences

Presigned multipart and lifecycle behavior require automated conformance tests. The application database remains the ownership/retention/classification manifest; object-store metadata is not sufficient authorization.
