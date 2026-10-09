-- Storage foundation only. Authorization, canonical/hash verification,
-- cross-row state pairs and transitions are enforced by later services.
CREATE TABLE update_request (
  update_request_id UUID PRIMARY KEY,
  requester_id TEXT NOT NULL CHECK(length(btrim(requester_id)) > 0),
  operation_type TEXT NOT NULL CHECK(operation_type IN ('CREATE','UPDATE','DISABLE','COMPOSITE')),
  status TEXT NOT NULL CHECK(status IN (
    'PREPARED','WAITING_APPROVAL','APPROVED','COMPLETED',
    'REJECTED','INVALIDATED','EXPIRED','FAILED'
  )),
  idempotency_key UUID UNIQUE NOT NULL,
  prepare_retry_key UUID NOT NULL,
  prepare_input_hash TEXT NOT NULL CHECK(prepare_input_hash ~ '^[0-9a-f]{64}$'),
  agent_input_hash TEXT NOT NULL CHECK(agent_input_hash ~ '^[0-9a-f]{64}$'),
  canonical_snapshot TEXT NOT NULL CHECK(length(canonical_snapshot) > 0),
  snapshot_schema_version INTEGER NOT NULL CHECK(snapshot_schema_version = 1),
  snapshot_hash TEXT NOT NULL CHECK(snapshot_hash ~ '^[0-9a-f]{64}$'),
  execution_result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(requester_id, prepare_retry_key),
  CHECK(execution_result IS NULL OR jsonb_typeof(execution_result) = 'object'),
  CHECK((status = 'COMPLETED') = (execution_result IS NOT NULL))
);

CREATE TABLE update_target (
  update_target_id UUID PRIMARY KEY,
  update_request_id UUID NOT NULL REFERENCES update_request(update_request_id),
  target_type TEXT NOT NULL CHECK(target_type IN (
    'EquipmentState','MaintenancePlan','MaintenanceRecord','ProductionOperation',
    'ProductionOperationEquipmentAssignment','DependencyRelation'
  )),
  target_id UUID NOT NULL,
  business_key JSONB NOT NULL CHECK(jsonb_typeof(business_key) = 'object'),
  operation_type TEXT NOT NULL CHECK(operation_type IN ('CREATE','UPDATE','DISABLE')),
  before_snapshot JSONB,
  proposed_snapshot JSONB NOT NULL CHECK(jsonb_typeof(proposed_snapshot) = 'object'),
  expected_version BIGINT,
  UNIQUE(update_request_id, target_type, target_id),
  UNIQUE(update_request_id, target_type, business_key),
  CHECK(
    (operation_type = 'CREATE' AND before_snapshot IS NULL AND expected_version IS NULL)
    OR
    (operation_type IN ('UPDATE','DISABLE') AND before_snapshot IS NOT NULL
     AND jsonb_typeof(before_snapshot) = 'object'
     AND expected_version IS NOT NULL AND expected_version > 0)
  ),
  CHECK(
    (target_type IN ('EquipmentState','ProductionOperation') AND operation_type = 'UPDATE')
    OR (target_type = 'MaintenancePlan' AND operation_type IN ('CREATE','UPDATE'))
    OR (target_type = 'MaintenanceRecord' AND operation_type = 'CREATE')
    OR target_type IN ('ProductionOperationEquipmentAssignment','DependencyRelation')
  )
);

CREATE TABLE approval (
  approval_id UUID PRIMARY KEY,
  update_request_id UUID UNIQUE NOT NULL REFERENCES update_request(update_request_id),
  approver_id TEXT CHECK(approver_id IS NULL OR length(btrim(approver_id)) > 0),
  status TEXT NOT NULL CHECK(status IN (
    'PENDING','APPROVED','CONSUMED','REJECTED','INVALIDATED','EXPIRED'
  )),
  snapshot_hash TEXT NOT NULL CHECK(snapshot_hash ~ '^[0-9a-f]{64}$'),
  approved_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK((approved_at IS NULL) = (expires_at IS NULL)),
  CHECK(expires_at IS NULL OR expires_at = approved_at + INTERVAL '30 minutes'),
  CHECK(status NOT IN ('APPROVED','CONSUMED','EXPIRED')
        OR (approver_id IS NOT NULL AND approved_at IS NOT NULL)),
  CHECK(status <> 'PENDING' OR (approver_id IS NULL AND approved_at IS NULL)),
  CHECK(status <> 'REJECTED' OR (approver_id IS NOT NULL AND approved_at IS NULL)),
  CHECK((status = 'CONSUMED') = (consumed_at IS NOT NULL)),
  CHECK(consumed_at IS NULL OR (consumed_at >= approved_at AND consumed_at < expires_at))
);
