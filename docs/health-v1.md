# health.v1 — recorded-condition contract

Method: `observed_condition_rules`. This is observed-condition reporting, not
validated predictive health, a physical-health certificate, or a diagnosis.
The pure engine accepts already-retrieved `Observation` and `Event` models and
returns an `Assessment`. It performs no I/O and reads no clock or configuration.
It does not read or modify `MachineTwin.health`; source scores are not evidence
for these rules. Extra input properties (including source scores) are ignored.

## Context and time

Call `calculate(observations, events, asset_id=..., source=..., run_id=...,
window_start=..., window_end=..., assessment_generated_at=...,
evidence_complete=...)`. All three context strings must be nonempty.
All timestamps must be timezone-aware and normalize to UTC. The receipt-time
window is positive, bounded and half-open `[window_start, window_end)`.
Naive, equal or reversed bounds are errors. The caller supplies assessment time;
it never silently becomes the current time. There is no physical-duration
calculation and no comparison of simulation time with receipt time.

Results include `contract_version`, `method`, context, supplied assessment time,
window bounds, `time_basis="receipt"`, availability, reasons, data quality and
six indicators. `latest_observed_at` is the maximum in-window receipt timestamp
across observations/events; `latest_source_timestamp` is the maximum known
in-window source timestamp, which can belong to a different record. Neither
field promises that a machine is currently reporting or healthy.

## Inputs and evidence references

Observation fields: positive `id`, nonnegative `sequence`, context, `observed_at`,
nullable `source_timestamp`, `state`, nullable `active_fault`, `valid`, `fresh`,
nullable `telemetry_values`, `quality_source`, nullable `reason`.
State/fault are stored observation fields, not currently exposed by the public
telemetry-history response; a future retrieval adapter must supply them.

Events use the persisted kinds `state_observed`, `state_changed`, `fault_observed`,
`fault_started`, `fault_recovered`, with nullable `previous_value` and `value`.
Event source time is optional: the existing event API supplies receipt time only.
Do not substitute receipt time for missing source time.

References contain `kind` (`observation` or `event`), `id`, `sequence`,
`observed_at` and nullable `source_timestamp`. Context is inherited from the
assessment. Positive findings reference matching records; negative findings
reference the inspected observations. Discontinuities reference affected records
and both endpoints of affected pairs. Observation/event ID namespaces are separate.

Mixed source/run/asset input is rejected, even outside the window. Identical ID
duplicates count once; conflicting duplicate IDs raise ValueError. Multiple
in-window observation IDs for one sequence are rejected as inconsistent with
storage uniqueness. Order is deterministic by receipt time then ID. The engine
never infers discontinuity across contexts or compares event sequence adjacency.

## Completeness and availability

`evidence_complete` defaults to false. True is the caller's explicit assertion
that both supplied streams include all retrieved records for the requested
context/window, with no truncation. This cannot prove complete physical sampling.
The engine cannot discover omitted rows; callers must not assert completeness
for a page or an arbitrary subset.

- `available`: complete retrieval, at least two observations, and no detected
  quality limitations. All rules can report about the supplied records only.
- `partial`: at least one rule is assessable but some evidence is limited,
  retrieval is incomplete, or fewer than two observations permit no pairwise
  continuity comparison. Positive recorded facts survive quality limitations.
- `unavailable`: no in-window evidence, or none of the six rules can yield a
  supported finding. Incomplete baseline-only evidence can therefore be unavailable.

All negative findings require complete retrieval, at least one observation and
no quality findings. Missing data never produces a zero-fault assessment. A
single clean observation supports point evidence, not continuity. An event-only
fault start/clear supports its recorded count but not a negative machine finding.

## Indicators

Each has `status` (`observed`, `not_observed`, `unavailable`), nullable `value`,
`reason` and `evidence`. Unavailable values are null, never fabricated zero.

| Indicator | Meaning and value |
| --- | --- |
| `fault_reported_at_last_observation` | Fault code from latest receipt-time observation if non-null. Negative result has null value and `not_observed`, distinct from unavailable. |
| `fault_state_observed` | True if any selected observation has state `FAULT`; false only with sufficient negative evidence. |
| `offline_state_observed` | True for recorded `OFFLINE`; not connector disconnection. |
| `fault_start_observations` | Distinct selected `fault_started` event IDs. `fault_observed` is never a known onset. |
| `fault_clear_observations` | Distinct selected `fault_recovered` IDs. Clearing is neither verified repair nor physical recovery. |
| `evidence_discontinuity` | True if a quality/continuity problem is detected; false only with sufficient evidence and at least two observations. No detected gap is not proof of continuity. |

Positive event counts report observed events even with partial evidence; they
are not total physical incident counts. Zero counts are only `not_observed`
within sufficient supplied evidence. No status means "healthy".

## Data quality

Report unique observation/event counts, usable observation count and findings:
missing source timestamps, invalid flags, stale flags, missing/empty telemetry
maps, sequence gaps, sequence reversals, non-increasing source timestamps.
Counts of sequence/time problems are affected adjacent pairs, not invented
numbers of missing physical events. Source timestamps are compared only for
adjacent consecutive sequences when both timestamps exist. No timestamp gap
threshold is invented. A usable observation has both quality flags true, a
source timestamp and a nonempty telemetry map. This does not certify every
measurement. Arbitrary nested null/non-numeric values have no universal validity
rule and are not used by these indicators. Recorded state/fault evidence remains
reportable even when telemetry is unusable. Original quality reasons remain in
caller evidence; result findings give deterministic category/count explanations.

## Non-goals and validation

No thresholds, composite health score, confidence percentage, ML, prediction,
remaining life, downtime duration, diagnosis, repair confirmation, API, storage
service or dashboard integration. Source scores are synthetic and unvalidated;
altering them cannot change this assessment. Same-sequence source changes missed
by ingestion cannot be reconstructed here. Historical quality flags describe
the accepted snapshot, not current wall-clock freshness. Initial or boundary
fault evidence cannot establish exact physical onset/clear times.

Hand-specified unittest fixtures cover boundaries, contexts, fault/state facts,
quality, gaps, duplicates, repeatability and source-score independence. These
tests establish rule correctness only, not predictive accuracy. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_health.py -v
```

## Internal PostgreSQL service

`app.health.service.asset_health(store, *, source, run_id, asset_id,
window_start, window_end, assessment_generated_at)` returns the existing
Assessment model. It validates nonblank identifiers and timezone-aware times
before I/O. Identifiers are matched exactly, without trimming or UUID coercion.
This service supports positive receipt windows up to 24 hours. This operational
bound does not change the pure engine's window semantics.

`PostgresStore.health_evidence` returns internal dictionaries for observations,
events, nearest `before`/`after` observations, and identity-existence flags.
It uses the existing receipt-time and event indexes; no migration is required.
All queries run in one read-only repeatable-read transaction under the existing
database timeout. They select only one source/run/asset, with receipt membership
`observed_at >= start AND observed_at < end`. Observation order is receipt time
then observation ID; event order is parent receipt time then event ID. Event
source timestamps come from their linked observations, never from receipt time.
Source scores are not selected. Nullable measurements and quality fields survive
mapping to the engine's exact input models.

Each stream is limited to 10,000 records. Queries fetch at most limit + 1 to
detect overflow. Events are joined only to selected observation IDs. Overflow
raises existing `HistoryWindowTooLarge` (a ValueError), outside the connection's
error-sanitization boundary; it never produces a truncated complete assessment.
Normal retrieval uses three queries: observations, events, adjacent context.
Empty windows add one identity-existence query. Database timeouts/errors propagate
as `PersistenceError`; disabled storage also raises PersistenceError. Invalid
requests raise ValueError. No HTTP status mapping is introduced.

Empty results still return the engine's unavailable assessment, with additional
reasons distinguishing unknown asset, unknown source/run, an empty receipt window
for a recorded combination, and no observations for an otherwise known
asset/source/run combination. Single/poor-quality evidence retains the engine's
partial/unavailable policy. Successful bounded snapshot retrieval sets
`evidence_complete=True`: this means retrieved evidence, not continuous physical
sampling or present-day health. Repeatability assumes unchanged persisted evidence.

One nearest predecessor before start and successor at/after end are fetched in
the same context. They never enter the in-window indicator counts, references,
latest timestamps or availability. The service evaluates each boundary pair
separately through the unchanged pure engine and appends labelled boundary
sequence/time findings, including observation IDs, to overall reasons. Thus an
otherwise available in-window assessment can have an external boundary warning;
availability is expressly about the selected window. No boundary conclusion is
made for an empty window or an absent neighbour. This preserves health.v1's
approved half-open semantics rather than manufacturing in-window samples.

Tests reuse generated PostgreSQL schemas, never public history. Capacity-edge
integration tests temporarily lower the internal constant to exercise exact-limit,
observation-overflow and event-overflow paths with small real datasets.
## Read-only HTTP API

`GET /api/twins/{asset_id}/health-assessment`

Required query parameters:

- `source`: exact source identifier, 1–200 characters, not whitespace-only.
- `run_id`: exact run identifier, 1–200 characters, not whitespace-only; no UUID coercion.
- `start`, `end`: timezone-aware datetimes defining the half-open **receipt-time**
  window `[start, end)`, positive and at most 24 hours.
- `assessment_generated_at`: caller-supplied timezone-aware evaluation timestamp.
  It is required, with no hidden wall-clock default. The returned UTC value is
  the actual timestamp used by the pure calculation, not a server receipt-time
  assertion. Equal requests and unchanged stored evidence are reproducible.

`asset_id` is a nonblank canonical ID. Source timestamps are never substituted for
receipt-window bounds. Use ISO 8601 with `Z` or a numeric offset; URL-encode `+`
as `%2B`. For example (replace asset/run with actual persisted identifiers):

```text
/api/twins/ASSET_ID/health-assessment?source=factory_simulator&run_id=RUN_ID&start=2026-10-24T10:00:00Z&end=2026-10-24T10:01:00Z&assessment_generated_at=2026-10-24T10:02:00Z
```

The response model is the existing `Assessment` (`health.v1`, method
`observed_condition_rules`). There is no live-registry existence gate: historical
assets remain queryable. Unknown asset/run, empty evidence and insufficient
evidence return **200** with the service's existing availability/reasons, never a
fabricated healthy or zero-valued assessment.

| HTTP status | Meaning |
| --- | --- |
| 200 | Assessment, including partial/unavailable historical results |
| 422 | Missing/malformed parameters, naive timestamps, invalid/over-24-hour window, or `HistoryWindowTooLarge` |
| 503 | Persistence disabled or `PersistenceError`; safe generic detail |
| 500 | Unexpected service/evidence failure; generic `Health assessment failed`, without internal exception details |

Request validation is separate from service execution: unexpected ValueErrors
from stored evidence are internal errors, not leaked as client-validation text.
No rule calculations live in the route. The GET never invokes synchronization,
machine control, migrations or database writes. The application's independent
background synchronizer retains its existing behavior. `/health` remains
application liveness; this endpoint is a historical evidence assessment, not a
current-health or predictive-health claim. The dashboard's Health Assessment view
now consumes this endpoint; see [operator-dashboard.md](operator-dashboard.md).
