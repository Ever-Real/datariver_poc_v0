CREATE TABLE IF NOT EXISTS poc_k9_managed_graph_policies (
    graph_id char(36) PRIMARY KEY,
    name varchar(255) NOT NULL,
    status varchar(50) NOT NULL,
    classification varchar(50) NOT NULL,
    ontology_version_id char(36) NOT NULL,
    studio_release_id char(36) NOT NULL,
    publication_version integer NOT NULL,
    schedule varchar(100) NOT NULL,
    managed_intent varchar(100) NOT NULL,
    accepted_proposal_id varchar(255) NOT NULL,
    subject_id varchar(255) NOT NULL,
    workspace_id varchar(255) NOT NULL,
    policy_hash char(64) NOT NULL,
    tbox_hash char(64) NOT NULL,
    contract_hash char(64) NOT NULL,
    proposal_hash char(64) NOT NULL,
    source_hash char(64) NOT NULL,
    mapping_hash char(64) NOT NULL,
    active_release_pointer varchar(255),
    active_release_hash char(64),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT chk_k9_graph_id CHECK (graph_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    CONSTRAINT chk_k9_ontology_id CHECK (ontology_version_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    CONSTRAINT chk_k9_studio_id CHECK (studio_release_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    CONSTRAINT chk_k9_policy_hash CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_k9_tbox_hash CHECK (tbox_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_k9_contract_hash CHECK (contract_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_k9_proposal_hash CHECK (proposal_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_k9_source_hash CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_k9_mapping_hash CHECK (mapping_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS poc_k9_refresh_runs (
    run_id char(36) PRIMARY KEY,
    graph_id char(36) NOT NULL,
    status varchar(50) NOT NULL, -- PREPARING, RUN, NO_OP, FAILURE
    input_snapshot_hash char(64),
    policy_hash char(64) NOT NULL,
    manifest jsonb,
    canonical_release jsonb,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    active_release_pointer varchar(255),
    error_message text,
    CONSTRAINT chk_k9_run_id CHECK (run_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
    CONSTRAINT chk_k9_r_policy_hash CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_k9_r_snapshot_hash CHECK (input_snapshot_hash IS NULL OR input_snapshot_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_k9_r_status_hash CHECK (
        (status IN ('RUN', 'NO_OP') AND input_snapshot_hash IS NOT NULL AND manifest IS NOT NULL AND canonical_release IS NOT NULL) OR
        (status NOT IN ('RUN', 'NO_OP'))
    )
);

CREATE INDEX IF NOT EXISTS idx_poc_k9_refresh_runs_graph ON poc_k9_refresh_runs(graph_id, started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_poc_k9_preparing_run ON poc_k9_refresh_runs(graph_id) WHERE status = 'PREPARING';
