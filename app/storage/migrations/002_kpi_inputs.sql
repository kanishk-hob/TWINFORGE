-- No historical backfill: previously unrecorded measurements remain unknown.
ALTER TABLE observations
    ADD COLUMN good_count bigint,
    ADD COLUMN reject_count bigint,
    ADD COLUMN total_count bigint,
    ADD COLUMN interval_power_kw double precision,
    ADD COLUMN interval_seconds double precision;
CREATE INDEX observations_kpi_window
    ON observations (source, run_id, asset_id, source_timestamp);
