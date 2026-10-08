CREATE TABLE equipment (
  equipment_id UUID PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  equipment_code TEXT NOT NULL,
  equipment_name TEXT NOT NULL,
  equipment_type TEXT NOT NULL,
  active BOOLEAN NOT NULL,
  UNIQUE(equipment_code),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE equipment_current_state (
  equipment_id UUID PRIMARY KEY REFERENCES equipment(equipment_id),
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  state_code TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK(state_code IN ('RUNNING','STOPPED','UNDER_MAINTENANCE','UNKNOWN'))
);

CREATE TABLE maintenance_plan (
  maintenance_plan_id UUID PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  plan_code TEXT NOT NULL,
  equipment_id UUID NOT NULL REFERENCES equipment(equipment_id),
  planned_start TIMESTAMPTZ NOT NULL,
  planned_end TIMESTAMPTZ NOT NULL,
  plan_status TEXT NOT NULL,
  UNIQUE(plan_code),
  CHECK(plan_status IN ('PLANNED','CANCELLED')),
  CHECK(planned_start<planned_end)
);

CREATE TABLE maintenance_record (
  maintenance_record_id UUID PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  record_code TEXT NOT NULL,
  maintenance_plan_id UUID REFERENCES maintenance_plan(maintenance_plan_id),
  equipment_id UUID NOT NULL REFERENCES equipment(equipment_id),
  performed_at TIMESTAMPTZ NOT NULL,
  result TEXT NOT NULL CHECK(length(btrim(result)) > 0),
  UNIQUE(record_code)
);

CREATE TABLE process (
  process_id UUID PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  process_code TEXT NOT NULL,
  process_name TEXT NOT NULL,
  active BOOLEAN NOT NULL,
  UNIQUE(process_code),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE production_operation (
  production_operation_id UUID PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  operation_code TEXT NOT NULL,
  process_id UUID NOT NULL REFERENCES process(process_id),
  planned_status TEXT NOT NULL,
  planned_start TIMESTAMPTZ NOT NULL,
  planned_end TIMESTAMPTZ NOT NULL,
  active BOOLEAN NOT NULL,
  UNIQUE(operation_code),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK(planned_status IN ('PLANNED','CANCELLED')),
  CHECK(planned_start<planned_end)
);

CREATE TABLE product (
  product_id UUID PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  product_code TEXT NOT NULL,
  product_name TEXT NOT NULL,
  active BOOLEAN NOT NULL,
  UNIQUE(product_code),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE infrastructure_resource (
  infrastructure_resource_id UUID PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  resource_code TEXT NOT NULL,
  resource_name TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  active BOOLEAN NOT NULL,
  UNIQUE(resource_code),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE production_operation_equipment_assignment (
  assignment_id UUID PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  production_operation_id UUID NOT NULL REFERENCES production_operation(production_operation_id),
  equipment_id UUID NOT NULL REFERENCES equipment(equipment_id),
  effective_from TIMESTAMPTZ NOT NULL,
  effective_to TIMESTAMPTZ,
  active BOOLEAN NOT NULL,
  UNIQUE(production_operation_id,equipment_id,effective_from) DEFERRABLE INITIALLY IMMEDIATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK(effective_to IS NULL OR effective_from<effective_to)
);

CREATE TABLE dependency_relation (
  dependency_relation_id UUID PRIMARY KEY,
  version BIGINT NOT NULL DEFAULT 1 CHECK(version>0),
  source_entity_type TEXT NOT NULL,
  source_entity_id UUID NOT NULL,
  target_entity_type TEXT NOT NULL,
  target_entity_id UUID NOT NULL,
  relation_type TEXT NOT NULL,
  effective_from TIMESTAMPTZ NOT NULL,
  effective_to TIMESTAMPTZ,
  required BOOLEAN NOT NULL,
  active BOOLEAN NOT NULL,
  UNIQUE(source_entity_type,source_entity_id,target_entity_type,target_entity_id,relation_type,effective_from) DEFERRABLE INITIALLY IMMEDIATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK(effective_to IS NULL OR effective_from<effective_to),
  CHECK(relation_type IN ('DEPENDS_ON','PRECEDES','SUPPLIES','CONTROLS','PRODUCES','CAN_SUBSTITUTE')),
  CHECK(relation_type IN ('DEPENDS_ON','SUPPLIES') OR required=false)
);


-- Endpoint existence/active, interval overlap and mixed-cycle validation belong
-- to the graph mutation transaction; polymorphic endpoints are not ordinary FKs.
ALTER TABLE dependency_relation ADD CONSTRAINT dependency_endpoint_types CHECK (
  (relation_type = 'DEPENDS_ON'
   AND source_entity_type IN ('Equipment','Process','ProductionOperation')
   AND target_entity_type IN ('Equipment','InfrastructureResource','Process')) OR
  (relation_type = 'PRECEDES'
   AND source_entity_type IN ('Process','ProductionOperation')
   AND target_entity_type = source_entity_type) OR
  (relation_type = 'SUPPLIES'
   AND source_entity_type IN ('InfrastructureResource','Equipment')
   AND target_entity_type IN ('Equipment','Process','ProductionOperation')) OR
  (relation_type = 'CONTROLS'
   AND source_entity_type = 'Equipment' AND target_entity_type = 'Equipment') OR
  (relation_type = 'PRODUCES'
   AND source_entity_type IN ('Process','ProductionOperation')
   AND target_entity_type = 'Product') OR
  (relation_type = 'CAN_SUBSTITUTE'
   AND source_entity_type IN ('Equipment','Process','InfrastructureResource')
   AND target_entity_type = source_entity_type)
);
