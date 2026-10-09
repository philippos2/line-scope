-- Execution history storage only. Execute must write these rows atomically
-- with business changes, request completion, approval consumption and audit.
ALTER TABLE approval ADD CONSTRAINT approval_id_request_unique
  UNIQUE (approval_id, update_request_id);

CREATE TABLE business_update_history (
  history_id UUID PRIMARY KEY,
  update_request_id UUID UNIQUE NOT NULL REFERENCES update_request(update_request_id),
  approval_id UUID NOT NULL,
  requester_id TEXT NOT NULL CHECK(length(btrim(requester_id)) > 0),
  approver_id TEXT NOT NULL CHECK(length(btrim(approver_id)) > 0),
  category TEXT NOT NULL CHECK(category IN (
    'EQUIPMENT_STATE','MAINTENANCE','PRODUCTION_OPERATION','DEPENDENCY'
  )),
  before_snapshot JSONB,
  after_snapshot JSONB NOT NULL,
  result TEXT NOT NULL CHECK(length(btrim(result)) > 0),
  occurred_at TIMESTAMPTZ NOT NULL,
  FOREIGN KEY (approval_id, update_request_id)
    REFERENCES approval(approval_id, update_request_id)
);

CREATE TABLE equipment_state_history (
  history_id UUID PRIMARY KEY,
  equipment_id UUID NOT NULL REFERENCES equipment(equipment_id),
  update_request_id UUID NOT NULL REFERENCES update_request(update_request_id),
  state_code TEXT NOT NULL CHECK(state_code IN (
    'RUNNING','STOPPED','UNDER_MAINTENANCE','UNKNOWN'
  )),
  effective_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  UNIQUE (update_request_id, equipment_id)
);
CREATE INDEX equipment_state_history_equipment_time_idx
  ON equipment_state_history(equipment_id, effective_at, history_id);
