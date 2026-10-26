# Presentation runbook

Use the existing vanilla JavaScript frontend, FastAPI and calculation contracts.
No algorithm or policy thresholds are changed for this demonstration.

## Normal live workspace

In the **separate Factory Simulator checkout**, use its existing environment:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In **TWINFORGE**, build once and start the existing application:

```powershell
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/dashboard/`. Do not start a second process on an
occupied port. The default connector URL is `http://127.0.0.1:8000`; override with
`TWINFORGE_SIMULATOR_URL` only when intentional. `.env` examples are not auto-loaded.
Normal persistence requires `TWINFORGE_DATABASE_URL` and existing migrations on
the intended database. This runbook does not authorize creating/resetting one.
Without that configuration, history/calculation APIs requiring storage return
unavailable; current canonical twins still work.

## Reliable isolated rehearsal (no database required)

From the TWINFORGE repository, adjust the sibling simulator path if needed:

```powershell
.\.venv\Scripts\python.exe -B tests/presentation_demo.py --simulator-repo "../factory simulator" --mode memory --interactive
```

The runner prints its **own dynamic loopback dashboard URL** with actual asset
and run selection. Open that URL, not the normal port 8001. It pauses at steps
60 and 90, and again before exit. Press Enter in the terminal to continue.

1. At step 60, show Overview and Machines, then Decision Support. The baseline
   may already alert: this is a statistical screening limitation, not hidden.
2. In Decision Support enter maintenance duration **120 seconds** and remaining
   batch duration **180 seconds**. These are caller assumptions, not measured job
   progress. Click **Use observed sequence**, then generate the recommendation.
   Its response contains the exact predictive and what-if evidence used.
3. Press Enter in the terminal. At step 90 refresh the UI, use the new observed
   sequence, and regenerate. Expect active degradation, high statistical risk,
   partial timing outcomes and **manual review required**, not automatic action.
4. Show explanatory reasons, unavailable production/energy impacts and operator
   approval text. Source health scores are separate from independent screening.
5. Enter continues to the final summary; Enter again closes only demo servers.

Use each pause promptly: persisted/temporary observation receipt age really
expires after 60 seconds under the existing recommendation policy. Duplicate
polls do not make an old observation new. An aged recommendation becoming manual
review is correct. Restart the rehearsal for a fresh presentation; do not alter
freshness limits or forge timestamps.

The runner generates **real snapshots from an isolated simulator instance** in
a subprocess with `-B`, seed 42, one-second source steps and deliberately long
cycle times `(1000,1000,1000)` to control operating-state changes. It captures
60 baseline steps, injects degradation on its private instance at source step
60, and captures through step 120. It writes source events/captures to a new
temporary directory, not into the simulator checkout. No shared simulator HTTP
endpoint is called. The replay source serves only `GET /api/v1/snapshot`.

The existing HTTPX connector, SyncService, registry, predictive engines, timing
model, recommendation policy and FastAPI routes are exercised. The runner waits
for each source sequence in the registry and evidence store before advancing.
It checks deduplication and calculation non-actuation. It uses free loopback
ports and never stops services it did not start.

**Memory mode is NOT PostgreSQL verification.** Its visible banner and
persistence-status endpoint identify temporary memory; no durable history is
claimed. Temporary raw telemetry can be inspected; event history, KPI and
health-history calculations return 503 rather than being fabricated. Source
event logs remain available in the printed evidence directory. This adapter is
demo-only; production imports and API contracts are unchanged.

## Full persistence demo, only with verified test infrastructure

No test URL was configured and no PostgreSQL container was running during the
implementation session. Do not use a development/production database instead.
When an administrator has provided an existing isolated local `twinforge_test`:

```powershell
$env:TWINFORGE_TEST_DATABASE_URL = 'postgresql://TEST_USER:TEST_PASSWORD@127.0.0.1:55432/twinforge_test'
.\.venv\Scripts\python.exe -B tests/presentation_demo.py --simulator-repo "../factory simulator" --mode postgres --interactive
```

Replace placeholders privately; do not commit credentials. The runner validates
the local URL and actual database name, creates a unique `tf_test_<uuid>` schema,
restricts its asyncpg pool search path to that schema, and applies existing
migrations there. It does not create a database. It verifies history events and
health/KPI response contracts in addition to the decision chain. The SQL mode
has **not been executed in this session**. Test-schema privileges are required.

Normal cleanup closes demo servers/pools and drops only the exact schema this
run successfully created, after checking its owner. The uniquely generated
source capture and report directory is retained for review. A forced process
kill may leave a test schema; never bulk-delete schemas or reset a database.

## Observed rehearsal results and interpretation

The memory-mode automated run completed on 2026-10-26: 120 target-machine
observations, no duplicate target sequences, successful HTTP health/static/API
checks, and no shared-service mutation.

- Step 60: v2 `WARNING`, policy `maintenance_after_current_batch` with operator
  approval. This was a **baseline alert**, not proven degradation detection.
- Step 90: v2 `CRITICAL`, policy `manual_review_required` because degradation is
  already an active fault. The policy correctly refuses maintenance selection.
- v1 baseline alert steps: 10, 13, 15, 23, 29, 50.
- v2 baseline alert steps: 41, 42, 44, 45, 50, 51, 53, 54, 55, 56, 58, 59, 60.
- Both first post-injection qualifying alerts occurred at step 61, one source
  second after injection. Because alerts also occurred beforehand, this is not
  proof of diagnostic specificity or a measured causal detector response.
- No later physical failure event was established. **Warning lead time is null.**

The report includes exact source event/run IDs, source timestamps, receipt
timestamps, observation references and all per-step API responses. UUIDs and
receipt times vary across runs; the seeded source trajectory is reproducible.
Statistical risk is not failure probability or remaining useful life. Source
degradation does not automatically become a FAULT-state failure. Timing outcomes
are simplified estimates; no OEE, WIP, throughput gain or energy saving is invented.

## If something fails during the presentation

- No SQL: use the explicitly labelled memory rehearsal and explain its boundary.
- Source service unavailable: the isolated generator does not need the live
  service; it needs only the separate simulator source checkout and dependencies.
- UI unavailable: open the printed `report.json` and `source-capture.json` to
  show actual recorded HTTP results, clearly described as a prior rehearsal.
- Stale evidence/409: refresh context and sequence, or restart the rehearsal;
  never hide or override the review path.
- Browser visual acceptance is not implied by HTTP or Node tests. Verify the
  displayed screens and keyboard/mobile layout manually before presenting.

For an unattended repeatable check, omit `--interactive`. No additional packages
are needed. The demo tests run with normal unittest discovery; the demo itself
is opt-in and never starts from the test suite.
