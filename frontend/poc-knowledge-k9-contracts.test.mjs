import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { URL } from 'node:url';
import * as contracts from './poc-knowledge-k9-contracts.mjs';

const {
  assertExactKeys,
  canonicalStringify,
  computeSha256,
  docMappingGlossary,
  docMappingLineage,
  docSourceGlossary,
  docSourceLineage,
  docTboxDataGlossary,
  docTboxMetadataLineage,
  envMappingGlossary,
  envMappingLineage,
  envSourceGlossary,
  envSourceLineage,
  envTboxDataGlossary,
  envTboxMetadataLineage,
  isNodeUrn,
  isTermUrn,
  validateAuthorityPin,
  validateClassification,
  validateContractIntegration,
} = contracts;

const ENVELOPES = [
  envTboxMetadataLineage,
  envTboxDataGlossary,
  envSourceLineage,
  envSourceGlossary,
  envMappingLineage,
  envMappingGlossary,
];

test('contract envelopes remain immutable PROPOSED artifacts with exact document hashes', () => {
  for (const envelope of ENVELOPES) {
    assert.equal(envelope.lifecycle, 'PROPOSED');
    assert.equal(envelope.document_hash, computeSha256(envelope.document));
    assert.ok(Object.isFrozen(envelope));
    assert.ok(Object.isFrozen(envelope.document));
  }
  assert.throws(() => {
    docTboxMetadataLineage.contract_version = '2.0';
  }, TypeError);
});

test('T-Boxes express exactly the two approved semantic targets and bounded vocabulary', () => {
  assert.deepEqual(
    [docTboxMetadataLineage.tbox_identity, docTboxMetadataLineage.graph_type],
    ['contract.semantic.metadata-lineage', 'CATALOG_MIRROR'],
  );
  assert.deepEqual(
    [docTboxDataGlossary.tbox_identity, docTboxDataGlossary.graph_type],
    ['contract.semantic.data-glossary', 'CURATED_KNOWLEDGE'],
  );
  assert.deepEqual(docTboxMetadataLineage.classes.map(({ name }) => name), ['Dataset']);
  assert.deepEqual(
    docTboxMetadataLineage.relationships.map(({ type }) => type),
    ['DEPENDS_ON'],
  );
  assert.deepEqual(
    docTboxDataGlossary.classes.map(({ name }) => name),
    ['BusinessTerm', 'GlossaryNode', 'Table', 'Column'],
  );
  assert.deepEqual(
    docTboxDataGlossary.relationships.map(({ type }) => type),
    ['HAS_PARENT_NODE', 'HAS_PARENT_NODE', 'MAPPED_TO_TERM', 'MAPPED_TO_TERM'],
  );
  assert.equal(docTboxMetadataLineage.classification_ceiling, 'INTERNAL');
  assert.equal(docTboxDataGlossary.classification_ceiling, 'INTERNAL');
});

test('source contracts declare exact Product routes and future private server-owned seams', () => {
  const lineageBoundary = docSourceLineage.selection_boundary;
  assert.deepEqual(lineageBoundary.endpoints, [
    'GET /poc-api/datahub/catalog?limit=100&cursor={cursor} -> {items, page:{next_cursor,limit}, total, total_exact, meta, match_mode}',
    'GET /poc-api/datahub/lineage?urn={urn} -> {center_asset_id, nodes, edges, direction, depth, truncated, meta}',
  ]);
  assert.equal(lineageBoundary.inventory_selection, 'FULL_SERVER_INVENTORY_NO_QUERY');
  assert.equal(lineageBoundary.public_catalog_limit, 100);
  assert.equal(lineageBoundary.private_provider_inventory_limit, 250);
  assert.equal(lineageBoundary.maximum_inventory_pages, 10002);
  assert.deepEqual(lineageBoundary.lineage_directions, ['UPSTREAM', 'DOWNSTREAM']);
  assert.equal(lineageBoundary.lineage_page_limit, 100);
  assert.equal(lineageBoundary.lineage_offset_step, 100);
  assert.equal(lineageBoundary.maximum_lineage_pages_per_direction, 10002);
  assert.match(lineageBoundary.lineage_total_reconciliation, /COUNT_EQUALS_PROVIDER_TOTAL/);
  assert.match(lineageBoundary.required_product_seam, /collectLineageInventorySeam/);
  assert.match(lineageBoundary.required_product_seam, /module-private in poc-server\.mjs/);
  assert.match(lineageBoundary.required_product_seam, /after context\.principal auth/);
  assert.match(lineageBoundary.required_product_seam, /server-owned exhaustive inventory/);
  assert.match(lineageBoundary.required_product_seam, /UPSTREAM\/DOWNSTREAM cursor\/membership traces/);
  assert.match(lineageBoundary.required_product_seam, /reconcile each provider total/);
  assert.match(lineageBoundary.required_product_seam, /reject repeated\/nonterminal-at-bound cursors/);

  const glossaryBoundary = docSourceGlossary.selection_boundary;
  assert.match(glossaryBoundary.endpoints[0], /GET \/poc-api\/datahub\/glossary.*-> \{items\}/);
  assert.match(glossaryBoundary.endpoints[0], /INSUFFICIENT for provider-scroll completeness/);
  assert.match(glossaryBoundary.endpoints[1], /page:\{next_cursor,limit\}/);
  assert.match(glossaryBoundary.endpoints[2], /\{id, external_urn, \.\.\., classification\}/);
  assert.equal(glossaryBoundary.hierarchy_cycle_policy, 'REJECT_TERM_OR_NODE_PARENT_CYCLE');
  assert.match(glossaryBoundary.required_product_seam, /collectGlossaryInventorySeam/);
  assert.match(glossaryBoundary.required_product_seam, /module-private in poc-server\.mjs/);
  assert.match(glossaryBoundary.required_product_seam, /server-owned exhaustive trace/);
  assert.match(glossaryBoundary.required_product_seam, /rehydrate assignment classification/);
  assert.match(glossaryBoundary.required_product_seam, /absent\/unknown\/above-INTERNAL/);
});

test('declared route and provider boundaries match the pinned Product source', () => {
  const product = readFileSync(new URL('./poc-server.mjs', import.meta.url), 'utf8');
  assert.match(product, /const maximumInventoryPages = 10_002/);
  assert.match(product, /async function datahubCatalogPage[\s\S]*?count: 250/);
  assert.match(product, /async function datahubCatalog[\s\S]*?Math\.min\(100,[\s\S]*?return \{[\s\S]*?total_exact: true,[\s\S]*?match_mode: 'ALL'/);
  assert.match(product, /async function datahubLineage[\s\S]*?count: 100[\s\S]*?truncated:[\s\S]*?meta: catalogMeta\(\)/);
  assert.match(product, /function datasetAsset[\s\S]*?id: entity\.urn,[\s\S]*?external_urn: entity\.urn,[\s\S]*?classification/);
  assert.match(product, /async function datahubGlossary[\s\S]*?return \{\s*items: terms\.sort/);
  assert.match(product, /async function datahubGlossaryAssignments[\s\S]*?Math\.min\(50,[\s\S]*?Math\.min\(100_000,[\s\S]*?page: \{ next_cursor:/);
});

test('mapping contracts bind exact source and T-Box pins and preserve deterministic fail-closed semantics', () => {
  assert.equal(validateContractIntegration(envMappingLineage, envTboxMetadataLineage, envSourceLineage), true);
  assert.equal(validateContractIntegration(envMappingGlossary, envTboxDataGlossary, envSourceGlossary), true);
  assert.equal(docMappingLineage.input_source_document_hash, envSourceLineage.document_hash);
  assert.equal(docMappingLineage.target_tbox_document_hash, envTboxMetadataLineage.document_hash);
  assert.equal(docMappingGlossary.input_source_document_hash, envSourceGlossary.document_hash);
  assert.equal(docMappingGlossary.target_tbox_document_hash, envTboxDataGlossary.document_hash);
  assert.equal(docMappingLineage.fail_closed_behavior, 'REJECT_ON_MISSING_PIN_OR_DRIFT');
  assert.equal(docMappingGlossary.fail_closed_behavior, 'REJECT_ON_MISSING_PIN_OR_DRIFT');
  assert.equal(docMappingLineage.classification_behavior, 'INHERIT_FROM_SOURCE');
  assert.equal(docMappingGlossary.classification_behavior, 'INHERIT_FROM_SOURCE');
  const dependencyRule = docMappingLineage.rules.find(
    ({ target_element }) => target_element === 'rel.dataset_depends_on',
  );
  assert.equal(dependencyRule.edge_source, 'edges.target_asset_id');
  assert.equal(dependencyRule.edge_target, 'edges.source_asset_id');
});

test('static validation fails closed on pin and classification violations', () => {
  assert.doesNotThrow(() => validateAuthorityPin({
    projection_version: 1,
    policy_version: 'POC_LIVE_PROVIDER_V1',
    classification_policy_version: 1,
    authorization_generation: 1,
    workspace_id: 'workspace-1',
    subject_id: 'subject-1',
    classification_ceiling: 'INTERNAL',
  }));
  assert.throws(
    () => validateAuthorityPin({
      projection_version: 1,
      policy_version: 'POC_LIVE_PROVIDER_V1',
      classification_policy_version: 1,
      authorization_generation: 1,
      workspace_id: 'workspace-1',
      subject_id: 'subject-1',
      classification_ceiling: 'RESTRICTED',
    }),
    /exactly INTERNAL/,
  );
  assert.doesNotThrow(() => validateClassification('INTERNAL', 'INTERNAL'));
  assert.throws(() => validateClassification('CONFIDENTIAL', 'INTERNAL'), /above INTERNAL/);
  assert.throws(() => validateClassification('toString', 'INTERNAL'), /Unknown classification/);
  assert.throws(() => validateClassification('constructor', 'INTERNAL'), /Unknown classification/);
  assert.throws(() => validateClassification('INTERNAL', 'toString'), /Unknown classification ceiling/);
});

test('proposal exports no executable runtime authority, collector, or snapshot API', () => {
  const exportNames = Object.keys(contracts);
  assert.equal(exportNames.some((name) => /bootstrap|runtime|collector|snapshot/i.test(name)), false);
  assert.equal('mapK9LineageToManagedGraph' in contracts, false);
  assert.equal('mapK9GlossaryToManagedGraph' in contracts, false);
});

test('canonical serialization and exact-key validation reject ambiguous inputs', () => {
  const cyclic = {};
  cyclic.self = cyclic;
  assert.throws(() => canonicalStringify(cyclic), /Cyclic references/);
  assert.throws(() => canonicalStringify({ value: undefined }), /Undefined values/);
  assert.throws(() => canonicalStringify({ value: [undefined] }), /Undefined array elements/);
  assert.throws(() => assertExactKeys({ a: 1, b: 2 }, ['a'], 'fixture'), /Exact keys mismatch/);
});

test('glossary identities accept canonical URNs and reject empty or control-bearing values', () => {
  assert.equal(isTermUrn('urn:li:glossaryTerm:finance.revenue'), true);
  assert.equal(isNodeUrn('urn:li:glossaryNode:finance'), true);
  assert.equal(isTermUrn('urn:li:glossaryTerm:'), false);
  assert.equal(isNodeUrn('urn:li:glossaryNode:bad value'), false);
  assert.equal(isTermUrn('urn:li:glossaryTerm:bad\u0000value'), false);
});
