-- Storage foundation only. Execute/worker transitions and payload validation
-- are separate services; this migration does not publish a Graph generation.
ALTER TABLE update_target ADD CONSTRAINT update_target_request_id_unique
  UNIQUE (update_request_id, update_target_id);

CREATE TABLE graph_outbox (
  outbox_id UUID PRIMARY KEY,
  update_request_id UUID NOT NULL REFERENCES update_request(update_request_id),
  update_target_id UUID NOT NULL,
  aggregate_type TEXT NOT NULL CHECK(length(btrim(aggregate_type)) > 0),
  aggregate_id UUID NOT NULL,
  aggregate_version BIGINT NOT NULL CHECK(aggregate_version > 0),
  event_type TEXT NOT NULL CHECK(length(btrim(event_type)) > 0),
  payload JSONB NOT NULL CHECK(jsonb_typeof(payload) = 'object'),
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN (
    'PENDING','PROCESSING','RETRYABLE','APPLIED','DEAD'
  )),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
  next_attempt_at TIMESTAMPTZ,
  processing_started_at TIMESTAMPTZ,
  processed_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(aggregate_type, aggregate_id, aggregate_version),
  FOREIGN KEY (update_request_id, update_target_id)
    REFERENCES update_target(update_request_id, update_target_id)
);
CREATE INDEX graph_outbox_pending_order_idx
  ON graph_outbox(created_at, outbox_id) WHERE status = 'PENDING';
CREATE INDEX graph_outbox_retry_due_idx
  ON graph_outbox(next_attempt_at, created_at, outbox_id) WHERE status = 'RETRYABLE';
CREATE INDEX graph_outbox_processing_lease_idx
  ON graph_outbox(processing_started_at) WHERE status = 'PROCESSING';
CREATE INDEX graph_outbox_status_idx ON graph_outbox(status);

CREATE TABLE graph_projection_control (
  control_id INTEGER PRIMARY KEY CHECK(control_id = 1),
  rebuild_flag BOOLEAN NOT NULL DEFAULT false,
  rebuild_id UUID,
  active_generation UUID,
  fatal_error TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO graph_projection_control(control_id, fatal_error)
  VALUES(1, 'NOT_INITIALIZED');
