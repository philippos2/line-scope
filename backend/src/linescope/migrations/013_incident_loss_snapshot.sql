-- Registered incident loss scopes use Snapshot v7. Prior bytes are unchanged.
ALTER TABLE update_request DROP CONSTRAINT update_request_snapshot_schema_version_check;
ALTER TABLE update_request ADD CONSTRAINT update_request_snapshot_schema_version_check
  CHECK(snapshot_schema_version IN (1,2,3,4,5,6,7));
