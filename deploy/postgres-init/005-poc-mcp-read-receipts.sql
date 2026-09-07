BEGIN;

CREATE OR REPLACE FUNCTION poc_reject_schema_receipt_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
  IF OLD.scope LIKE 'product-owned-schema-contract-v%'
    OR OLD.scope LIKE 'mcp-read-receipt-v1:%'
    OR (TG_OP = 'UPDATE' AND (
      NEW.scope LIKE 'product-owned-schema-contract-v%'
      OR NEW.scope LIKE 'mcp-read-receipt-v1:%'
    )) THEN
    RAISE EXCEPTION 'POC Product schema and MCP read receipts are immutable';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END
$function$;

INSERT INTO poc_state (scope, value) VALUES (
  'product-owned-schema-contract-v3',
  '{"contract":"DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V3","revision":3,"fingerprint":"80a64380b21040a1a308301a236fd74bb5d8aad210be675f97ffba87523c6e48"}'::jsonb
);

COMMIT;
