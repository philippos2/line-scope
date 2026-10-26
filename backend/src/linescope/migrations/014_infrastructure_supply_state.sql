-- Registered bootstrap condition, not a measurement of physical supply.
CREATE TABLE infrastructure_supply_state (
    infrastructure_resource_id UUID PRIMARY KEY
        REFERENCES infrastructure_resource(infrastructure_resource_id),
    supply_state TEXT NOT NULL CHECK (supply_state IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN')),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    registered_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    source TEXT NOT NULL CHECK (length(source) > 0)
);
