# Security and ABAC definition

## Trust boundaries and threats

Untrusted inputs include browser/API payloads, OIDC claims before verification, DataHub/provider responses, uploaded files, object metadata, LLM output, graph content, webhook/event duplicates and operator-supplied connection settings. Primary threats are IDOR/cross-workspace access, search existence leakage, privilege escalation, confused-deputy worker actions, SSRF, prompt injection, arbitrary query execution, secret/log exposure, malicious uploads, replay and false workflow completion.

## Identity

- Production accepts asymmetric OIDC JWTs after signature, issuer, audience, expiry, not-before and allowed-algorithm validation.
- Subject ID is `(issuer, sub)` mapped to a DataRiver subject and active workspace membership.
- Workspace comes from the route/header but must match an active membership; a token-provided default does not grant access.
- Administrative/high-classification actions require a recent phishing-resistant authentication
  context. DataRiver recognizes hardware WebAuthn only when the signed token contains an exact,
  deployment-approved ACR and AMR combination plus `auth_time`; generic MFA, OTP and `iat` are not
  substitutes. Password reauthentication never becomes hardware assurance.
- Service identities are separate from users, scoped to one purpose and never impersonate a human approver.
- The browser stores only a versioned authentication intent and a same-origin relative return path.
  It never stores a mutation body, idempotency key or executable callback in OIDC state, and never
  replays an approval/publish operation after WebAuthn. Backend authorization remains authoritative.

## ABAC vocabulary

| Category | Required attributes |
|---|---|
| Subject | workspace, department, groups, job function, clearance, allowed system/domain IDs, auth strength, active |
| Resource | workspace, owner department, system/domain, classification, sensitivity, lifecycle, share scope |
| Action | `catalog.read`, `change.create/review/approve`, `kg.read/edit/publish/share`, `chat.query`, `attachment.download`, `admin.manage`, etc. |
| Environment | time, network zone, client type, authentication age, purpose, request/CR ID |

## Decision algorithm

1. Verify identity and membership.
2. Resolve the protected resource without disclosing forbidden existence.
3. Resolve subject/resource/environment attributes from canonical stores.
4. Evaluate all applicable policy versions; default deny and explicit deny wins.
5. Require workspace equality and clearance/range constraints.
6. Apply separation-of-duties and strong-auth rules.
7. Set transaction-local workspace/subject attributes for PostgreSQL RLS.
8. Apply field-level redaction.
9. Persist decision ID, policy versions and reason codes; a bounded list/Chat evaluation may use one grouped record containing per-resource effects instead of one transaction/row per candidate. Avoid sensitive raw inputs.

## Mandatory policies

- Workspace mismatch always denies.
- Inactive subject, membership, resource or expired grant denies.
- `resource.classification <= subject.clearance` and system/domain assignments must match.
- A requester cannot provide final approval. High-classification publish/apply/share requires two distinct eligible approvers.
- Attachment URL issuance and every actual download perform fresh authorization.
- Search, facets, suggestions, counts, exports and SSE apply the same ABAC scope as detail reads.
- Chat filters evidence before model invocation and re-authorizes citations before response.
- Search cache keys bind workspace, complete subject permission scope, policy version, request shape and projection watermark; non-empty short queries and unescaped wildcard semantics are rejected.
- Policy service failure is fail-closed for protected reads and writes.
- Gateway authentication, DataHub permissions, a UI-hidden button, or graph-database users never substitute for application authorization.

## Query and LLM safety

- LLM output is parsed into strict versioned proposal schemas with size/depth limits.
- Generated SQL/Cypher is never executed. Graph analysis uses approved templates and typed parameters.
- Templates enforce read-only operation, label/relation allowlist, maximum hops/rows/time/cost, statement timeout and database read-only transaction.
- Retrieved documents are data, not instructions. System/tool policy is isolated from evidence and tool output.
- Model requests exclude unauthorized fields and secrets; raw prompts/responses are not production logs.
- External inference remains disabled. The immutable authorized evidence-chunk and fail-closed citation boundary is implemented; the classification-specific Chat matrix, isolated worker and full prompt-injection red-team gate in `14_PRODUCTION_HARDENING.md` still require acceptance.

## API and browser controls

- Strict CORS allowlist; never wildcard with credentials.
- Secure, HttpOnly, SameSite cookies only if a BFF session is used; otherwise short-lived bearer tokens stay in memory.
- CSRF protection for cookie-authenticated mutations.
- Request/body/file limits, rate limits by subject/workspace/product, and bounded decompression.
- Security headers: CSP, frame ancestors, nosniff, referrer policy, HSTS at TLS edge.
- Outbound connector endpoints use approved schemes/hosts, DNS/IP revalidation and private/metadata address blocking to prevent SSRF.

## Secrets and encryption

- Git contains `.env.example` names only. Bootstrap generates strong local secrets into ignored files.
- Production uses secret mounts or a secret manager; DB stores `secret_ref` only.
- No zero/default encryption key fallback. Startup fails when required secret material is missing or weak.
- TLS is mandatory outside a single-host private development network. PostgreSQL/object backups are encrypted and restoration is tested.
- Logs redact Authorization, cookies, provider tokens, presigned URLs, connection strings, prompt content and personal data.

## Upload security

Direct multipart upload enters a private quarantine prefix. Completion validates ownership, object key, content length, MIME, checksum and part manifest. A streaming worker performs malware/type/structure checks before an accepted-state transition. URLs expire within 15 minutes; abandoned multipart uploads and quarantine objects are garbage-collected. Overwrite is disabled unless a new immutable object version is explicitly created.

## Audit requirements

Security-relevant requests record request/trace ID, subject/service identity, workspace, resource/action, decision/effect/reason, policy versions, aggregate version and outcome. Audit events are append-only to normal application roles and protected from payload tampering with chained/batched hashes or external immutable export in production.

## Security acceptance matrix

Tests cover allow and deny for every endpoint/action, cross-workspace IDs, hidden resource `404`, list/count/facet leakage, stale permission cache, revoked grant, self-approval, weak authentication, object URL replay, duplicated idempotency keys, SSRF targets, malicious archive/content, prompt injection and prohibited query clauses. Release requires secret scan, SAST, dependency/image scan, SBOM/license inventory and zero unresolved Critical/High findings.
