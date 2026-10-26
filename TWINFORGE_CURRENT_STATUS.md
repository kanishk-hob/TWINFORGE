# TWINFORGE - Current implementation and teammate handoff

Updated: 2026-10-26. This document replaces the previous status file at the user's request.
It describes the working tree, including uncommitted changes, rather than only the last commit.

## 1. Current position

TWINFORGE is a retrofit-first manufacturing digital-twin and decision-support MVP.
The application includes live twins, optional PostgreSQL history, independent KPI and
observed-condition calculations, statistical predictive screening, maintenance timing
comparisons, recommendations, and a six-view operator dashboard.

The product is implemented but full real-browser acceptance remains pending. Recent
unit/API checks pass; real PostgreSQL regression tests were skipped in the latest run.
Live persistence and historical HTTP reads have separately been observed working.
Do not confuse those limited live checks with a full database regression pass.

- Branch: `chaitanya_main`.
- HEAD: `e2b6ae4eb330008aaa563d40d0a73ba0e67848c6`.
- HEAD subject: `feat: add predictive maintenance, what-if simulation, recommendations and decision support`.
- Important work remains uncommitted; do not reset, clean, stash, switch branches,
  overwrite changes, or commit/push without the user's instruction.
- Factory Simulator is a separate repository and process. Never modify it as a
  shortcut to fixing TWINFORGE.

## 2. Architecture and ownership

```text
Separate Factory Simulator (normally localhost:8000)
  -> HTTPX snapshot connector
  -> serialized automatic SyncService
  -> canonical mapper / MachineTwin
  -> PostgreSQL transaction when configured
  -> in-memory TwinRegistry
  -> FastAPI twin/status/history/calculation APIs (localhost:8001)
  -> same-origin vanilla-JavaScript operator dashboard
```

Storage commits accepted observations before publication to the registry. Increasing
sequences are accepted per run; duplicates and older observations do not create
repeated history. Run changes permit sequence resets. Failed polls retain last-known
twins. Database failures are reported and retried by subsequent polls; intermediate
source snapshots can be lost during outages because there is no durable replay queue.
The registry starts empty after restart and repopulates through synchronization, not
by loading historical rows.

The frontend uses native JavaScript modules, hash routing, shared URL selection,
uPlot charts, and esbuild. TypeScript checks selected JavaScript/contracts; this is
not a React/Next.js application. FastAPI serves static assets at `/dashboard/`.
There is no separate frontend server required after building.

The dashboard calls TWINFORGE APIs, not simulator control APIs. Decision Support
uses two calculation-only POST requests; describing all dashboard traffic as GET-only
would be incorrect. Neither calculation executes maintenance or controls machines.

## 3. Implementation inventory

| Feature | Current status / location | Important limitation |
| --- | --- | --- |
| Simulator connector and automatic synchronization | Implemented; `app/connectors/`, `app/services/sync_service.py` | Depends on separate source; no recovery of every missed snapshot |
| Canonical twins and registry | Implemented; `app/twin/` | Registry is process-local; source health scores remain source-provided |
| Connectivity / freshness | Implemented; `app/main.py`, sync service | Successful browser refresh does not prove source connection; sync age is not transport latency |
| PostgreSQL persistence | Implemented; `app/storage/` | Optional configuration; latest full suite did not exercise real PostgreSQL tests |
| Telemetry / machine events | Implemented and live historical reads verified | Snapshot-observed transitions, not exact physical event times |
| KPI v1 | Independent engine; `app/kpi/`, `docs/kpi-v1.md` | Complete bounded source-time evidence required; several metrics intentionally unavailable |
| health.v1 | Independent observed-condition rules; `app/health/` | Reports recorded evidence, not prediction or physical machine health |
| predictive.v1 / v2 | Rolling Z-score; opt-in Z-score/EWMA; `app/predictive/` | Statistical anomaly/drift screening, not failure probability or remaining useful life |
| Maintenance what-if | Implemented; `app/simulation/` | Frozen current canonical context and caller timing assumptions; no simulator mutation |
| Recommendation policy | Implemented; `app/recommendation/` | Advisory; inadequate evidence leads to manual review; no automatic execution |
| Overview | Implemented; `app/static/dashboard/console.js` | Counts known twins, not complete installed inventory |
| Machines | Implemented; identity, state, telemetry, relationships and history | Missing metadata/telemetry stays unavailable |
| KPI Analytics | Implemented; backend metric cards, context and reasons | No durable historical KPI trend series |
| Health Assessment | Implemented; source scores separate from independent evidence | Requires bounded receipt-time evidence for independent rules |
| History | Implemented; paginated telemetry, events, trends and loaded-data export | Explicit applied asset/run required; initial zero-loaded message can be misleading |
| Decision Support | Implemented; predictive, comparison and recommendation panels | Comparison/recommendation require current run, unlike historical analytics |
| Polling hardening | Uncommitted `refresh.js`, console changes and tests | Real-browser flicker/focus/viewport acceptance still pending |
| Decision action feedback | Latest targeted fix in `decision-view.js` | Browser end-to-end test remains pending; handler fixtures and live APIs tested separately |
| Presentation runner | `tests/presentation_demo.py`, `docs/presentation-demo.md` | Memory mode is temporary evidence, not PostgreSQL persistence verification |

Navigation, selected-machine/run/source URL context, search/state filters, explicit
refresh, loaded-history exports, numeric charts with gap handling, and quality/error
states are implemented. Exports describe loaded records, not all database history.
Missing values are not zero. Source time, database receipt time and browser refresh
time have different meanings and must remain separately labelled.

## 4. Independent results versus source values

- `MachineTwin.health.health_score` and `anomaly_score` are source-reported values;
  they are not independently validated TWINFORGE predictions.
- `kpi.v1` computes quality, reject rate, per-asset good-unit throughput, estimated
  energy, estimated energy per good unit and sampled downtime when inputs suffice.
  API availability, performance, OEE and WIP remain unknown without schedules,
  trustworthy runtime, ideal-cycle and unit-flow evidence. Do not sum upstream and
  downstream throughput into factory output. Sampled downtime is not verified OEE downtime.
- `health.v1` uses `observed_condition_rules`: last-observation fault, observed FAULT
  and OFFLINE states, distinct fault-start/clear events, and evidence discontinuity.
  Empty/limited evidence yields unavailable/partial assessments, not healthy zeros.
- Predictive v1 is default rolling Z-score; v2 is opt-in `z_score_ewma`.
  Existing thresholds must not be tuned merely to manufacture demo alerts.
- What-if estimates maintenance timing only. Missing production, energy and financial
  impacts remain unavailable. Remaining batch duration is a caller assumption.
- Recommendation responses include policy/evidence reasons and approval requirements.
  No durable approval recording, command execution or certified safety decision exists.

## 5. Actual runtime evidence observed on 2026-10-26

These observations are time-specific, not permanent configuration guarantees:

- Port 8001 responded; source `factory_simulator` reported connected.
- `/api/persistence-status` was rechecked while updating this document:
  `enabled: true`, `last_error: null`, `last_persisted_at: 2026-10-26T02:49:57.183176+00:00`.
  This is last successful batch activity, not proof of a new row or an active DB probe.
- Current reported run: `afce30d0f04d49dfbb731a42bdadd4ce`.
- In the preceding diagnosis, current `CNC_01` was IDLE, sequence 0, with no current
  job, null telemetry and invalid/not-fresh quality (`no telemetry`). Persistence
  being enabled does not make those readings sufficient for analytics.
- Historical run `91f340ae5ecf4ceaac7ac9e84cf0032e`, asset `CNC_01`:
  telemetry GET returned 120 rows and history GET returned 40 events, HTTP 200.
  Subsequent cursor pages were empty. Measurements included power, current, speed,
  temperature and vibration. JSON shapes matched the frontend.
- The supplied loaded-history export instead selected the newer run and contained
  one observation and one event. It was not an export of the older 120-row run.
- Live database credentials, exact active database identity and migration tracking
  were not re-inspected in these latest UI fixes. Earlier context names the local
  `127.0.0.1:55432/twinforge_test` instance; verify identity before any schema/test work.
  Do not claim migration 001/002 status was freshly checked here.

### History zero-record diagnosis (not yet changed)

`console.js` applies form fields only when **Open selection** is clicked. The
History view then waits for **Load recorded history**. `evidence-view.js` refuses
requests with an empty applied asset/run. Initially its empty arrays still display
"Loaded 0 telemetry and 0 events", which is not proof of an empty database.

To inspect the known old history: choose CNC_01, factory_simulator and the historical
run above; click Open selection; leave receipt bounds empty initially; click Load
recorded history. Use current source run selects a different run and only fills the
input until Open selection is clicked.

Requests use limit 200 and endpoint-specific exclusive `after_id`; each stream has
an initial 2,000-row cap, extendable explicitly. Source and receipt bounds are filtered
client-side. The backend accepts omitted run filters, but this UI requires a selected
run. Explicit empty `run_id=` is an exact empty-string filter, not all runs.

Recommended remaining UI fix: distinguish not-yet-loaded/missing-selection from a
successfully loaded empty result. This recommendation has not been implemented.

### Decision buttons: latest fix

Both handlers and API paths were correct. The historical selection was blocked by
the current-run prerequisite; errors appeared above the panels while the panels
retained "No result loaded". The fix adds local per-action validation/loading/success/
error feedback and explicit current-run selection guidance, retaining context guards.
Eight regression tests were added. Existing approval policy is unchanged.

Live calculation-only POST checks used a clearly assumed 60-second maintenance
interval, unknown remaining batch duration and no expected-sequence constraint:

- Historical run: both endpoints returned 409, "Requested run does not match current canonical run".
- Current run: comparison returned 200 with partial timing outcomes; recommendation
  returned 200, `manual_review_required`, `INSUFFICIENT_DATA`, human approval required
  and automatic execution false.

To use the buttons: Use current source run -> Open selection -> enter a positive
maintenance duration -> calculate. A current run with insufficient telemetry should
still produce honest partial/manual-review outcomes, not fabricated advice.

## 6. Repository and API reference

| Location | Responsibility |
| --- | --- |
| `app/main.py`, `app/config.py` | FastAPI lifespan/routes and environment settings |
| `app/connectors/`, `app/services/`, `app/twin/` | Source acquisition, sync, canonical model/registry |
| `app/storage/postgres.py`, `app/storage/models.py` | Persistence, bounded reads, serialized records |
| `app/storage/migrations/001_initial.sql`, `002_kpi_inputs.sql` | Versioned schema; nullable KPI raw inputs added in 002 |
| `app/kpi/`, `app/health/`, `app/predictive/` | Independent calculations and evidence services |
| `app/simulation/`, `app/recommendation/` | Read-only timing model and advisory policy |
| `app/static/dashboard/` | Frontend modules, styles and generated build directory |
| `frontend/` | npm manifest/lockfile, build and checks; not separate application server |
| `tests/`, `tests/dashboard/` | Python and dependency-free Node tests |
| `docs/` | Versioned contracts and operator/demo instructions |

| Method/path | Contract |
| --- | --- |
| `GET /health` | Application liveness, not database health |
| `GET /api/twins`, `/api/twins/{asset_id}` | Current canonical twins/detail |
| `GET /api/source-status` | Run, connection, latest sync/attempt, failure/freshness |
| `GET /api/persistence-status` | Enabled, last successful batch time, safe error |
| `POST /sync` | Explicit synchronization; not used by dashboard controls |
| `GET /api/twins/{asset_id}/telemetry` | Observation array; limit 1-1000, after_id >= 0, optional exact run_id |
| `GET /api/twins/{asset_id}/history` | Event array; independent cursor, same pagination/filter contract |
| `GET /api/twins/{asset_id}/kpis` | Required run_id/start/end; source defaults factory_simulator; source-time window |
| `GET /api/twins/{asset_id}/health-assessment` | Required source/run_id/start/end/assessment_generated_at; receipt-time window |
| `GET /api/twins/{asset_id}/predictive-health` | Required run_id; method rolling_z_score (default) or z_score_ewma |
| `POST /api/scenarios/maintenance/compare` | Current asset_id/run_id, positive maintenance_duration_seconds; optional remaining_batch_seconds/expected_sequence |
| `POST /api/recommendations/maintenance` | Same assumptions plus predictive_method; dashboard explicitly requests z_score_ewma |

KPI and health HTTP windows are timezone-aware, positive and at most 24 hours.
KPI boundaries must match recorded source timestamps; health uses half-open receipt
bounds [start,end) and a caller-supplied generation timestamp. Health retrieval caps
each evidence stream at 10,000; KPI caps observations at 10,000. Excess is an explicit
error, not silent completeness. Read actual schemas at `/docs` or `/openapi.json`.

Unknown/empty history is HTTP 200 with []; unavailable storage is 503. KPI/health
empty evidence returns explicit unknown/unavailable results. Invalid requests are
422. Decision context conflicts are 409; unknown current assets are 404. Recommendation
can return a safe review result when predictive storage/evidence is unavailable.

## 7. Fresh-clone setup (PowerShell)

Prerequisites: Python 3.11+ and PostgreSQL 14+ per README; Node/npm for the existing
lockfile/build. No Node engines constraint is declared; latest build ran on Node
26.5.1. Each teammate runs their own services/database unless explicitly configuring
a shared environment. Never assume the author's local data or credentials are included.

From the TWINFORGE root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

Backend configuration is read from process environment. `.env.example` and
`frontend/.env.example` are templates, NOT automatically loaded files.

| Variable | Default / use |
| --- | --- |
| `TWINFORGE_SIMULATOR_URL` | `http://127.0.0.1:8000` |
| `TWINFORGE_SYNC_POLL_INTERVAL_SECONDS` | 1 second between completed attempts |
| `TWINFORGE_SIMULATOR_TIMEOUT_SECONDS` | 2 seconds |
| `TWINFORGE_SOURCE_STALE_AFTER_SECONDS` | 5 seconds |
| `TWINFORGE_DATABASE_URL` | Unset = no persistence |
| `TWINFORGE_DATABASE_TIMEOUT_SECONDS` | 5 seconds |
| `TWINFORGE_KPI_MAX_GAP_SECONDS` | 5 source-time seconds; does not forgive sequence gaps |
| `TWINFORGE_API_BASE` | Build-time empty same-origin prefix; optional proxy path, never credentials |
| `TWINFORGE_TEST_DATABASE_URL` | Opt-in isolated test database only |

Have a PostgreSQL administrator provision a dedicated local database and role if
needed. Verify its identity before migration; do not reset/recreate an existing DB.
Use private credentials with special characters URL-encoded:

```powershell
$env:TWINFORGE_DATABASE_URL = 'postgresql://YOUR_USER:YOUR_PASSWORD@127.0.0.1:YOUR_PORT/YOUR_DATABASE'
# Only after verifying this is the intended database:
.\.venv\Scripts\python.exe -m app.storage.migrate
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Migrations are explicitly applied and recorded in `schema_migrations`; application
startup does not create tables. Do not modify previously applied migrations.
Without a database URL, live twins still work but stored-history analytics do not.
Do not commit environment files, credentials, dumps, logs or build/dependency output.

In a separate terminal and the separate simulator checkout, using its environment
and setup instructions, the existing runbook uses:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Do not start duplicate services on occupied ports. Open:
`http://127.0.0.1:8001/dashboard/`; API docs: `http://127.0.0.1:8001/docs`.
Hash navigation includes overview, machines, kpi, health, history and decision.
Build after frontend changes; `npm.cmd --prefix frontend run dev` watches builds.

## 8. Verification evidence and commands

The following checks actually ran during the immediately preceding Decision Support
fix on 2026-10-26. They were not rerun solely to rewrite this document.

| Command / check | Observed result |
| --- | --- |
| `node --test tests/dashboard/decision.test.mjs` | Final run: 28 passed, 0 failed; includes eight new regression tests |
| `npm.cmd --prefix frontend test` | 69 passed, 0 failed |
| `npm.cmd --prefix frontend run typecheck` | Passed |
| `npm.cmd --prefix frontend run lint` | Passed |
| `npm.cmd --prefix frontend run build` | Passed after outside-sandbox retry; initial esbuild directory access failure was environmental |
| `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v` | 143 discovered: 127 passed, 16 skipped, 0 failed |
| `git diff --check` | Passed; Git emitted an existing status-document line-ending warning |
| Live status/history/calculation HTTP checks | Results recorded above; not browser acceptance |

Backend test subprocess deliberately omitted application/test DB URLs, preserving
parent configuration and avoiding database writes. Skips were real PostgreSQL tests
with no isolated test URL configured. No migration/database reset was run for these
fixes. Earlier 55/61 frontend counts are superseded by 69; earlier database-verified
reports are historical evidence, not the latest suite result.

`compileall` was not rerun for the latest frontend-only fix. Full browser console,
network, viewport, keyboard and end-to-end interaction acceptance remains pending.
Button behavior was exercised with minimal controlled DOM fixtures; live API calls
were separate. Server-console logs were not inspected for that diagnosis.

For future DB integration verification, first confirm a dedicated `twinforge_test`
database and safe access. Existing tests create unique `tf_test_<uuid>` schemas,
apply migrations in those schemas and clean up only their own schemas. Do not run
those tests against production or assume a database name alone proves safe ownership.

## 9. Presentation and manual acceptance

See `docs/presentation-demo.md` for the exact isolated rehearsal and limitations:

```powershell
.\.venv\Scripts\python.exe -B tests/presentation_demo.py --simulator-repo "../factory simulator" --mode memory --interactive
```

Use the dynamically printed demo URL, not normal port 8001. This mode uses genuine
isolated simulator-generated snapshots and a temporary memory evidence adapter;
it is NOT durable PostgreSQL. Event-history/KPI/health-history endpoints unavailable
in memory mode return 503. The runner does not mutate the shared simulator and owns
its temporary processes. PostgreSQL mode requires verified isolated infrastructure.

The runbook records an earlier memory rehearsal: 120 target observations, baseline
v2 WARNING at step 60, CRITICAL/manual-review at step 90, and first post-injection
alerts at step 61. Baseline alerts also occurred, so these are not proof of prediction
accuracy. No later failure established warning lead time. This document update did
not rerun the demonstration or independently revalidate its artifacts.

Manual checklist before presentation:

1. Load all six views at desktop/mobile widths; inspect console/network, labels,
   keyboard focus, chart/table overflow and no broken assets.
2. Verify Overview polling preserves filters, selection, focus and scroll without
   full-page reload or panel flicker. Browser refresh time differs from last sync.
3. On a privately controlled source only, check disconnect/reconnect: retain
   last-known data, expose errors, recover on polls. Never disrupt shared services.
4. Load the known historical run explicitly; inspect telemetry/events, gap handling,
   independent pagination and export scope. Use recorded source bounds for KPI,
   receipt bounds for health.
5. Apply the current run for Decision Support, enter honest timing assumptions,
   verify both actions show local feedback and operator-approval requirements.
6. Test run change only in an isolated rehearsal; old decision context must be
   invalidated/409, not silently combined with new evidence.

## 10. Remaining priorities and boundaries

1. Complete actual browser acceptance of the updated feedback and polling behavior.
2. Improve History's not-yet-loaded versus empty-result messaging; no backend fix
   was indicated by the historical read diagnosis.
3. Obtain sufficient valid/fresh observations in a safe controlled run. Do not
   change thresholds, rewrite timestamps or use old-run evidence as current advice.
4. Reverify database identity/migrations and run isolated PostgreSQL integration
   tests when explicitly authorized; validate full durable demo separately.
5. Review accumulated uncommitted changes before any requested commit; do not
   equate passing unit tests with complete presentation acceptance.

Planned, not implemented in this checkout's verified scope: physical industrial
connectors beyond simulator REST, validated failure prediction/RUL, ML models,
durable maintenance approval/audit execution, machine actuation, production
scheduling/unit-flow data for complete OEE/WIP, durable historical KPI/predictive
trend series, authentication/role management, and cloud deployment. These are not
claims of production capability or commitments for the next change.

## 11. Working-tree handoff

At this update the existing modified files were README.md, this status document,
console.js, decision-view.js, docs/operator-dashboard.md and
 tests/dashboard/decision.test.mjs (dashboard paths under app/static/dashboard).
Existing untracked additions were refresh.js, docs/presentation-demo.md,
tests/dashboard/refresh.test.mjs, tests/presentation_demo.py and
tests/test_presentation_demo.py. Generated bundles are not source handoff artifacts.

This status-document replacement is the only intended edit in this update. No
Factory Simulator file, database record, runtime setting, branch or commit was
changed. Future sessions should inspect Git status and actual code before work;
this dated handoff is guidance, not a substitute for verification.
