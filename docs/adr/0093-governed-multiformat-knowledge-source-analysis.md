# ADR-0093: Governed multi-format Knowledge source analysis

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Knowledge Platform, Application, Security Architecture
- Refines: ADR-0044, ADR-0072, ADR-0074, ADR-0083, ADR-0092

## Context

The Knowledge Asset operating model already accepts bounded PDF, CSV, TXT, JSON, XML, HTML,
DOCX, XLSX and PPTX documents when inferring a T-Box Proposal. A-Box file enrichment, however,
still accepted only PDF even though it used the same immutable upload, fenced worker, typed
extraction and DRAFT Changeset boundary. Users therefore had to convert an otherwise supported
document before they could extract governed instances from it.

Adding a second browser-side parser or a synchronous inference route would duplicate truth and
discard the lease, retry, stale, cancellation and provenance guarantees of the existing
source-analysis worker. Accepting legacy DOC/XLS, macros, external OpenXML links, XML entities or
unbounded extracted text would weaken the current upload boundary.

## Decision

The existing Knowledge source-analysis job is generalized from PDF-only to a governed document
source. It remains the only file-to-A-Box LLM path and still produces only a typed DRAFT
Changeset.

The accepted format vocabulary is:

- PDF (`application/pdf`);
- UTF-8 CSV and TXT;
- JSON;
- XML without DTD or entity declarations;
- HTML/XHTML text;
- macro-free DOCX, XLSX and PPTX OpenXML packages.

Legacy DOC and XLS are not accepted. Filename extension and declared media type must agree.
Uploads remain integrity verified, immutable, private-object-store snapshots and are limited to
50 MiB. Classification remains capped at INTERNAL for the currently activated inference route.

PDF retains physical page boundaries. Other formats are converted by a server-owned bounded
parser into deterministic evidence segments. Each segment has a stable ordinal and content hash,
and the combined extracted text remains subject to the existing total character, provider batch
and typed operation limits. Browser input cannot select a parser, URL, object key, SQL, Cypher or
provider credential.

The durable job continues to pin:

- Workspace, graph, upload and source snapshot;
- exact object version, byte count and SHA-256;
- graph/base Release and ontology checksum;
- parser configuration hash;
- embedding and extraction model bindings;
- requester authorization and source classification.

Worker completion continues to create provenance-bearing typed node/edge operations in a DRAFT
Changeset. The model cannot publish a Release or write Neo4j. Independent review, publication and
optional verified shadow projection are unchanged.

This decision does not approve full DB/CSV batch ingestion through Studio bindings. That path
still requires a deployment-owned physical source manifest, batch reader, worker attempts/events,
lease fencing, source read-back and a separate refining ADR/migration.

## Consequences

- Users can enrich an approved T-Box from the same modern document formats used for schema
  proposals without a lossy PDF conversion.
- One upload and worker state machine remains canonical; there is no alternate synchronous LLM
  mutation route.
- Existing PDF jobs and APIs remain compatible. New jobs use a new parser-configuration hash and
  cannot be replayed under the previous parser binding.
- The response field historically named `page_count` represents bounded evidence segments for
  non-PDF sources. The API field remains for backward compatibility; UI wording is format-neutral.
- DB binding preview and PENDING ingestion control-plane limitations remain visible and are not
  represented as completed materialization.

## Verification

- Parser tests cover Unicode text segmentation, safe OpenXML extraction, unsupported media and
  XML entity rejection.
- Upload validation tests cover each newly accepted format, extension/MIME mismatch, macro and
  legacy-format rejection.
- Worker tests prove a non-PDF immutable source follows the same claim, checkpoint, stale,
  extraction and DRAFT finalization path.
- Frontend tests cover the format allowlist, canonical MIME selection, size bound and unchanged
  multipart/analyze request sequence.
- Ruff, strict mypy, backend pytest/static, TypeScript, ESLint and production build remain required
  release gates. Authenticated browser/provider verification is reported separately.
