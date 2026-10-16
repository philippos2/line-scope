-- Optional registered assumptions use Snapshot v6; v1-v5 bytes remain valid.
ALTER TABLE update_request DROP CONSTRAINT update_request_snapshot_schema_version_check;
ALTER TABLE update_request ADD CONSTRAINT update_request_snapshot_schema_version_check
  CHECK(snapshot_schema_version IN (1,2,3,4,5,6));
