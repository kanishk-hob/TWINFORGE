# Recommendation Engine v1

`POST /api/recommendations/maintenance` generates an advisory maintenance decision
from independently calculated predictive evidence and an existing what-if timing
comparison. It returns `recommendation.v1`, policy `maintenance_policy.v1`.

## Architecture and scope

`app/recommendation/service.py` calls the existing simulation service, which
freezes canonical state and estimates both maintenance alternatives. It then
calls the existing predictive service with a read-through `EvidenceReader`.
The reader records the same bounded telemetry rows used by the predictive
service; no second SQL query, new SQL infrastructure or duplicated statistical
calculation is introduced. There is one history read (up to 60 rows for v2,
31 for v1). Pure `policy.py` consumes these typed results and applies rules.

The request defaults to `z_score_ewma` (`predictive.v2`). The caller can explicitly
select `rolling_z_score` (`predictive.v1`). There is no silent method fallback.
Neither simulator-provided score is read by the recommendation package. The
embedded predictive response is independently calculated from persisted telemetry.
Its textual recommendation is explanatory context, not the action-selection rule.

The existing predictive, simulation, health and KPI meanings are unchanged.
Simulation still returns `preferred_scenario: null`. The new outer response owns
the advisory decision. No simulator request, machine command, synchronization,
database write or automatic action is performed. There is no approval or execute
endpoint: `human_approval_required` describes a required external operator step.
`automatic_execution_allowed` is always false.

## API request

```json
{
  "asset_id": "CNC_01",
  "run_id": "run-1",
  "maintenance_duration_seconds": 10,
  "remaining_batch_seconds": 30,
  "expected_sequence": 60,
  "predictive_method": "z_score_ewma"
}
```

The request inherits the simulation contract: nonblank asset/run, positive
finite maintenance duration up to 604800 seconds, optional nonnegative remaining
batch duration up to 604800 seconds, optional nonnegative integer expected sequence.
Durations reject numeric strings and booleans. Unknown fields are rejected, so
clients cannot inject a risk score, precomputed recommendation or approval flag.
Use the actual current run and sequence. All timing inputs are caller assumptions,
not observations or guarantees. `remaining_batch_seconds` may be omitted, but
this prevents a maintenance recommendation under this policy.

HTTP behavior:

- 200: a recommendation, including degraded monitoring or required manual review.
- 404: no matching canonical twin in the current requested run.
- 409: initial run/expected-sequence conflict, or canonical run, sequence or other
  frozen state changes during the awaited database read. Refresh and retry.
- 422: malformed request or unsupported predictive method.
- 500: unexpected internal failure with a sanitized message.

Disabled/unavailable persistence, empty history, malformed predictive evidence
and calculation validation failures produce a 200 manual-review response with
safe missing-evidence reasons. They do not fabricate a NORMAL result. This new
endpoint's failure behavior does not change the standalone predictive endpoint.

## Evidence alignment and quality gates

The comparison freezes one canonical asset/run/sequence before the database read.
After the await, the service rechecks that canonical identity, sequence, job,
state, fault, quality and source timestamp still match. A newly disconnected or
stale source prevents a usable recommendation even if the sequence is unchanged.
This follows the current single-event-loop registry architecture; it is not a
distributed transaction and cannot guarantee that evidence remains current after
the response is delivered.

The latest persisted observation must match asset, source, run and canonical
sequence. A lagging or ahead-of-registry database snapshot yields manual review.
Its receipt timestamp must be timezone-aware and between 0 and 60 seconds old
at response generation. This uses `observed_at`, not simulator source time.
A frozen simulator that is still being polled can therefore eventually have
stale predictive evidence even while source connectivity remains true.

The bounded predictive window must contain valid/fresh observations and consecutive
increasing sequences. The predictive result must have a finite risk consistent
with its declared status, at least one contributing signal, and no partial or
unscorable-evidence reason. Context must match the simulation baseline. A
canonical state is usable only when connected/recent, valid, fresh, RUNNING and
without an active fault. Non-running or already faulted machines need operator
review because this first policy does not model them.

"Complete timing" means both named alternatives have `status=estimated`, no
comparison data-quality findings, and finite nonnegative estimated values in
seconds for all six existing timing metrics: maintenance downtime/start/end,
batch completion/delay, and scenario duration. A current job and caller-supplied
remaining batch time are consequently required. Unsupported throughput, energy,
good-unit impact and downstream effects remain explicitly unavailable and do not
prevent timing completeness. No preference is inferred from a smaller metric.

`data_quality.classification` is categorical:

- `adequate`: canonical, predictive and timing gates all pass.
- `partial`: at least one gate fails, or timing is incomplete.
- `unavailable`: predictive response is absent or declares INSUFFICIENT_DATA.

The separate `canonical_usable`, `predictive_usable`, `timing_complete` and
`findings` fields explain the category. Adequate means sufficient for this
provisional advisory policy, not statistical confidence, complete sensor coverage,
or physical safety certification. Predictive top signals remain limited to the
chosen method's reported contributors; absent sensors are not declared healthy.

## Exact policy table (evaluated in this order)

| Condition | Action | Status / rule |
| --- | --- | --- |
| Canonical or predictive evidence inadequate | manual_review_required | review_required / R1_EVIDENCE_INADEQUATE |
| Usable NORMAL evidence, timing complete | continue_monitoring | recommended / R2_NORMAL |
| Usable NORMAL evidence, timing incomplete | continue_monitoring | degraded / R2_NORMAL |
| Usable WARNING/CRITICAL evidence, timing incomplete | manual_review_required | review_required / R3_TIMING_INCOMPLETE |
| Usable WARNING, complete timing, B maintenance start <= 300 seconds | maintenance_after_current_batch | recommended / R4_WARNING_BOUNDED_DEFERRAL |
| Usable WARNING, complete timing, B maintenance start > 300 seconds | manual_review_required | review_required / R5_WARNING_DEFERRAL_EXCEEDED |
| Usable CRITICAL, complete timing | maintenance_now | recommended / R6_CRITICAL |

Every maintenance action and manual-review response sets
`human_approval_required=true`; monitoring sets it false. No row enables execution.
For WARNING, the deferral is scenario B's existing
`maintenance_start_offset_seconds`, not its maintenance end or total duration.
Zero deferral is permitted and corresponds to an already completed batch.
CRITICAL prioritization is an explicit policy choice, not a prediction that a
failure will occur before the batch ends. Excessive WARNING deferral is not
silently escalated to immediate maintenance.

Constants in `app/recommendation/config.py`:

| Setting | Value |
| --- | --- |
| MAX_WARNING_DEFERRAL_SECONDS | 300 |
| MAX_PREDICTIVE_RECEIPT_AGE_SECONDS | 60 |
| MIN_MAINTENANCE_EVIDENCE_QUALITY | adequate |
| POLICY_VERSION | maintenance_policy.v1 |

Status/risk boundaries are imported from predictive configuration: NORMAL
`0 <= risk < .45`, WARNING `.45 <= risk < .75`, CRITICAL `.75 <= risk <= 1`.
Risk is not recalculated here. The response includes the effective settings
alongside the policy version. Policy changes should revise the version.
The 300-second limit is a demonstration policy bound, not a validated safe
deferral duration; machine-specific validation and operator judgment are required.

## Response and provenance

`MaintenanceRecommendation` includes:

- `asset_id`, `run_id`, `sequence`, `generated_at` and policy/contract versions.
- `recommended_action`, `recommendation_status`, `rule_id`, `explanation`,
  `human_approval_required`, `automatic_execution_allowed`.
- `predictive_status_used`, `predictive_risk_used` and full
  `calculated_predictive_evidence` (nullable). "Used" denotes evidence considered;
  a displayed risk may be rejected by quality gates, as findings explain.
- `predictive_evidence_reference`: latest persisted observation ID/sequence,
  receipt timestamp/age and sequence alignment result.
- `estimated_scenario_evidence`: unchanged full comparison, including its
  source-reported frozen `baseline`, caller `inputs`, estimates and null metrics.
- `assumptions`, `missing_evidence`, `data_quality` and effective `policy_parameters`.

Observed source state, calculated prediction, caller timing assumptions,
conditional scenario estimates and the policy decision remain distinct.
Missing-evidence lists retain unsupported simulation metrics even when they do
not block this timing-only policy. A quality category is never a confidence
percentage. Unknown evidence remains null.

## Concrete examples

All three examples use fresh matching sequence 60, a RUNNING `CNC_01` with
`JOB_001`, no fault, maintenance duration 10 seconds and remaining work 30 seconds.
The synthetic persisted temperature fixture has 60 readings: `[40,42]` repeated
29 times, then `40`, then the current value below. Both existing engines are used.

| Current value | Predictive v2 status/risk | Recommended action | Approval |
| --- | --- | --- | --- |
| 42 | NORMAL / 0 | continue_monitoring | false |
| 43.5 | WARNING / 0.5 | maintenance_after_current_batch | true |
| 45 | CRITICAL / 1 | maintenance_now | true |

For every example, simulation A finishes the batch at 40 seconds and maintenance
at 10; B finishes the batch at 30 seconds and maintenance at 40. Both have 10
seconds of modeled stop and a 40-second common horizon. The policy chooses
differently despite identical scenario deltas because independent predictive
status and the explicit deferral policy determine the advisory decision.

WARNING decision excerpt (the API also returns the full evidence objects):

```json
{
  "contract_version": "recommendation.v1",
  "policy_version": "maintenance_policy.v1",
  "asset_id": "CNC_01",
  "run_id": "r",
  "sequence": 60,
  "recommended_action": "maintenance_after_current_batch",
  "recommendation_status": "recommended",
  "rule_id": "R4_WARNING_BOUNDED_DEFERRAL",
  "explanation": "WARNING policy permits a caller-modeled deferral of 30 seconds, within the configured 300-second limit; operator approval is required",
  "predictive_status_used": "WARNING",
  "predictive_risk_used": 0.5,
  "human_approval_required": true,
  "automatic_execution_allowed": false
}
```

If remaining work is 301 seconds, WARNING instead requires manual review. If
remaining work is absent, NORMAL monitoring is degraded and both WARNING and
CRITICAL require manual review. Missing, stale, misaligned or invalid predictive
evidence always requires manual review, regardless of the timing assumptions.

## Limitations and prerequisites for real control

This policy is deterministic and explainable but uncalibrated. It inherits
predictive baseline drift/coverage limitations and simulation's assumptions of
preemptible work, no scrap/restart penalty, no additional faults or blocking,
and no resource constraints. It does not estimate failure probability, monetary
savings, RUL, avoided-downtime odds or OEE improvement. Receipt freshness is not
proof of physical sensor freshness. Recommendations are transient; there is no
durable decision/approval audit, expiry enforcement or downstream control path.

Before real control: validate sensor quality and predictive thresholds against
machine-specific outcomes; establish approved maintenance/deferral procedures,
resource availability and restart/scrap rules; add durable evidence/decision and
operator-approval audit records, authenticated authorized control, command
idempotency, context/expiry revalidation at execution, equipment interlocks and
a separately tested control adapter with failure/recovery handling. A returned
approval flag by itself cannot authorize a machine operation.

## Verification

Focused unit/API tests in `tests/test_recommendation.py` cover all policy branches,
the inclusive WARNING limit, human approval flags, missing comparison metrics,
stale/invalid canonical evidence, receipt age and sequence alignment, initial and
in-flight context conflicts, malformed/storage failures, method selection and
API schemas. They exercise the actual predictive and simulation services with
synthetic persisted rows, and verify one read and no source/sync/storage writes.
No live machine operation or calibrated recommendation accuracy is claimed.
