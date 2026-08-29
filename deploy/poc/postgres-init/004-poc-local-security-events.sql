BEGIN;

CREATE TABLE IF NOT EXISTS poc_local_security_events (
  event_id uuid PRIMARY KEY,
  event_type text NOT NULL,
  subject_id text NOT NULL,
  actor_subject_id text NOT NULL,
  actor_kind text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  resulting_credential_version bigint NOT NULL,
  revoked_session_count bigint NOT NULL,
  CONSTRAINT uq_poc_local_security_event_subject_version
    UNIQUE (event_type, subject_id, resulting_credential_version),
  CONSTRAINT ck_poc_local_security_event_type
    CHECK (event_type = 'SELF_PASSWORD_CHANGED_V1'),
  CONSTRAINT ck_poc_local_security_event_actor
    CHECK (actor_kind = 'SELF' AND actor_subject_id = subject_id),
  CONSTRAINT ck_poc_local_security_event_subject
    CHECK (char_length(subject_id) BETWEEN 1 AND 255),
  CONSTRAINT ck_poc_local_security_event_version
    CHECK (resulting_credential_version > 0),
  CONSTRAINT ck_poc_local_security_event_session_count
    CHECK (revoked_session_count >= 0)
);

CREATE OR REPLACE FUNCTION poc_reject_local_security_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
  RAISE EXCEPTION 'POC local security events are append-only';
END
$function$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'trg_poc_local_security_events_append_only'
      AND tgrelid = 'poc_local_security_events'::regclass
  ) THEN
    CREATE TRIGGER trg_poc_local_security_events_append_only
      BEFORE UPDATE OR DELETE ON poc_local_security_events
      FOR EACH ROW EXECUTE FUNCTION poc_reject_local_security_event_mutation();
  END IF;
END
$block$;

CREATE OR REPLACE FUNCTION poc_reject_schema_receipt_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
  IF OLD.scope LIKE 'product-owned-schema-contract-v%'
    OR (TG_OP = 'UPDATE' AND NEW.scope LIKE 'product-owned-schema-contract-v%') THEN
    RAISE EXCEPTION 'POC Product schema receipts are immutable';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END
$function$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'trg_poc_state_schema_receipts_immutable'
      AND tgrelid = 'poc_state'::regclass
  ) THEN
    CREATE TRIGGER trg_poc_state_schema_receipts_immutable
      BEFORE UPDATE OR DELETE ON poc_state
      FOR EACH ROW EXECUTE FUNCTION poc_reject_schema_receipt_mutation();
  END IF;
END
$block$;

INSERT INTO poc_state (scope, value) VALUES (
  'product-owned-schema-contract-v2',
  '{"contract":"DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V2","revision":2,"fingerprint":"b19760b2ca0857e572e5c16684747a2f76ec43d46988b52af649b997d4991dc1"}'::jsonb
);

COMMIT;
