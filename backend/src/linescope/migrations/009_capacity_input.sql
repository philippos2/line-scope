-- Extend contracts without modifying already applied migration checksums.
CREATE TABLE capacity_input (
  capacity_input_id UUID PRIMARY KEY,
  input_code TEXT UNIQUE NOT NULL CHECK(length(btrim(input_code)) BETWEEN 1 AND 100),
  equipment_id UUID NOT NULL REFERENCES equipment(equipment_id),
  product_id UUID NOT NULL REFERENCES product(product_id),
  payload JSONB NOT NULL CHECK(jsonb_typeof(payload) = 'object'),
  version BIGINT NOT NULL CHECK(version > 0)
);
ALTER TABLE update_request DROP CONSTRAINT update_request_snapshot_schema_version_check;
ALTER TABLE update_request ADD CONSTRAINT update_request_snapshot_schema_version_check CHECK(snapshot_schema_version IN (1,2,3));
ALTER TABLE update_target DROP CONSTRAINT update_target_target_type_check;
ALTER TABLE update_target ADD CONSTRAINT update_target_target_type_check CHECK(target_type IN (
  'EquipmentState','MaintenancePlan','MaintenanceRecord','ProductionOperation',
  'ProductionOperationEquipmentAssignment','DependencyRelation','EconomicInput','CapacityInput'
));
-- Name the old operation/target check through its definition, not CHECK numbering.
DO $$
DECLARE constraint_name text;
BEGIN
 SELECT conname INTO STRICT constraint_name FROM pg_constraint
 WHERE conrelid='update_target'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%MaintenanceRecord%'
 AND pg_get_constraintdef(oid) LIKE '%operation_type%';
 EXECUTE format('ALTER TABLE update_target DROP CONSTRAINT %I', constraint_name);
END $$;
ALTER TABLE update_target ADD CONSTRAINT update_target_category_operation_check CHECK(
 (target_type IN ('EquipmentState','ProductionOperation') AND operation_type='UPDATE')
 OR (target_type IN ('MaintenancePlan','EconomicInput','CapacityInput') AND operation_type IN ('CREATE','UPDATE'))
 OR (target_type='MaintenanceRecord' AND operation_type='CREATE')
 OR target_type IN ('ProductionOperationEquipmentAssignment','DependencyRelation')
);

ALTER TABLE business_update_history DROP CONSTRAINT business_update_history_category_check;
ALTER TABLE business_update_history ADD CONSTRAINT business_update_history_category_check CHECK(category IN ('EQUIPMENT_STATE','MAINTENANCE','PRODUCTION_OPERATION','DEPENDENCY','ECONOMIC_INPUT','CAPACITY_INPUT'));
