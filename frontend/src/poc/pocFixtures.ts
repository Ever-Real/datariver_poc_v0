export type PocColumn = {
  name: string
  type: string
  description: string
  nullable: boolean
  quality: number
}

export type PocAsset = {
  id: string
  name: string
  platform: string
  database: string
  schema: string
  domain: string
  owner: string
  classification: 'INTERNAL' | 'CONFIDENTIAL'
  description: string
  rows: string
  size: string
  freshness: string
  quality: number
  tags: readonly string[]
  terms: readonly string[]
  columns: readonly PocColumn[]
  upstream: readonly string[]
  downstream: readonly string[]
}

export const pocAssets = [
  {
    id: 'asset-wafer-inspection',
    name: 'wafer_inspection_events',
    platform: 'Snowflake',
    database: 'MANUFACTURING',
    schema: 'QUALITY',
    domain: 'Manufacturing Quality',
    owner: 'Yield Engineering',
    classification: 'INTERNAL',
    description: 'Normalized optical inspection events for each wafer, lot and inspection step.',
    rows: '48.2M',
    size: '18.4 GB',
    freshness: '12 min ago',
    quality: 97,
    tags: ['gold', 'hourly', 'inspection'],
    terms: ['Wafer', 'Defect', 'Inspection Step'],
    columns: [
      { name: 'wafer_id', type: 'VARCHAR(32)', description: 'Pseudonymous wafer identifier.', nullable: false, quality: 100 },
      { name: 'lot_id', type: 'VARCHAR(24)', description: 'Manufacturing lot identifier.', nullable: false, quality: 100 },
      { name: 'inspection_ts', type: 'TIMESTAMP', description: 'Inspection event timestamp in UTC.', nullable: false, quality: 99 },
      { name: 'defect_code', type: 'VARCHAR(16)', description: 'Controlled defect taxonomy code.', nullable: true, quality: 94 },
      { name: 'defect_count', type: 'INTEGER', description: 'Observed defect count for the event.', nullable: false, quality: 98 },
    ],
    upstream: ['raw_mes.inspection_log', 'reference.defect_taxonomy'],
    downstream: ['analytics.yield_summary', 'quality.excursion_watch'],
  },
  {
    id: 'asset-lot-genealogy',
    name: 'lot_genealogy',
    platform: 'PostgreSQL',
    database: 'MES_CURATED',
    schema: 'CORE',
    domain: 'Manufacturing Operations',
    owner: 'MES Data Office',
    classification: 'INTERNAL',
    description: 'Curated parent and child relationships across manufacturing lots and split events.',
    rows: '8.7M',
    size: '4.1 GB',
    freshness: '5 min ago',
    quality: 99,
    tags: ['certified', 'genealogy'],
    terms: ['Lot', 'Split Event'],
    columns: [
      { name: 'lot_id', type: 'VARCHAR(24)', description: 'Current lot identifier.', nullable: false, quality: 100 },
      { name: 'parent_lot_id', type: 'VARCHAR(24)', description: 'Parent lot before a split.', nullable: true, quality: 99 },
      { name: 'operation_id', type: 'VARCHAR(18)', description: 'Operation at which lineage changed.', nullable: false, quality: 98 },
      { name: 'event_ts', type: 'TIMESTAMP', description: 'Genealogy event timestamp in UTC.', nullable: false, quality: 100 },
    ],
    upstream: ['raw_mes.lot_events'],
    downstream: ['analytics.cycle_time', 'analytics.yield_summary'],
  },
  {
    id: 'asset-yield-summary',
    name: 'yield_summary_daily',
    platform: 'Databricks',
    database: 'ANALYTICS',
    schema: 'YIELD',
    domain: 'Executive Analytics',
    owner: 'Yield Analytics',
    classification: 'CONFIDENTIAL',
    description: 'Daily sample yield rollup by product family, site and process stage.',
    rows: '1.2M',
    size: '730 MB',
    freshness: '42 min ago',
    quality: 96,
    tags: ['executive', 'daily'],
    terms: ['First Pass Yield', 'Product Family'],
    columns: [
      { name: 'business_date', type: 'DATE', description: 'Reporting date.', nullable: false, quality: 100 },
      { name: 'product_family', type: 'VARCHAR(40)', description: 'Sample product family grouping.', nullable: false, quality: 98 },
      { name: 'stage_yield', type: 'DECIMAL(7,4)', description: 'Sanitized stage yield ratio.', nullable: false, quality: 95 },
      { name: 'wafer_count', type: 'INTEGER', description: 'Number of contributing sample wafers.', nullable: false, quality: 97 },
    ],
    upstream: ['quality.wafer_inspection_events', 'core.lot_genealogy'],
    downstream: ['bi.operations_scorecard'],
  },
  {
    id: 'asset-equipment-alarms',
    name: 'equipment_alarm_history',
    platform: 'Oracle',
    database: 'EQUIPMENT',
    schema: 'EVENTS',
    domain: 'Equipment Engineering',
    owner: 'Equipment Reliability',
    classification: 'INTERNAL',
    description: 'Sanitized equipment alarm history for reliability and excursion analysis.',
    rows: '92.1M',
    size: '26.8 GB',
    freshness: '8 min ago',
    quality: 93,
    tags: ['equipment', 'event'],
    terms: ['Equipment', 'Alarm Severity'],
    columns: [
      { name: 'equipment_id', type: 'VARCHAR(20)', description: 'Pseudonymous equipment identifier.', nullable: false, quality: 100 },
      { name: 'alarm_code', type: 'VARCHAR(16)', description: 'Controlled alarm code.', nullable: false, quality: 97 },
      { name: 'severity', type: 'VARCHAR(12)', description: 'Normalized severity label.', nullable: false, quality: 92 },
      { name: 'opened_at', type: 'TIMESTAMP', description: 'Alarm-open timestamp in UTC.', nullable: false, quality: 94 },
    ],
    upstream: ['raw_eap.alarm_stream'],
    downstream: ['reliability.mtbf_features', 'monitoring.tool_health'],
  },
] as const satisfies readonly PocAsset[]

export const capabilityFixtures = [
  { name: 'Catalog projection', detail: '4 sample assets', status: 'AVAILABLE' },
  { name: 'Governance workflow', detail: 'browser-memory states', status: 'SIMULATED' },
  { name: 'Knowledge evidence', detail: '3 synthetic sources', status: 'SIMULATED' },
  { name: 'Quality execution', detail: 'deterministic step control', status: 'SIMULATED' },
] as const

export const qualityRuleSets = [
  { name: 'Wafer inspection essentials', owner: 'Yield Engineering', rules: 8, coverage: '4 assets', score: 97, status: 'ACTIVE' },
  { name: 'Lot genealogy integrity', owner: 'MES Data Office', rules: 6, coverage: '2 assets', score: 99, status: 'ACTIVE' },
  { name: 'Equipment event hygiene', owner: 'Equipment Reliability', rules: 5, coverage: '3 assets', score: 93, status: 'DRAFT' },
] as const

export const knowledgeSources = [
  { title: 'Yield excursion response guide', kind: 'Governance document', version: 'v3.2', evidence: 14, state: 'PUBLISHED' },
  { title: 'Wafer inspection glossary', kind: 'Catalog evidence', version: '2026.07', evidence: 23, state: 'PUBLISHED' },
  { title: 'Quality triage playbook', kind: 'Knowledge source', version: 'Draft 4', evidence: 9, state: 'IN REVIEW' },
] as const

export const monitoringMetrics = [
  { label: 'Sample availability', value: '99.96%', note: 'simulated 24h', level: 96 },
  { label: 'Search latency', value: '182 ms', note: 'synthetic p95', level: 72 },
  { label: 'Workflow activity', value: '128', note: 'sample events', level: 64 },
  { label: 'Quality freshness', value: '12 min', note: 'sample watermark', level: 84 },
] as const
