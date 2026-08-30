BEGIN;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'poc_local_security_events'::regclass
      AND conname = 'ck_poc_local_security_event_type_v4'
  ) THEN
    ALTER TABLE poc_local_security_events
      DROP CONSTRAINT ck_poc_local_security_event_type,
      ADD CONSTRAINT ck_poc_local_security_event_type_v4 CHECK (
        event_type IN ('SELF_PASSWORD_CHANGED_V1', 'LOCAL_CREDENTIAL_PROVISIONED_V1')
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'poc_local_security_events'::regclass
      AND conname = 'ck_poc_local_security_event_actor_v4'
  ) THEN
    ALTER TABLE poc_local_security_events
      DROP CONSTRAINT ck_poc_local_security_event_actor,
      ADD CONSTRAINT ck_poc_local_security_event_actor_v4 CHECK (
        char_length(actor_subject_id) BETWEEN 1 AND 255
        AND ((event_type = 'SELF_PASSWORD_CHANGED_V1'
            AND actor_kind = 'SELF' AND actor_subject_id = subject_id)
          OR (event_type = 'LOCAL_CREDENTIAL_PROVISIONED_V1'
            AND actor_kind = 'LOCAL_ADMIN'))
      );
  END IF;
END
$block$;

INSERT INTO poc_state (scope, value) VALUES (
  'product-owned-schema-contract-v4',
  '{"contract":"DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V4","revision":4,"fingerprint":"e0147fd92a5eb98472af41659409c3cfb548b33f15ac62f85035818b923d575f"}'::jsonb
);

COMMIT;
