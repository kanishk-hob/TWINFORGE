# Predictive maintenance v1

GET `/api/twins/{asset_id}/predictive-health?run_id=...` reads persisted
`ObservationRecord` telemetry through `PostgresStore.history`, exactly like the
telemetry route. The internal `latest=True` option retrieves at most 31 records
by descending observation ID. Existing forward history pagination is unchanged.
No schema changes, source calls, synchronization or writes occur.

The pure engine sorts by persisted ID, holds the latest reading out, and uses up
to 30 preceding readings. It does not search further back to replace missing
values. Each assessed signal requires at least 10 valid, fresh, finite numeric
observations including the current reading (nine baseline values minimum).
Booleans, numeric strings, absent signals and nonfinite values are excluded.
An unusable latest observation cannot be replaced by an older prediction.
Supported keys: temperature, temperature_c, temp_c, vibration, vibration_rms,
current, current_a, power, power_kw. Keys are assessed independently without
merging aliases or assuming unit conversions. Simulator scores are never inputs.

The baseline uses population standard deviation. Signed Z = (current - mean) /
standard deviation; risk = clamp((abs(Z) - 1) / 3, 0, 1). Overall risk is the
maximum scorable signal risk. WARNING begins at 0.45 (absolute Z 2.35), CRITICAL
at 0.75 (absolute Z 3.25). These are provisional statistical screening thresholds,
not calibrated failure probabilities or verified maintenance lead times.

An unchanged constant baseline yields Z=0 and risk=0. A changed constant baseline
has undefined Z and null risk, with an explicit reason. If no signal is scorable,
or an unscorable change would otherwise yield NORMAL, status is INSUFFICIENT_DATA
and aggregate risk is null. Other scorable WARNING/CRITICAL evidence is retained
with a partial-evidence reason. Top three signals sort by descending risk then
name; per-signal counts include current. Aggregate observations_used counts the
union of observations used by assessed signals; when none qualifies, it reports
the largest useful candidate count. Missing other signals are not imputed.

The response includes predictive.v1, method, source/run, latest persisted receipt
time, risk/status, top signals, counts and a recommendation. Empty/unknown history
returns INSUFFICIENT_DATA (200). Missing/blank run is 422; disabled/unavailable
persistence is 503. Unexpected evidence failures return a sanitized 500.

Limitations: latest means latest persisted ID for the requested run, not current
wall-clock freshness. The recorded fresh flag describes ingestion quality; an
old run can still be assessed. No time window, operating-state segmentation,
sequence/time-gap model or timestamp-age rejection is applied. A rolling baseline
can absorb gradual drift or include abnormal operation. Coverage can be partial;
NORMAL applies only to the assessed signals. This is an explainable anomaly
screen, not a validated fault forecast, RUL estimate or replacement for health.v1.
The existing history index may need query-plan review for very large datasets.
Future methods can reuse the service/evidence path while exposing their own
method/version and calibration contracts.

## Optional v2 detector

The default remains rolling_z_score and predictive.v1. Opt in with
method=z_score_ewma for the combined predictive.v2 response; see
[Predictive maintenance v2](predictive-v2.md) for formulas and limitations.
