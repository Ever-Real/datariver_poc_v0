# ADR-0066: Explicitly approved public enterprise inference hosts

- Status: Accepted
- Date: 2026-07-28
- Refines: ADR-0030, ADR-0065

## Context

An organisation-operated GenAI gateway can be reachable only through the corporate network while
its approved DNS name intentionally resolves to a globally routable address. Address-class checks
alone therefore cannot distinguish that enterprise gateway from an unapproved public provider.
Removing the private-address requirement globally would silently expand every intranet inference
binding and weaken the existing SSRF and provider-residency boundary.

## Decision

Private, non-loopback DNS resolution remains the default for development intranet inference. Add
the deployment-owned, comma-separated
`INTRANET_OPENAI_COMPATIBLE_APPROVED_PUBLIC_HOSTS` option for exceptional enterprise gateways.
Every entry:

- is an exact hostname, never a URL, wildcard or request-supplied value;
- must also appear in `INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS`;
- applies only to development OpenAI-compatible Chat, Embedding and fixed-route Reranking;
- permits DNS results classified as globally routable while continuing to reject loopback,
  link-local, multicast, unspecified and reserved ranges; and
- becomes part of every affected immutable runtime deployment binding hash.

Startup Settings and the server-owned Admin connection probe both enforce the same address policy.
The existing HTTPS requirement, fixed API route suffixes, safe gateway path validation, mounted
file secrets, redirect prohibition, proxy-environment prohibition and bounded response validation
remain unchanged. Production external inference is not authorized by this option.

## Consequences

- An approved hostname such as `api-genai.corp.example` is deliberately written into both host
  lists; source code contains no company hostname or IP.
- Leaving the new option empty preserves the previous private-only behavior.
- A typo or a public hostname present only in the main allowlist fails closed with an actionable
  validation error.
- DNS/route, enterprise ownership, certificate trust and provider capability remain target
  acceptance evidence; source tests do not claim that the remote gateway is available.
