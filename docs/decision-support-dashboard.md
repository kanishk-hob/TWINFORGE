# Operator decision support

The existing vanilla JavaScript dashboard now includes
`/dashboard/#/decision/{encoded_asset_id}?run={run_id}&source=factory_simulator`.
Decision Support is reachable from the sidebar, the overview inspection links,
and Machine Details. Existing routes, selection parameters, visual style,
esbuild bundling and uPlot telemetry charts are retained.

## Workflow and API boundary

1. Select a machine and run with the shared selection bar. The observed-state
   panel shows current job, sequence, state, fault and separate source/sync/browser
   timestamps. Source scores are not inputs to this view.
2. **Calculate predictive condition** explicitly requests
   `GET /api/twins/{asset_id}/predictive-health?run_id=...&method=z_score_ewma`.
   Show status, combined/Z-score/EWMA risk bars, contributing signals, detector,
   explanation, observation counts and database receipt timestamp.
3. Enter the assumed maintenance duration and optional remaining batch duration.
   Blank remaining time means unknown; zero means no remaining processing time.
   Optional expected sequence can be typed or copied with **Use observed sequence**.
   **Compare maintenance timings** calls `POST /api/scenarios/maintenance/compare`.
4. **Generate maintenance recommendation** calls
   `POST /api/recommendations/maintenance` with the same assumptions and
   `predictive_method=z_score_ewma`. It replaces the predictive and what-if panels
   with the exact evidence embedded in that response. Earlier independently
   fetched panels are not silently presented as its input evidence.
5. The operator reviews the policy explanation, rule/version, data quality,
   assumptions, missing evidence and approval requirement. The page has no
   approval-recording or execution controls. Maintenance execution stays outside
   this dashboard.

Requests are centralized in `client.js`; JSON POST support is used by two named
calculation helpers. Regular polling still only reads twins/source/persistence.
Calculations never run automatically on polling or input changes. API schemas are
declared in `contracts.d.ts`; pure validation and display mappings live in
`decision-data.js`; rendering and request lifecycle live in `decision-view.js`.

## Meaning and presentation

- Observed machine state, predictive calculation, what-if estimate and policy
  decision have separate numbered sections. Backend calculations are not repeated
  in the browser.
- NORMAL is green; WARNING amber; CRITICAL red; INSUFFICIENT_DATA neutral.
  Risk bars use the 0–1 statistical-deviation scale and explicitly disclaim failure
  probability. No historical predictive-series chart is invented.
- Policy actions have their own distinct labels: Continue monitoring, Maintenance
  after current batch, Maintenance now, Operator review required (purple).
  The policy action is rendered from `recommended_action`, not guessed from risk.
- Null values are Unavailable, not zero. Scenario metric reasons appear alongside
  values. Both alternatives and B-minus-A deltas are shown. Partial status,
  incomplete job coverage, assumptions and unavailable outcomes remain visible.
- Human approval required is a notice. Automatic execution allowed is displayed
  explicitly; no button can stop/reset/control the simulator or machine.
- Predictive and recommendation evidence timestamps are database receipt times.
  Source telemetry time, captured/generated time, browser fetch time and scenario
  offsets are labeled separately. Scenario completion offsets are not wall-clock
  deadlines. Risk and scenario results may refer to different times unless loaded
  together from a recommendation response.

## Selection, stale evidence and errors

The current backend supports only factory_simulator decision evidence; other
source selections show guidance rather than silently targeting a different source.
What-if/recommendation require a known current twin and selected current run.
Standalone predictive reads can inspect a selected persisted run. The backend
remains authoritative for quality and context checks.

One calculation runs at a time. Requests are aborted and generation-guarded on
navigation/destruction, input edits or observed context changes, so late responses
cannot replace the current view. Changed assumptions label prior estimates and
recommendations as previous/not current advice. Changed observed sequence, job,
state, fault, quality or source connectivity invalidates prior results. Source run
changes follow existing shell behavior: the view remounts with no old results.
Receipt-age expiry from recommendation policy parameters also labels retained
advice as previous when the regular view update runs.

Temporary errors retain same-selection results with an explicit previous-result
notice. HTTP 409 marks all retained evidence as previous and tells the operator
to refresh state and verify run/sequence. HTTP 422 explains assumption validation;
503 explains unavailable persistence/history. Unknown machines and general errors
are explicit. Missing predictive evidence, partial simulation and manual-review
recommendations are renderable successful responses, not fabricated success data.

## Verification and limits

`tests/dashboard/decision.test.mjs` exercises predictive statuses, risk/null
formatting, scenario values and missing metrics, recommendation actions, approval
notices, literal-text rendering, request paths/payloads, 409 handling, retained
results and cancellation/context/input races. It uses a minimal DOM tree to test
rendering and events, not a browser layout emulator.

Frontend tests, typecheck, syntax/safety lint and esbuild run through the existing
frontend scripts. Typing covers API contracts/client and pure data helpers;
the view follows the existing untyped DOM-component convention.

A desktop browser smoke check used an isolated loopback server with synthetic
WARNING evidence, mocked history and simulator synchronization disabled. It
verified navigation, assumptions entry, predictive bars, partial what-if metrics,
manual-review advice and operator approval notice. The fixture aged into stale
canonical state, appropriately yielding manual review. No live production data
or simulator mutation was used. Mobile layout, full keyboard/accessibility audit,
and all error states in a real browser remain manual acceptance work.

The view can be long, and evidence tables scroll horizontally on narrow screens.
Assumptions are not persisted across navigation/run remounts. Advice has no durable
approval/audit workflow. Rapidly advancing sequences can invalidate calculations;
operators must refresh/retry as the backend requires. The underlying predictive,
simulation and recommendation model limitations still apply.
