# ADR-0097: Administrator-approved Monitoring frames

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Application, Security Architecture
- Refines: ADR-0048, ADR-0090
- Supersedes in part: ADR-0095 decisions 3 and 4

## Context

ADR-0095 allows administrators to register provider-neutral Dashboard Links but treats every
non-deployment Grafana origin as external-only. Product policy now defines a successful
fresh-assurance administrator save as approval to present that Dashboard inside its Monitoring
tab. A static Nginx edge cannot construct a per-Workspace CSP from authenticated database rows, and
a third-party site may independently prohibit framing.

## Decision

1. A persisted `platform.monitoring_configurations` row is the Workspace administrator's iframe
   approval document. Each credential-free HTTP(S) descriptor returned from that row receives
   `embed_state=AVAILABLE` and its saved URL as the embed descriptor.
2. The web edge permits `http:` and `https:` in `frame-src`. Only server-returned Monitoring
   descriptors are rendered as frames; the browser cannot create a frame from local state or an
   unsaved input.
3. Every frame remains sandboxed, lazy-loaded and no-referrer, with the existing explicit
   `480..2000` pixel height and an opener-isolated new-window fallback.
4. Registration remains presentation-only. DataRiver never fetches, probes, proxies or
   authenticates to the saved destination and receives no target credentials.
5. A target site's CSP `frame-ancestors` or `X-Frame-Options` is authoritative. DataRiver does not
   attempt to bypass or conceal a target refusal; the UI tells the operator to use the fallback.
6. A deployment-default Grafana page that has not been persisted by an administrator retains the
   original exact-origin, explicit-enable and evidence gate.

## Consequences

- All Dashboard Links saved by an administrator are approved by DataRiver for in-page Monitoring
  presentation, independent of provider.
- Edge `frame-src` is broader than ADR-0095, but frame creation remains constrained to
  server-validated, RLS-protected administrator configuration and active HTTP(S) schemes only.
- External providers such as general public sites may still render blank or refuse connection.
  That behavior is controlled by the provider and is not evidence that DataRiver rejected the
  administrator's approval.
- No schema migration is required.
