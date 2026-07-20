# ADR-0024: Workspace access roles and development connection probes

- Status: Accepted
- Date: 2026-07-20
- Refines: ADR-0009, ADR-0011, ADR-0013

## Context

Editing every membership's complete ABAC document is correct but too detailed for routine account
administration. Administrators need reusable role definitions, while the authorization engine must
continue to evaluate the existing membership document rather than trust a browser role name.

The Mac development environment also needs one inventory for non-secret external-system settings
and a safe way to test them. A saved YAML document cannot silently replace deployment settings for
already-running API and worker processes, and an arbitrary URL test endpoint would create an SSRF
surface.

## Decision

Add workspace-owned `iam.access_roles`. A role contains a bounded key and display metadata plus one
typed clearance, group set, Action allow/deny set and System/Domain UUID scopes. Assigning or
removing a role materializes that exact document through the existing version-fenced membership
update service, including the reserved `datariver-role-{role_key}` group marker. The marker is for
display and assignment reconciliation only; it is not independent authority. Runtime access
continues to use the materialized membership document and the ABAC/classification policy engine.

Role definitions contain no credentials. Creation, update, deactivation and assignment require the
same eligible administrator and current hardware-WebAuthn operation as direct membership access.
Self-assignment remains forbidden. A role's security-bearing fields cannot change while any member
uses it; administrators first reassign those members. This avoids an implicit bulk privilege change
that bypasses per-subject reauthorization. Role changes append outbox audit evidence and are
workspace-RLS scoped.

Retain the fixed `platform.external_service_profiles` inventory for development-only non-secret
YAML. Chat, embedding and reranker remain distinct typed service records but the UI groups them as
one LLM area. Saved profiles can be tested only through server-owned connector probes with fixed
paths and protocols. The request supplies a known system identifier, never a URL. Probes reject
embedded credentials and non-routable/reserved targets and report only bounded availability,
authentication-required or unavailable results.

Saved development profiles do not become the configuration source for all running processes in
this decision. Existing long-lived clients still use validated `Settings`, mounted secret
references and deployment wiring. Moving them to per-workspace live profiles requires a separately
reviewed resolver, cache invalidation, client lifecycle, worker routing, secret-provider and
rollback design. The Admin UI and documentation must not claim central runtime management before
that work is complete.

## Consequences

- Routine account administration can define reusable roles and assign one role per membership
  without exposing raw access documents as the primary workflow.
- The advanced membership document remains available for exceptional cases and remains the runtime
  enforcement input.
- A role security change with assigned users fails closed instead of changing many users at once.
- Connection TEST proves only that the saved development profile can complete its fixed probe; it
  is not evidence that every API/worker has hot-reloaded the profile or that production is ready.
- Hardware WebAuthn remains the accepted high-risk mutation control. The UI uses the device-neutral
  name “WebAuthn security key”; removing that control requires an ADR that replaces its assurance
  and two-human invariants rather than a UI-only deletion.
