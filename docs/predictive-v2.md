# Predictive maintenance v2: independent EWMA trend screening

## API and compatibility

The existing endpoint and default remain `predictive.v1`, `rolling_z_score`:

`GET /api/twins/CNC_01/predictive-health?run_id=run-1`

Opt in to the combined detector:

`GET /api/twins/CNC_01/predictive-health?run_id=run-1&method=z_score_ewma`

This returns `contract_version=predictive.v2`, `method=z_score_ewma`.
All existing fields remain. `risk_score` is combined risk, and each signal's
`risk` is its combined risk. Top-level `z_score_risk` and `ewma_risk` disclose
method maxima. Each signal adds `z_score_risk`, a detailed `ewma` object and
`dominant_method`; top-level dominant signal/method and explanation identify the
strongest contributor. Ties choose rolling_z_score, then alphabetical signal.
V1 gains nullable fields in its schema but retains its calculation and defaults.
The v1 baseline_mean/std/z_score fields still describe the recent Z-score baseline;
EWMA's distinct reference statistics are under `ewma`.

## Evidence and configuration

Uses the same persisted raw `ObservationRecord.telemetry_values` and bounded
`PostgresStore.history(..., latest=True)` path. No SQL/schema changes, simulator
scores, source calls or database writes. V2 reads up to 60 recent persisted IDs,
orders ascending, and partitions the oldest 30 as reference and remaining 10-30
as monitoring. At least 40 records are required. The current reading is included
in monitoring, never in the reference. Z-score keeps the v1 rule of comparing
current against up to 30 immediate predecessors, excluding current.

Constants live in `app/predictive/config.py`:
- BASELINE_SIZE=30 (reference and rolling Z-score baseline size)
- EWMA_MONITOR_SIZE=30, EWMA_MIN_MONITOR_OBSERVATIONS=10
- EWMA_ALPHA=0.2
- WARNING_THRESHOLD=0.45, CRITICAL_THRESHOLD=0.75

V2 conservatively requires an intact useful series for each signal across the
selected records: valid, fresh, finite numbers, excluding booleans. Missing or
invalid samples exclude that signal from combined scoring rather than impute or
compress time across gaps. Other complete signals can still be scored; NORMAL
only describes those signals. No eligible signal returns INSUFFICIENT_DATA.
Partial reference windows are not substituted. The method-independent v1 minimum
of ten readings remains unchanged for default requests.

## Exact calculation

Let mu and sigma be population mean and population standard deviation of the
30 reference values. Initialize E_0=mu. For monitoring values x_1,...,x_n:

    E_t = alpha*x_t + (1-alpha)*E_(t-1)
    s_t = sigma * sqrt(alpha/(2-alpha) * (1-(1-alpha)^(2*t)))
    D_t = (E_t-mu)/s_t

Code uses the algebraically equivalent E_t=E_(t-1)+alpha*(x_t-E_(t-1)) for
numerical stability. D_n is signed; both upward and downward deviations count.
The finite-start scale assumes independent stationary reference noise with a
known reference mean/variance; estimated reference statistics make it heuristic.

Both methods use risk(d)=clamp((abs(d)-1)/3,0,1).

    signal_combined = max(z_score_risk, ewma_risk)
    risk_score = max(signal_combined across eligible signals)

This avoids averaging away an alert. The highest combined signal/method is
reported explicitly. WARNING begins at .45 and CRITICAL at .75; lower scores are
NORMAL. These scores measure statistical deviation, not failure probability.

An unchanged zero-variance baseline yields zero deviation/risk. A changed
zero-variance baseline yields null deviation/risk plus a reason. If all methods
are unscorable, return INSUFFICIENT_DATA and null combined risk. Unscorable
methods also prevent an otherwise NORMAL result; a scored WARNING/CRITICAL is
retained with an explicit partial-evidence reason. Numeric overflow is an
assessment failure and is sanitized by the API rather than emitted as JSON NaN.

## Limitations

The reference is held fixed during each evaluation, but moves as the 60-record
retrieval window advances. EWMA is stateless/recomputed per request: prolonged
drift eventually enters the reference. No permanent healthy calibration or
stored EWMA state is claimed. Startup with already degraded data can normalize
that condition. EWMA can respond to spikes as well as trends; it does not prove
sustained physical degradation. Alpha and thresholds require machine-specific
benchmarking, including false alarms, correlated noise and warning lead time.

There is no time-aware decay, state/load segmentation, physical sampling-gap
validation or wall-clock freshness check. Counts are samples, not durations.
Missing one signal can reduce coverage; unsupported and excluded signals are
not healthy. Latest means persisted ID in the requested run. No RUL, failure
probability, Isolation Forest, dashboard, health.v1 or KPI changes are included.
