# KPI calculation contract: kpi.v1

## Scope and inventory

An asset/run is the calculation boundary. Existing observations contain sequence,
state, active fault, source quality, receipt time (`observed_at`), and nullable
telemetry time (`source_timestamp`). They contain no schedules, certified ideal
cycle times, unit-level completion records, or WIP ledger. Machine events record
observed changes, not exact physical event times. Historical receipt time must
not be confused with simulation time.

Migration 002 adds nullable canonical production counters (good, rejected, total)
and interval power/duration. The simulator mapper takes raw asset production
counters, `extensions.last_interval_power_kw`, and `factory.config.step_seconds`.
It does not consume factory metrics or cumulative simulator energy. Legacy rows
remain null; there is no backfill or fabricated zero. The source's declared
valid/fresh flags gate all calculations.

## Window and completeness

The request names one asset, source and run, and timezone-aware `start` and `end`.
Window length must be positive and at most 24 hours. Times normalize to UTC.
At most 10,000 observations are processed; excess is an explicit 422, not silent
truncation. A source-time index serves the bounded query.

Both boundaries must coincide exactly with valid stored source timestamps.
Counters describe differences over `(start, end]`; sampled states use `[start,end)`.
No interpolation, extrapolation, or wall-clock substitution occurs. Identical
duplicate observations are ignored; conflicting duplicates or sequence/time
reversals invalidate the window. Different source/run/asset inputs are rejected.
Consecutive sequence values and source timestamp gaps no larger than the configured
`TWINFORGE_KPI_MAX_GAP_SECONDS` (default 5) are required. Each interval also needs
valid/fresh endpoints. Coverage is the sum of qualifying interval durations divided
by requested seconds. Missing boundaries, sequence gaps, null timestamps, invalid
or stale data yield unknown whole-window metrics, even when a partial subtotal is
available. A historical complete window does not expire just because it is old.
These checks detect observable gaps; they cannot prove an unobserved reset or
physical transition did not occur between samples.

## Metrics

All metrics expose `value`, `unit`, `status` (`ok`, `estimated`, `unknown`, or
`not_applicable`), and `reason`. Null is distinct from a measured zero.

| Metric | Formula / support |
| --- | --- |
| quality | delta good / delta total; fraction |
| reject_rate | delta rejected / delta total; fraction |
| throughput | delta good * 3600 / window seconds; good units/hour, asset output only |
| energy_consumption | sum right-endpoint interval power kW * interval seconds / 3600; kWh, estimated |
| energy_per_good_unit | calculated energy / delta good; kWh/good unit, estimated |
| downtime | left-held non-RUNNING state durations; seconds, estimated |
| availability | runtime / planned production seconds; unknown through API until schedule and trustworthy runtime are available |
| performance | ideal cycle seconds * delta total / runtime; unknown through API until ideal cycle and trustworthy runtime are available |
| oee | availability * performance * quality, only when all three are valid |
| wip | unknown: no unit/job/buffer ledger is persisted; current_job_id is not a unit count |

Counters must be nonnegative integers, satisfy good + rejected = total at every
point, and never decrease within a run. A detected reset/inconsistency invalidates
production-dependent metrics. Zero total makes quality/reject rate not applicable;
zero good makes energy per good unit not applicable. Zero good over a complete
window gives zero throughput. Partial counters never imply zero output.

For energy every right endpoint must provide finite nonnegative interval power
and a positive interval duration equal to the source-time difference. Power is
interval-average, not an instantaneous sample. Missing or mismatched measurements
make energy unknown. This avoids integrating idle rated power or copying the
simulator's cumulative energy metric.

Downtime is an explicitly sampled estimate, not OEE downtime. Recognized states:
RUNNING, IDLE, SETUP, BLOCKED, STARVED, FAULT, OFFLINE. Every non-RUNNING state counts
toward the estimate. Reasons are the active fault code when present, otherwise
the state. Unknown states make downtime unknown. A state change exactly at end
has zero duration in this window. Reasons and their seconds are returned only
for complete, recognized windows; unknown windows return null, not an empty map.

The independent pure OEE formula helper accepts explicit complete planned time,
runtime, ideal cycle and counts for hand-calculated verification. It rejects
negative/nonfinite inputs, zero denominators and performance above 1 rather than
clamping. The HTTP API does not accept invented schedules to manufacture OEE.
Definitions follow https://www.oee.com/calculating-oee/ .

## Read-only API

`GET /api/twins/{asset_id}/kpis?source=factory_simulator&run_id=...&start=...&end=...`

`source` defaults to `factory_simulator`; run_id, start and end are required.
Response includes `contract_version`, asset/source/run context, normalized window,
coverage, observation count, configured max gap, metric results, and nullable
`downtime_reasons_seconds`. Empty windows return 200 with unknown metrics and zero
coverage. Malformed/naive/oversized windows or row-limit overflow return 422.
Disabled/unavailable storage returns 503. Existing endpoints keep their fields;
new internal canonical operational fields are excluded from legacy twin JSON.

## Validation limits

Unit fixtures verify all formulas and gap/reset behavior. Real PostgreSQL tests
verify migration, persistence, indexed window retrieval and engine integration.
Controlled simulator comparisons use raw snapshots as inputs and its metrics only
as reference. Asset output is not line output; upstream goods must not be summed
with downstream goods. Windowed results may differ from simulator since-start
metrics. Simulated telemetry time must not be compared to receipt wall time.
