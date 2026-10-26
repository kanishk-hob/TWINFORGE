# TWINFORGE

For presentation startup, the isolated degradation rehearsal, and honest fallback
instructions, see [the presentation runbook](docs/presentation-demo.md).

For the current implementation, setup, verification and remaining work, start
with [TWINFORGE_CURRENT_STATUS.md](TWINFORGE_CURRENT_STATUS.md).

TWINFORGE is a retrofit-first manufacturing digital-twin service. It polls the
Factory Simulator, maps simulator assets to canonical machine twins, and keeps
the latest accepted twins in memory. PostgreSQL stores accepted observations
and observed machine history when configured.

## Running locally

Build the five-view Operator Dashboard before opening `/dashboard/`:

```powershell
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
```

The existing vanilla-JavaScript frontend is served by FastAPI on the same origin.
See [dashboard setup, API semantics and verification](docs/operator-dashboard.md)
and `frontend/.env.example` for the optional build-time API path prefix.

The Factory Simulator normally runs on `http://127.0.0.1:8000`. Start TWINFORGE
on a different port:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Configuration is available through environment variables:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `TWINFORGE_SIMULATOR_URL` | `http://127.0.0.1:8000` | Simulator base URL |
| `TWINFORGE_SIMULATOR_TIMEOUT_SECONDS` | `2.0` | Timeout for one snapshot request |
| `TWINFORGE_SYNC_POLL_INTERVAL_SECONDS` | `1.0` | Delay between completed poll attempts |
| `TWINFORGE_SOURCE_STALE_AFTER_SECONDS` | `5.0` | Maximum age of the last success before the source is stale |

## Source connectivity

`GET /api/source-status` returns:

- `source`: stable source identifier (`factory_simulator`).
- `connected`: `true` only when the latest attempt succeeded and that success
  is no older than `stale_after_seconds`.
- `run_id`: active simulator run ID, if a snapshot has been accepted.
- `last_sync_at`: UTC timestamp of the last fully mapped successful poll.
- `last_sync_attempt_at`: UTC timestamp when the latest serialized poll began.
- `last_sync_error`: safe error summary for the latest failed poll, otherwise
  `null` after recovery.
- `consecutive_failures`: failures since the latest success.
- `sync_lag_seconds`: elapsed wall-clock seconds since `last_sync_at`, or `null`
  before the first success. This is source freshness age, not network latency.
- `stale_after_seconds`: configured freshness threshold used for `connected`.

A failed poll immediately marks the source disconnected but retains the last
known good twins. The single background loop continues bounded, sequential
retries and recovers automatically. A new simulator run ID clears the old run's
twins before accepting reset sequence numbers.

## Tests

The tests use mocked asynchronous sources and do not need a simulator or
internet connection:

```powershell
python -m unittest discover -s tests -v
```

## PostgreSQL setup and migrations

Requires Python 3.11+ and PostgreSQL 14+. Only `asyncpg` is added; there is no ORM.
Install the dependencies into a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create an empty database and a dedicated owner using your PostgreSQL administrator
account. In `psql`, for example (the password is entered at a prompt):

```sql
CREATE ROLE twinforge LOGIN;
\password twinforge
CREATE DATABASE twinforge OWNER twinforge;
```

Set `TWINFORGE_DATABASE_URL` through your shell or secret manager. For example,
replace the placeholders below with your local values (URL-encode special
characters in credentials):

```powershell
$env:TWINFORGE_DATABASE_URL = 'postgresql://YOUR_USER:YOUR_PASSWORD@127.0.0.1:5432/twinforge'
$env:TWINFORGE_DATABASE_TIMEOUT_SECONDS = '5'
.\.venv\Scripts\python.exe -m app.storage.migrate
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

`.env.example` is a template only; files are not automatically loaded. `.env`
and `.env.*` are ignored except for the credential-free example. Never commit
real credentials. Database errors returned by the service omit DSNs and SQL.

`TWINFORGE_DATABASE_URL` has no default. When absent, existing in-memory mode
continues; history endpoints return 503 and persistence status shows disabled.
When present, persistence is mandatory for successful synchronization. The
positive finite `TWINFORGE_DATABASE_TIMEOUT_SECONDS` defaults to 5 and bounds
each entire database operation, including pool acquisition, transaction, and
commit. The lazily initialized pool holds at most four connections and closes
on lifespan shutdown. Database outages do not prevent `/health` from responding.

Run migrations explicitly before starting the app. Numbered SQL migrations in
`app/storage/migrations` are applied once, in filename order, under a PostgreSQL
advisory lock and transaction; `schema_migrations` records applied versions.
Re-running the command is safe. Do not edit applied migrations: add a new version.
There are no automatic destructive downgrades. Back up persistent databases
before future schema upgrades. Application startup never creates tables.

## Storage semantics and limitations

The canonical `MachineTwin`, simulator connector, and mapper remain separate
from storage. `SyncService` maps a full snapshot, selects increasing sequences,
then commits the batch through `PostgresStore` before updating `TwinRegistry`.
Factories, factory-scoped lines, assets, and source runs are normalized tables.
Observations have a unique `(source, run_id, asset_id, sequence)` key. Older and
equal sequences are skipped, including after a process restart. A new run can
start at sequence zero. As in the existing API, asset IDs must be globally unique;
run IDs must not be reused for unrelated runs. Asset identity records represent
the latest location/type; historical relocation tracking is not implemented.

Telemetry values are JSON objects, preserving source-specific fields without
changing the canonical model. A missing object is SQL NULL, not zero or an empty
object. Invalid/freshness flags and reasons are retained verbatim. Structurally
invalid snapshots and non-JSON numeric values (NaN/infinity) fail the entire batch.
`source_timestamp` is parsed only from a supplied timezone-aware telemetry
timestamp; malformed or naive timestamps remain available as
`raw_source_timestamp` while the parsed field is null. `observed_at` is UTC time
when TWINFORGE observed the batch, not a fabricated source event timestamp.

The first observation in each run produces `state_observed` and, if a fault is
present, `fault_observed`. Subsequent state/fault differences produce
`state_changed`, `fault_started`, or `fault_recovered`. A changed fault code
produces both recovery of the previous code and start of the new code. These
record changes **observed between snapshots**, not exact physical event times.
Unchanged states/faults do not produce repeated events. No cross-run recovery
event is inferred. Telemetry source timestamps are not used as transition times.

Any failed transaction rolls back. The registry, run ID, and last successful sync
timestamp stay unchanged; `/sync` returns 503 for persistence failures. Background
polling retries on its normal schedule. `source-status.connected` is conservative:
when persistence is enabled, synchronization includes a successful database
transaction, so database failures also make it false. Last known good twins stay
available. No durable retry queue is added: the next poll fetches the latest
snapshot, so intermediate observations during outages can be missed. A commit
with a lost acknowledgement can be safely retried because of idempotency.

History survives application restarts. The live registry still starts empty and
is filled by the next successful sync; it is not hydrated from old history. A
stopped or disconnected simulator does not prevent database history reads.
No retention policy or replay is implemented. The independent KPI engine is
described below; it does not reconstruct missing observations.

## Historical read APIs

- `GET /api/twins/{asset_id}/telemetry` returns `ObservationRecord[]`.
- `GET /api/twins/{asset_id}/history` returns `MachineEventRecord[]`.
- `GET /api/persistence-status` returns `enabled` (boolean), `last_persisted_at`
  (UTC timestamp or null), and `last_error` (safe summary or null). These status
  fields are process-local. `last_persisted_at` is the last successful batch
  transaction, including one with no new observations; it is not a database probe.

Both history routes accept `limit` (default 100, range 1–1000), `after_id`
(default 0, nonnegative exclusive cursor), and optional exact `run_id` filter.
Results are ordered by increasing database record ID, representing ingestion
order, not source-time order. To page, pass the last returned `id` as `after_id`.
Cursors belong to their endpoint. Invalid query values return 422. Empty history
and unknown asset IDs return `[]` with 200. Disabled/unavailable storage returns
503 with a safe error message. Reads do not depend on the current registry.

`ObservationRecord` fields: `id`, `source`, `run_id`, `asset_id`, `sequence`,
`observed_at`, nullable `source_timestamp`, nullable `raw_source_timestamp`,
nullable `telemetry_values`, `valid`, `fresh`, `quality_source`, nullable `reason`.
`MachineEventRecord` fields: `id`, `source`, `run_id`, `asset_id`, `sequence`,
`observed_at`, `kind`, nullable `previous_value`, nullable `value`.
The exact Pydantic response schemas are exposed in `/openapi.json` and `/docs`.

Example: `/api/twins/CNC_01/telemetry?limit=50&after_id=0&run_id=run-1`.
Existing successful endpoint contracts are unchanged.

## Isolated database tests

The full suite uses standard-library unittest. With no test database configured,
the PostgreSQL tests are explicitly skipped; mock tests are not proof of SQL
correctness or durability. Run offline tests with the application DB URL unset:

```powershell
Remove-Item Env:TWINFORGE_DATABASE_URL -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app tests
git diff --check
```

For real PostgreSQL verification, create a separate disposable `twinforge_test`
database owned by a test role and set **only** the test URL. Never use production:

```powershell
$env:TWINFORGE_TEST_DATABASE_URL = 'postgresql://TEST_USER:TEST_PASSWORD@127.0.0.1:5432/twinforge_test'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_postgres_integration.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Each database test creates a generated `tf_test_<uuid>` schema, applies the actual
migration, and drops only that schema afterward. The test account needs schema
creation privileges. Tests cover identity/telemetry, state/fault transitions,
duplicate/old sequences, run resets, null and zero values, rollback, migrations,
pagination, reconnection after closing the pool, and history during disconnection.
The restart test reopens storage against the same tables; it does not launch a
second operating-system process. Interrupted tests may leave disposable schemas.

The integration suite refuses any URL whose database path is not exactly
`/twinforge_test`, and confirms `current_database()` before modifying schemas.
Only generated schemas are dropped; existing databases are never reset.

### Explicit process restart and database outage verification

`tests/manual_postgres_recovery.py` is a separate opt-in check, not a mocked test
or part of automatic discovery. It requires a dedicated Docker container named
`twinforge-persistence-verification`, image `postgres:17.11-alpine`, database
`twinforge_test`, and binding `127.0.0.1:55432:5432`. Set
`TWINFORGE_TEST_DATABASE_URL` to that database and `TWINFORGE_TEST_CONTAINER_ID`
to its full container ID. The script validates all these targets before acting:

```powershell
.\.venv\Scripts\python.exe tests/manual_postgres_recovery.py
```

It applies the actual migration, uses a local controlled HTTP snapshot fixture,
launches/restarts a real Uvicorn process, and stops/restarts only that dedicated
PostgreSQL container. It checks retained history, registry repopulation,
deduplication, source disconnection, failed persistence during a database outage,
unchanged success timestamps, and automatic retry with state/fault/recovery
events. It leaves verification observations in the dedicated database and stops
its application/fixture processes. It does not modify the Factory Simulator.

## Independent KPI engine (kpi.v1)

The read-only [Operator Dashboard](docs/operator-dashboard.md) is available at
`http://127.0.0.1:8001/dashboard/` when TWINFORGE is running. It uses the existing
APIs. Build the vanilla-JavaScript frontend using the npm commands above; FastAPI
serves the resulting assets. uPlot provides charts; esbuild bundles the frontend.

Read the versioned [calculation contract](docs/kpi-v1.md) for exact formulas,
input requirements, units, timestamp semantics, and missing-data behavior.
Pure functions are in `app/kpi/engine.py`; `app/kpi/service.py` handles history
retrieval. The HTTP route contains no formulas. No new dependency is required.

Apply migration 002 before running this version with persistence enabled:

```powershell
.\.venv\Scripts\python.exe -m app.storage.migrate
```

The additive migration stores nullable canonical good/reject/total counters and
interval-average power/duration. Existing history is preserved, with null values
for inputs that were not captured. No synthetic backfill occurs. New operational
fields remain internal to canonical twins so existing twin JSON stays compatible.

`GET /api/twins/{asset_id}/kpis` requires `run_id`, `start`, and `end`, with an
optional `source` defaulting to `factory_simulator`. Use timezone-aware ISO 8601
source timestamps (encode `+` as `%2B` in raw URLs, or use `Z`). For example:

```text
/api/twins/QC_01/kpis?run_id=YOUR_RUN&start=2024-01-01T00:00:01Z&end=2024-01-01T00:02:00Z
```

The maximum window is 24 hours and 10,000 observations. Both boundaries must
match stored source timestamps. Results include the normalized UTC window,
asset/source/run identifiers, coverage, completeness reasons, and metric objects
with `value`, `unit`, `status`, and `reason`. Downtime reason seconds are included
only for complete recognized-state windows. The OpenAPI response is `KpiResult`.
Invalid requests or oversized result sets return 422; unavailable storage returns
503; empty/insufficient data returns 200 with unknown metrics rather than zeros.

Supported outputs are quality, reject rate, asset good-unit throughput, integrated
energy, energy per good unit, and sampled downtime/reasons. Energy and downtime
are labelled estimated. Availability, performance, OEE, and WIP are explicitly
unknown through the API because schedules, trustworthy runtime, certified ideal
cycle times, and unit-flow records are absent. Standard OEE formulas are tested
independently using complete synthetic inputs, not simulator precomputed KPIs.

`TWINFORGE_KPI_MAX_GAP_SECONDS` defaults to 5 (positive finite seconds). This is
the maximum tolerated source-time spacing, not a grace period for missing
sequence numbers. Sequence gaps, stale/invalid flags, timestamp regressions,
missing boundaries, and mixed context never become verified zero production or
downtime. Counter resets invalidate counter-based outputs. History queries stay
available after source disconnection; genuinely complete old windows remain valid.

### Controlled reference validation

The explicit script below runs the separate simulator's `Simulator` class in a
fresh subprocess, disables bytecode writes, writes logs only to a TwinForge
temporary directory, and stores observations in a disposable PostgreSQL test
schema. Set `TWINFORGE_TEST_DATABASE_URL` to the dedicated `twinforge_test` database.
The simulator repository and live simulator are not modified:

```powershell
.\.venv\Scripts\python.exe tests/manual_kpi_reference.py --simulator-repo '..\factory-simulator'
```

Verified baseline: seed 42, 120 steps, 360 persisted observations, window
`2024-01-01T00:00:01Z` to `2024-01-01T00:02:00Z` (119 seconds).

| Comparison | TwinForge | Reference for the same window |
| --- | ---: | ---: |
| QC quality | 0.95 | 0.95 |
| QC reject rate | 0.05 | 0.05 |
| QC good units/hour | 574.7899159664 | 574.7899159664 |
| Sum of asset energy (kWh) | 0.1715 | 0.1715 |

The simulator's since-start throughput is 570/hour over 120 seconds; TwinForge
does not invent the missing step-zero telemetry boundary. The simulator's
fault-only downtime is zero in this run, while TwinForge's non-running sampled
durations are 79/59/99 seconds (CNC/MILL/QC), including idle. These definitions
are intentionally different and must not be presented as equivalent OEE downtime.
Line energy-per-good-unit and WIP are not exposed by the asset endpoint. Reference
factory metrics and cumulative energy are stripped from snapshots before sync;
they are used only for the independent comparison assertions.

Run all unit/API and real PostgreSQL regression tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app tests
git diff --check
```
