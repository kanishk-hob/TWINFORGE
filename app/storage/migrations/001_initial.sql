CREATE TABLE factories (factory_id text PRIMARY KEY);
CREATE TABLE lines (
    factory_id text REFERENCES factories, line_id text,
    PRIMARY KEY (factory_id, line_id)
);
CREATE TABLE assets (
    asset_id text PRIMARY KEY,
    factory_id text NOT NULL, line_id text NOT NULL, asset_type text NOT NULL,
    FOREIGN KEY (factory_id, line_id) REFERENCES lines
);
CREATE TABLE source_runs (
    source text, run_id text, first_observed_at timestamptz NOT NULL,
    PRIMARY KEY (source, run_id)
);
CREATE TABLE observations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text NOT NULL, run_id text NOT NULL,
    asset_id text NOT NULL REFERENCES assets, sequence bigint NOT NULL CHECK (sequence >= 0),
    observed_at timestamptz NOT NULL, source_timestamp timestamptz,
    raw_source_timestamp text, telemetry_values jsonb,
    valid boolean NOT NULL, fresh boolean NOT NULL, quality_source text NOT NULL,
    reason text, state text NOT NULL, active_fault text,
    FOREIGN KEY (source, run_id) REFERENCES source_runs,
    UNIQUE (source, run_id, asset_id, sequence)
);
CREATE INDEX observations_asset_time ON observations (asset_id, observed_at, id);
CREATE INDEX observations_asset_cursor ON observations (asset_id, id);
CREATE TABLE machine_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    observation_id bigint NOT NULL REFERENCES observations,
    kind text NOT NULL CHECK (kind IN ('state_observed', 'state_changed', 'fault_observed', 'fault_started', 'fault_recovered')),
    previous_value text, value text,
    UNIQUE (observation_id, kind)
);
CREATE INDEX machine_events_observation ON machine_events (observation_id);
