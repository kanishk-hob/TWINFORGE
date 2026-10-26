# Operator Dashboard · Milestone 4

Read-only HTML/CSS/JavaScript modules served by FastAPI at
<http://127.0.0.1:8001/dashboard/>. The operator dashboard reuses the
existing vanilla-JavaScript frontend. It uses uPlot for charts and esbuild for the
production bundle; there is no separate frontend server or framework. Source strings are rendered
as text. Dashboard reads use GET; explicit what-if and recommendation calculations
use POST to same-origin TWINFORGE APIs. Both POSTs are read-only calculations; there are
no simulator requests or machine controls. The existing application synchronization
loop still runs independently of the dashboard.

## Start locally

From the TWINFORGE repository, with the existing environment installed:

```powershell
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Node.js and npm are required for the frontend build. `npm.cmd run dev` in
`frontend` watches source changes; FastAPI still serves the built files.
`frontend/.env.example` documents `TWINFORGE_API_BASE`: empty by default, or a
same-origin reverse-proxy path prefix. Set it in the build process environment;
the example file is not auto-loaded. Never put a database DSN in this variable.
Generated files under `app/static/dashboard/build` are ignored by Git; build after
a fresh checkout. `npm.cmd run typecheck` checks the typed API/data boundary;
`npm.cmd run lint` checks JavaScript syntax and unsafe-rendering patterns.

## Views

Hash routes preserve the selected canonical asset, run and source without adding
backend routes: `/dashboard/#/overview`, `#/machines/{encoded_asset_id}`, `#/kpi`,
`#/health`, `#/history`, and `#/decision/{encoded_asset_id}`. Query parameters include `asset`, `run`, `source`,
and overview filters. Use the shared machine/run controls to apply a selection.
The current source run can be copied explicitly; historical run IDs can be entered
manually. No complete run catalog exists. Overview search and filters operate on
known twins; export includes only the filtered loaded dataset.

The overview uses the reference fleet registry and inspection panel. Machine
details render whatever telemetry fields exist for that asset, plus relationships,
job and fault context. Verified simulator-specific unit mappings are isolated in
`data.js`; unknown units are not guessed. Health separates source scores from
independent `health.v1` rules. It calls `/api/twins/{asset_id}/health-assessment`
with source/run, a half-open **receipt** window, and the displayed caller-supplied
assessment timestamp. It makes no prediction or physical-health claim.

The simulator is separate, normally at `http://127.0.0.1:8000`. Configure its URL
through `TWINFORGE_SIMULATOR_URL` if needed. Do not modify that repository.
Without `TWINFORGE_DATABASE_URL`, live twins work but history/KPIs return 503 and
persistence is explicitly disabled. For history, supply the intended local
PostgreSQL DSN (`postgresql://USER:PASSWORD@HOST:PORT/DATABASE`) through the process
environment; never put credentials in frontend files, URLs or Git. `.env` is not
automatically loaded. Follow the README database setup and apply existing migrations
only after confirming the target. Dashboard implementation adds no schema changes.

## Data sources and refresh

| Section | Existing GET API | Behavior |
| --- | --- | --- |
| Known machines / cards | `/api/twins` | Factory/line filters; observed-state counts, raw health scores, telemetry, quality and faults. Counts are not installed inventory. |
| Source | `/api/source-status` | Reported connection, current run, sync times/errors and freshness threshold. Persistence failure can also make source connected false. |
| Persistence | `/api/persistence-status` | Enabled flag and past persistence success/error, not a current DB health probe. |
| Independent health | `/api/twins/{asset_id}/health-assessment` | Explicit receipt-window assessment; no frontend rules. |
| KPIs | `/api/twins/{asset_id}/kpis` | Explicit action, required run/start/end, source defaults to factory_simulator. No client formulas. |
| Telemetry | `/api/twins/{asset_id}/telemetry` | Forward `after_id`, `limit=200`, exact selected `run_id`. |
| Events | `/api/twins/{asset_id}/history` | Same cursor contract; observed state/fault changes, not exact physical transition times. |

Routine requests run together in a non-overlapping batch, then wait three seconds.
Hidden tabs stop scheduling new batches; an in-flight batch can finish. Each GET
has a ten-second timeout. Failed refreshes keep last-known data and show errors.
History/KPI requests are cancelled and generation-guarded on selection changes.
An observed source run change invalidates history and KPI context, clears window
inputs and refetches twins. These separate APIs cannot provide an atomic snapshot;
the UI does not promise one. The explicitly selected run remains in the URL and
must be reloaded after invalidation. Manual asset/run input supports records absent
from the live registry. No complete asset or run catalog exists in the APIs.

## Time, quality and calculations

- Source telemetry timestamps describe simulation time, not receipt wall time.
- `observed_at` is TWINFORGE receipt/observation time, including for machine events.
- Browser refresh time only indicates when the browser obtained a response.
- `last_sync_at` is successful synchronization time, not a source timestamp.
- Health scores have no invented scale, alarm threshold or unit. Telemetry uses
  source field names; null values are unavailable, while actual zero remains zero.

See [kpi.v1](kpi-v1.md). Start/end must include a timezone and match exact persisted
source timestamps, with a positive window of at most 24 hours and at most 10,000
observations. Loaded valid/fresh telemetry provides timestamp suggestions. Returned
coverage, completeness, reasons, units, context and metric status are shown directly.
Availability, performance, OEE and WIP remain unavailable when required inputs are
absent. Energy and sampled downtime retain estimated labels. Sampled downtime is
not verified OEE downtime. Never sum upstream/downstream throughput into line output.
HTTP 422/503 errors remain visible; unknown history/run results are not zero metrics.

## History limits

Each stream initially loads forward in pages of at most 200 up to a 2,000-row
budget. Load More explicitly expands that stream's budget by another 2,000 when
needed. Changing/reopening selection resets the budget and allows a fresh read
after the observed end is reached. Receipt extent,
record IDs and loaded count are shown; there is no claim of complete history.
Pages deduplicate by record ID; a failed later page retains earlier pages for
retry. A short page marks the observed end, not a guarantee that no new rows arrive.

uPlot trends use finite numeric values, actual source-time spacing and raw field
names, with a table alongside. Segments break at run/source changes, nonconsecutive
sequences, invalid/stale quality, missing or reversed time, null and nonnumeric
values. Event sequences are not required to be consecutive. Very large explicitly
expanded histories may slow browser rendering; use a different run or reload the
selection. No server time filtering, reverse paging or total-count contract exists.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app tests
node --test tests/dashboard/logic.test.mjs
node --test tests/dashboard/console.test.mjs
git diff --check
```

Real PostgreSQL tests require `TWINFORGE_TEST_DATABASE_URL` targeting the dedicated
`twinforge_test` database. Existing safeguards create/drop only generated test
schemas. Never point tests at production or reset an existing database.

Dependency-free browser renderer checks are separate from production. Temporarily
serve the repository on loopback with the following command, open
`http://127.0.0.1:8012/tests/dashboard/`, and stop the server afterward. Do not expose
this repository server to a network; it can serve local files.

```powershell
.\.venv\Scripts\python.exe -m http.server 8012 --bind 127.0.0.1
```

Manual browser acceptance checklist (not implied by Python/Node test success):

1. Open `/dashboard/`; verify all assets load, mobile/desktop layout, keyboard
   access, focus outlines and horizontally scrollable tables without page overflow.
2. Verify no twins/loading/missing optional fields; filter factories/lines and
   inspect cards against `/api/twins`. No dummy production data should appear.
3. In browser developer tools block individual GETs: verify source request failure
   differs from reported disconnected, and old cards/status/results remain labelled
   last-known. Persistence disabled/failure must not be called healthy.
4. Load history with valid asset/run. Confirm 200-row requests, 2,000 initial cap,
   explicit extension, deduplicated retry after a failed page, empty history,
   separate timestamps and broken chart lines at gaps/invalid samples.
5. Select exact recorded boundaries; compare KPI values, nulls, reasons, units and
   estimates with the JSON. Check malformed/oversized windows, 422, 503 and empty
   runs; no OEE or throughput aggregation is performed in the browser.
6. Switch selections while requests are pending; old responses must not replace
   the new selection. Observe a source run change using a test fixture (do not
   mutate the shared simulator); historical context must invalidate.
7. Hide/restore the tab and inspect network requests for serialized polling and
   GET reads and the two explicit calculation-only POSTs (`/api/scenarios/maintenance/compare`
   and `/api/recommendations/maintenance`). The dashboard must never call `/sync`
   or simulator mutation endpoints.

Historical verification of the earlier single-page implementation: 56 Python tests passed, including 10 real PostgreSQL
tests on the dedicated local database. All 15 Node tests passed, including the
2,000-row pagination budget, explicit extension, failed-page retention/retry and
KPI null/zero/estimate rendering with a DOM double. Compilation and diff checks
passed. A temporary real TWINFORGE process served the dashboard and all assets
with HTTP 200 and synchronized three twins from the live simulator. Persistence
was disabled for that smoke check to avoid writing existing history; PostgreSQL
correctness was checked separately in isolated schemas. The process was stopped.
Browser automation was unavailable in the
implementation session; the visual/manual checklist and browser renderer harness
remain pending. Node logic tests are not real-browser verification.

## Five-view redesign verification

This session: production build, typed API/data checks, and syntax/safety lint
passed. Node checks include URL state, source uncertainty, receipt boundaries,
unit scoping, exact health requests, error propagation and chart discontinuities.
The real HTTP smoke check served HTML/CSS/bundled JavaScript and synchronized
three canonical twins. Persistence was disabled; this is not a PostgreSQL or
browser-rendering verification. Full browser acceptance at desktop and mobile
widths remains pending because Computer Use could not establish the Windows
browser URL. The earlier browser harness exercises legacy modules only.

Final automated results: 35 Node tests passed. Python discovery ran 96 tests:
81 passed and 15 PostgreSQL tests skipped with "No isolated PostgreSQL test URL
configured". Compilation and `git diff --check` passed. No database verification
is claimed for this frontend session.

Extend the manual checklist above across all five routes at 1440px and 390px:
check navigation/selection reload, search, keyboard focus, no page overflow,
health rule evidence versus source scores, empty/503 states, and real-history
charts. KPI trend series are not available from the backend; the page shows
persisted telemetry context instead of inventing historical KPI calculations.
