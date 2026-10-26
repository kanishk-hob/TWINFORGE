# What-If Simulation v1: maintenance timing comparison

`POST /api/scenarios/maintenance/compare` compares `maintenance_now` (A) with
`maintenance_after_current_batch` (B). TWINFORGE owns the orchestration and the
conditional timing calculations. The result is `simulation.v1`, method
`deterministic_maintenance_timing`.

## Execution architecture and simulator inspection

The local Factory Simulator source at `C:/FactorySimulator/factory-simulator`
was inspected before implementation. Its `app/main.py` passes the shared `sim`
instance to `ScenarioRunRegistry.execute` for `POST /api/v1/scenarios/run`.
`app/scenarios.py` calls `simulator.reset(request.seed)`, optionally injects a
fault, then advances that instance. The simulator README also documents that
scenario execution resets shared state and has no rollback. The inspected API
does not expose an isolated fork or restoration of an arbitrary current snapshot.
This is source inspection, not a claim that the running server was exercised.

A separate seeded simulator subprocess can run controlled experiments, as the
existing KPI reference script demonstrates, but it cannot reconstruct current
factory execution from the canonical twin alone: buffers, in-flight unit state,
job progress, RNG state and restoration support are missing. Running a fresh
seed would compare a different initial factory.

V1 therefore uses a small deterministic timing model over a frozen projection
of the selected canonical `MachineTwin`. It does not implement another line-flow
simulator. No simulator endpoint, connector, subprocess, synchronization, database
read/write, migration or machine command is called by the comparison. The normal
background synchronization process continues independently.

The asynchronous route performs snapshot capture and calculation synchronously,
without yielding. Existing SyncService publication also runs without yielding;
within the current single-event-loop application this prevents a run/sequence
change during capture. The frozen context contains only immutable scalar fields.
This is not a cross-process transaction or a general thread-safe registry API.

## Request

```json
{
  "asset_id": "CNC_01",
  "run_id": "run-1",
  "maintenance_duration_seconds": 10,
  "remaining_batch_seconds": 30,
  "expected_sequence": 42
}
```

Use the actual current run and, if supplied, actual current sequence.

| Field | Meaning and validation |
| --- | --- |
| asset_id | Required nonblank canonical asset ID, up to 200 characters |
| run_id | Required nonblank current canonical run ID, up to 200 characters |
| maintenance_duration_seconds | Required caller-modeled stop; finite JSON number, greater than 0, at most 604800 seconds |
| remaining_batch_seconds | Optional caller-assumed remaining processing duration at the captured context; finite JSON number from 0 through 604800 |
| expected_sequence | Optional nonnegative integer; reject if current twin sequence differs |

Durations reject booleans, numeric strings, NaN and infinity. Extra fields are
rejected. The two actions are fixed by this comparison endpoint and appear in the
scenario results; there is no action execution request.

Remaining batch time is **not** derived from a job ID, cumulative production
counters, telemetry, historical throughput or predictive risk. A minimal request
without this assumption still returns the requested stop duration for each
alternative and immediate-maintenance start/end timing. Batch completion,
deferred maintenance timing and total scenario duration remain unknown.

HTTP 200 includes both estimated and partial results. HTTP 404 means the selected
twin is absent in the matching current run; 409 means run/optional sequence no
longer matches (including no current run); 422 means invalid request data.
Persistence need not be configured. GET on this endpoint is not supported.

## Response contract and evidence types

The OpenAPI schema exposes `MaintenanceComparisonRequest`, `CurrentContext`,
`ScenarioResult` and `MaintenanceComparison` in `app/simulation/models.py`.

| Response field | Evidence meaning |
| --- | --- |
| contract_version / method | `simulation.v1` / `deterministic_maintenance_timing` |
| live_state_mutated | Always false; this endpoint has no execution path |
| evidence_basis | `canonical_source_observations_and_caller_assumptions` |
| baseline | Frozen asset/factory/line identity, state, job/fault, relationships, sequence/run, telemetry timestamp, local capture/sync times and quality flags |
| inputs | Validated caller inputs; explicit assumptions rather than measurements |
| scenario_a / scenario_b | Action, timing status, metrics, known involved job labels, assumptions and unavailable reasons |
| deltas_b_minus_a | B minus A, computed only when both metric values exist |
| preferred_scenario | Always null in v1 |
| comparison_rule | Explicit delta direction and reason no overall ranking is justified |
| assumptions / data_quality | Model conditions and context limitations |

Metrics reuse `app.kpi.models.Metric`: `value`, `unit`, `status`, `reason`.
Derived timings use `estimated`; unsupported values use `unknown` with null
value and a reason. A scenario with supported timing has status `estimated`,
even though throughput/energy metrics remain unavailable. Otherwise its status
is `partial`. There are no measured future outcomes.

The baseline contains source-reported observations, not independently measured
physical conditions. `captured_at` is local wall-clock time; `source_timestamp`
remains the source's timestamp. Scenario offsets are seconds from hypothetical
time zero and are not wall-clock completion timestamps.

## Exact calculations

Let D be maintenance duration and R be remaining batch duration. For completion
estimates the context must be connected/recent according to the existing source
status rule, valid, fresh, RUNNING, without an active fault, and have a nonblank
current job label. R must also be provided. No supported context is inferred for
IDLE, FAULT, OFFLINE, BLOCKED, STARVED or other states.

For R > 0:

| Metric (seconds) | A: now | B: after batch | B minus A |
| --- | ---: | ---: | ---: |
| projected_maintenance_downtime_seconds | D | D | 0 |
| maintenance_start_offset_seconds | 0 | R | R |
| maintenance_end_offset_seconds | D | R+D | R |
| current_batch_completion_offset_seconds | R+D | R | -D |
| current_batch_delay_seconds | D | 0 | -D |
| scenario_duration_seconds | R+D | R+D | 0 |

Delay is relative to a no-maintenance completion at R. The common scenario
horizon ends once both the modeled batch and maintenance are complete.
Projected maintenance downtime is the action's modeled stop duration, not total
factory downtime or measured machine unavailability.

For R = 0, the batch is assumed already complete: completion/delay are zero for
both alternatives; maintenance starts at zero and ends at D; both horizons are D.
An already completed batch cannot be delayed retroactively.

For unknown/unsupported R or context, immediate-maintenance start=0 and end=D
and each modeled stop=D remain conditional action definitions; dependent values
and their deltas are null. Missing data is never treated as zero.

With D=10 and R=30, A finishes maintenance at 10 seconds and the batch at 40;
B finishes the batch at 30 and maintenance at 40. Both contain 10 seconds of
maintenance over a 40-second horizon. B completes the batch 10 seconds earlier
but postpones maintenance completion by 30 seconds. Neither is declared best.

## Assumptions and unavailable outcomes

Both results expose their assumptions: work can be paused/resumed without scrap,
restart/setup penalty; maintenance starts immediately at its chosen trigger;
no crew waits, additional faults, blocking, starvation or scheduling constraints;
same work and stop duration for both actions; only the selected machine is modeled.
Maintenance does not reset predictive risk or imply any future fault reduction.

The known current job label is included in `affected_jobs` for supported timing
as the job considered by the model, including B's zero modeled delay. This is not
a complete affected-job inventory: `affected_jobs_complete` is false, and a
missing list does not prove no jobs are affected. Upstream/downstream identifiers
are disclosed as context only; propagation is not computed.

Good-unit impact, throughput impact and energy impact remain null. There is no
batch quantity/yield model, future production-rate model, maintenance power or
restart power model. The KPI engine calculates historical evidence; passing
fabricated future observations into it would not make these forecasts supported.
OEE, WIP, failure probability, monetary savings and RUL are not generated.
Predictive v1/v2 may motivate a comparison but are not converted into failure
odds or maintenance urgency; this endpoint does not fetch or reinterpret them.

More realistic simulation needs canonical batch progress/quantity and cycle
time, buffers/routing and in-flight work, preemption/restart/scrap rules,
maintenance resources and effects, operating power profiles, and an isolated
simulator checkpoint/fork/restore interface. A future execution adapter can use
that interface while TWINFORGE keeps scenario selection and comparison ownership.

## Verification

`tests/test_simulation.py` covers hand-calculated timings/deltas, zero remaining
work, partial evidence, state/quality gates, nonfinite and malformed inputs,
run/sequence conflicts, detached immutable context, repeated deterministic
outcomes, API/OpenAPI contracts and absence of source/storage/sync side effects.
These are model and API tests; no live-simulator comparison is claimed.
