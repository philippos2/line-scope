CREATE TABLE update_audit_event (
  audit_event_id UUID PRIMARY KEY,
  request_id UUID NOT NULL,
  update_request_id UUID NOT NULL REFERENCES update_request(update_request_id),
  approval_id UUID REFERENCES approval(approval_id),
  actor_id TEXT NOT NULL CHECK(length(btrim(actor_id)) > 0),
  action TEXT NOT NULL CHECK(action IN (
    'PREPARE','APPROVE','REJECT','EXECUTE','INVALIDATE','EXPIRE','FAILURE','PROJECTION'
  )),
  before_status TEXT,
  after_status TEXT,
  result_code TEXT NOT NULL CHECK(length(btrim(result_code)) > 0),
  details JSONB NOT NULL CHECK(jsonb_typeof(details) = 'object'),
  occurred_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX update_audit_event_request_idx
  ON update_audit_event(update_request_id, occurred_at, audit_event_id);
