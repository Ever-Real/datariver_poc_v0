# ADR-0105: Redacted classification-policy summary

- Status: Accepted
- Date: 2026-08-01
- Refines: ADR-0009, ADR-0011

## Context

The Admin classification screen previously loaded the full policy history, active policy and
approved provider profiles as soon as the tab mounted. Those documents contain identifiers,
versions, jurisdiction, maker/checker reasons, hashes and provider metadata. An administrator is
entitled to inspect that detail, but an ordinary authenticated session should not receive it before
fresh assurance. This distinction limits disclosure after session theft or assurance expiry without
removing the administrator's durable authority.

The default screen still needs the current four-class Search/Chat posture. Deriving that posture in
the browser from a full response would make redaction cosmetic and would expose metadata that the
summary does not need.

## Decision

Add `GET /admin/classification-access/policies/current/summary`. It uses the administrator READ
fallback only for an active, RESTRICTED-cleared human in `security-administrators` with an effective
`admin.manage` allow and no explicit deny. After authorization, the transaction sets Workspace and
Subject RLS context and rechecks the canonical eligible-human-administrator membership before
reading policy state.

The response is exactly:

```json
{
  "state": "GOVERNED | STATIC_FLOOR",
  "rules": [
    {"classification": "PUBLIC", "search_mode": "...", "chat_mode": "..."}
  ]
}
```

`rules` contains exactly one row for each of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL` and `RESTRICTED`.
The server uses the existing effective classification resolver, so missing, malformed or unavailable
policy/provider state yields the portable `STATIC_FLOOR`. The response is `private, no-store`.

The summary never contains UUIDs, policy numbers or versions, jurisdiction, grant duration,
provider-profile identifiers, reasons, timestamps, hashes, decision metadata, credentials, URLs,
secret references or deployment identity.

Existing full policy list/current/detail responses and their fresh `admin.manage` assurance remain
unchanged. The browser mounts with only the summary request. **상세 이력 보기** is an explicit
second action: an ordinary session starts the existing hardware or password reauthentication flow
and does not replay the read after return. A user with fresh assurance must select the action again;
only then may the browser request full policy/history/provider documents. Authorization failure or
canonical membership revocation clears detail state instead of retaining a stale sensitive view.

## Consequences

- Default Admin rendering discloses only the current effective four-mode matrix.
- Administrators retain full-detail entitlement, separated from the freshness requirement.
- The server, not role labels, local storage or browser state, remains the authority.
- No schema, migration, bootstrap Role, maker/checker or self-approval behavior changes.
- A future offline audit or delegated security-auditor export remains a separate decision.
