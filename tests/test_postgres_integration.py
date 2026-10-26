"""Real PostgreSQL tests: opt in with TWINFORGE_TEST_DATABASE_URL.

Only a generated schema is created/dropped; never use a production database.
"""
import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import asyncpg
from app.storage.postgres import PostgresStore, PersistenceError
from app.services.sync_service import SyncService
from app.twin.mapper import simulator_asset_to_twin
from app.twin.registry import TwinRegistry
from app.kpi.service import asset_kpis
from app.health.service import asset_health
from app.health.models import Observation, Event
from test_source_connectivity import make_asset, connection_error


@unittest.skipUnless(os.getenv("TWINFORGE_TEST_DATABASE_URL"), "No isolated PostgreSQL test URL configured")
class PostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dsn = os.environ["TWINFORGE_TEST_DATABASE_URL"]
        if urlsplit(self.dsn).path != "/twinforge_test":
            raise RuntimeError("Integration tests require a dedicated database named twinforge_test")
        self.schema = "tf_test_" + uuid.uuid4().hex
        self.admin = await asyncpg.connect(self.dsn, timeout=5)
        if await self.admin.fetchval("SELECT current_database()") != "twinforge_test":
            await self.admin.close()
            raise RuntimeError("Refusing to modify a non-test database")
        await self.admin.execute(f'CREATE SCHEMA "{self.schema}"')
        self.store = await self.new_store()
        await self.store.migrate()

    async def new_store(self):
        store = PostgresStore(self.dsn)
        store._pool = await asyncpg.create_pool(self.dsn, min_size=0, max_size=2,
            timeout=5, command_timeout=5, server_settings={"search_path": self.schema})
        return store

    async def asyncTearDown(self):
        await self.store.close()
        await self.admin.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        await self.admin.close()

    async def save(self, seq=1, run="run-1", state="RUNNING", fault=None, values=None):
        asset = make_asset(sequence=seq)
        asset["dynamic_state"]["state"] = state
        asset["dynamic_state"]["active_fault"] = fault
        if values is not None:
            asset["dynamic_state"]["values"] = values
        await self.store.save(run, [simulator_asset_to_twin(asset)], datetime.now(timezone.utc))

    async def health_save(self, seq, second, run='health', asset_id='CNC_01',
                          state='RUNNING', fault=None, source_time=None):
        asset = make_asset(asset_id=asset_id, sequence=seq)
        asset['dynamic_state'].update(state=state, active_fault=fault,
                                      last_telemetry_timestamp=source_time)
        await self.store.save(run, [simulator_asset_to_twin(asset)],
                              datetime(2024, 1, 1, tzinfo=timezone.utc)+timedelta(seconds=second))

    async def health_result(self, start=1, end=3, **changes):
        epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
        args = dict(source='factory_simulator', run_id='health', asset_id='CNC_01',
                    window_start=epoch+timedelta(seconds=start),
                    window_end=epoch+timedelta(seconds=end), assessment_generated_at=epoch)
        args.update(changes)
        return await asset_health(self.store, **args)

    async def test_health_receipt_window_mapping_and_isolation(self):
        for seq in range(4):
            await self.health_save(seq, seq, state='FAULT' if seq==1 else 'RUNNING',
                                   fault='jam' if seq==1 else None)
        await self.health_save(1, 1, run='other')
        await self.health_save(1, 1, asset_id='OTHER')
        epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
        evidence = await self.store.health_evidence('factory_simulator','health','CNC_01',
                                                    epoch+timedelta(seconds=1),epoch+timedelta(seconds=3))
        rows = [Observation(**r) for r in evidence['observations']]
        events = [Event(**e) for e in evidence['events']]
        self.assertEqual([r.sequence for r in rows], [1, 2])
        self.assertTrue(all(r.source_timestamp is None for r in rows))
        self.assertEqual(rows[0].active_fault, 'jam')
        self.assertEqual(rows[0].telemetry_values, {'temperature':42.0})
        self.assertEqual([e.kind for e in events], ['state_changed','fault_started','state_changed','fault_recovered'])
        self.assertEqual(len({e.id for e in events}), 4)
        self.assertEqual((evidence['before']['sequence'],evidence['after']['sequence']), (0,3))
        result = await self.health_result()
        self.assertEqual(result, await self.health_result())
        self.assertEqual(result.indicators['fault_start_observations'].value, 1)
        self.assertEqual(result.data_quality.missing_source_timestamps, 2)
        self.assertIn('Unknown persisted source/run', (await self.health_result(source='other')).reasons)
        self.assertIn('Unknown persisted asset', (await self.health_result(asset_id='missing')).reasons)
        self.assertIn('Empty receipt window', (await self.health_result(start=10,end=11)).reasons)

    async def test_health_boundary_context_does_not_enter_indicators(self):
        await self.health_save(0, 0, state='FAULT',fault='jam',source_time='2024-01-01T00:00:00Z')
        await self.health_save(2, 1, source_time='2024-01-01T00:00:02Z')
        await self.health_save(3, 2, source_time='2024-01-01T00:00:03Z')
        await self.health_save(4, 3, source_time='2024-01-01T00:00:03Z')
        result = await self.health_result()
        self.assertEqual(result.data_quality.observation_count, 2)
        self.assertEqual(result.data_quality.sequence_gaps, 0)
        self.assertEqual(result.availability, 'available')
        self.assertEqual(result.indicators['fault_state_observed'].status, 'not_observed')
        self.assertTrue(any('before window' in r and 'sequence_gaps: 1' in r for r in result.reasons))
        self.assertTrue(any('after window' in r and 'nonincreasing_source_timestamps: 1' in r for r in result.reasons))

    async def test_health_limits_are_capacity_errors_not_partial_success(self):
        from unittest.mock import patch
        from app.storage.postgres import HistoryWindowTooLarge
        await self.health_save(0, 1)
        await self.health_save(1, 2)
        with patch('app.storage.postgres.HEALTH_EVIDENCE_LIMIT', 2):
            self.assertEqual((await self.health_result()).data_quality.observation_count, 2)
            await self.health_save(2, 2)
            with self.assertRaises(HistoryWindowTooLarge):
                await self.health_result()
        # One fault observation yields two distinct events; test event cap alone.
        await self.health_save(0, 1, run='fault-run',state='FAULT',fault='jam')
        with patch('app.storage.postgres.HEALTH_EVIDENCE_LIMIT', 1):
            with self.assertRaises(HistoryWindowTooLarge):
                await self.health_result(run_id='fault-run')

    async def test_health_real_storage_failure_is_not_an_assessment(self):
        # Missing application tables in a read-only catalog search path exercise
        # the real DB error path without changing roles, schemas or existing data.
        broken = PostgresStore(self.dsn)
        broken._pool = await asyncpg.create_pool(self.dsn, min_size=0, max_size=1,
            server_settings={'search_path': 'pg_catalog'}, timeout=5, command_timeout=5)
        try:
            epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
            with self.assertRaises(PersistenceError):
                await asset_health(broken, source='factory_simulator',run_id='health',asset_id='CNC_01',
                    window_start=epoch,window_end=epoch+timedelta(seconds=1),assessment_generated_at=epoch)
        finally:
            await broken.close()

    async def test_health_api_reads_persisted_evidence_without_writes(self):
        import httpx
        import app.main as main
        from unittest.mock import patch
        await self.health_save(0, 0)
        await self.health_save(1, 1, state='FAULT', fault='jam')
        await self.health_save(2, 2)
        async with self.store.connection() as conn:
            before = [dict(r) for r in await conn.fetch('SELECT * FROM observations ORDER BY id')]
            before_events = [dict(r) for r in await conn.fetch('SELECT * FROM machine_events ORDER BY id')]
        params = dict(source='factory_simulator', run_id='health', start='2024-01-01T00:00:00Z',
                      end='2024-01-01T00:00:02Z', assessment_generated_at='2024-01-02T00:00:00Z')
        with patch.object(main, 'store', self.store), patch.object(main.sync_service, 'sync_once', AsyncMock()) as sync:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
                response = await client.get('/api/twins/CNC_01/health-assessment', params=params)
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result['data_quality']['observation_count'], 2)
                self.assertEqual(result['indicators']['fault_reported_at_last_observation']['value'], 'jam')
                self.assertEqual(result['indicators']['fault_start_observations']['value'], 1)
                self.assertEqual(result, (await client.get('/api/twins/CNC_01/health-assessment', params=params)).json())
                for overrides in (dict(source='other'), dict(run_id='other')):
                    other = await client.get('/api/twins/CNC_01/health-assessment', params=dict(params, **overrides))
                    self.assertEqual(other.json()['availability'], 'unavailable')
                missing = await client.get('/api/twins/missing/health-assessment', params=params)
                self.assertEqual(missing.json()['availability'], 'unavailable')
            sync.assert_not_awaited()
        async with self.store.connection() as conn:
            self.assertEqual(before, [dict(r) for r in await conn.fetch('SELECT * FROM observations ORDER BY id')])
            self.assertEqual(before_events, [dict(r) for r in await conn.fetch('SELECT * FROM machine_events ORDER BY id')])

    async def test_identity_and_telemetry_round_trip(self):
        await self.save()
        rows = await self.store.history("CNC_01", "telemetry")
        self.assertEqual(rows[0]["telemetry_values"], {"temperature": 42.0})
        self.assertTrue(rows[0]["valid"])
        self.assertIsNotNone(rows[0]["observed_at"].tzinfo)
        async with self.store.connection() as conn:
            identity = await conn.fetchrow("SELECT * FROM assets")
            self.assertEqual(identity["factory_id"], "FACTORY_01")
            self.assertEqual(identity["line_id"], "LINE_01")
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM factories"), 1)

    async def test_transitions_fault_recovery_and_unchanged_state(self):
        await self.save(1)
        await self.save(2)
        await self.save(3, state="FAULT", fault="OVERHEAT")
        await self.save(4)
        rows = await self.store.history("CNC_01", "history")
        self.assertEqual([r["kind"] for r in rows], ["state_observed", "state_changed", "fault_started", "state_changed", "fault_recovered"])

    async def test_duplicate_lower_sequence_and_new_run(self):
        await self.save(10)
        await self.save(10)
        await self.save(9)
        await self.save(0, run="run-2")
        rows = await self.store.history("CNC_01", "telemetry")
        self.assertEqual([r["sequence"] for r in rows], [10, 0])
        self.assertEqual(len(await self.store.history("CNC_01", "history")), 2)

    async def test_missing_invalid_quality_and_zero_are_distinct(self):
        asset = make_asset()
        asset["dynamic_state"]["values"] = None
        asset["dynamic_state"]["last_telemetry_timestamp"] = "bad-time"
        asset["data_quality"].update(valid=False, fresh=False, reason="no telemetry")
        await self.store.save("run-1", [simulator_asset_to_twin(asset)], datetime.now(timezone.utc))
        await self.save(2, values={"temperature": 0})
        rows = await self.store.history("CNC_01", "telemetry")
        self.assertIsNone(rows[0]["telemetry_values"])
        self.assertIsNone(rows[0]["source_timestamp"])
        self.assertEqual(rows[0]["raw_source_timestamp"], "bad-time")
        self.assertFalse(rows[0]["valid"])
        self.assertEqual(rows[1]["telemetry_values"]["temperature"], 0)

    async def test_restart_migrations_and_pagination(self):
        await self.save(1)
        await self.save(2)
        await self.store.close()
        self.store = await self.new_store()
        await self.store.migrate()
        await self.save(2)
        first = await self.store.history("CNC_01", "telemetry", limit=1)
        rest = await self.store.history("CNC_01", "telemetry", after_id=first[0]["id"])
        self.assertEqual([r["sequence"] for r in first + rest], [1, 2])
        self.assertEqual(await self.store.history("missing", "history"), [])

    async def test_failed_batch_rolls_back_and_history_survives_disconnect(self):
        await self.save(1)
        invalid = simulator_asset_to_twin(make_asset(sequence=-1))
        valid = simulator_asset_to_twin(make_asset(asset_id="ROLLBACK_ONLY", sequence=1))
        with self.assertRaises(PersistenceError):
            await self.store.save("run-2", [valid, invalid], datetime.now(timezone.utc))
        async with self.store.connection() as conn:
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM source_runs"), 1)
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM observations"), 1)
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM assets WHERE asset_id='ROLLBACK_ONLY'"), 0)
        service = SyncService(TwinRegistry(), AsyncMock(side_effect=connection_error()), store=self.store)
        with self.assertRaises(Exception):
            await service.sync_once()
        self.assertEqual(len(await self.store.history("CNC_01", "telemetry")), 1)

    async def test_kpi_persisted_window_and_run_isolation_after_restart(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for seq in range(3):
            asset = make_asset(sequence=seq)
            asset['dynamic_state']['last_telemetry_timestamp'] = (start + timedelta(seconds=seq)).isoformat()
            asset['production'] = dict(good_quantity=seq*8, rejected_quantity=seq*2, total_quantity=seq*10)
            asset['extensions'] = dict(last_interval_power_kw=3.6)
            twin = simulator_asset_to_twin(asset, 1)
            await self.store.save('kpi-run', [twin], datetime.now(timezone.utc))
            await self.store.save('kpi-run', [twin], datetime.now(timezone.utc))
        await self.store.close()
        self.store = await self.new_store()
        result = await asset_kpis(self.store, source='factory_simulator', run_id='kpi-run',
            asset_id='CNC_01', start=start, end=start+timedelta(seconds=2), max_gap_seconds=5)
        self.assertEqual(result.observation_count, 3)
        self.assertEqual(result.metrics['quality'].value, .8)
        self.assertAlmostEqual(result.metrics['energy_consumption'].value, .002)
        other = await asset_kpis(self.store, source='factory_simulator', run_id='other-run',
            asset_id='CNC_01', start=start, end=start+timedelta(seconds=2), max_gap_seconds=5)
        self.assertIsNone(other.metrics['quality'].value)
        # Real HTTP serialization backed by PostgreSQL, without a mocked DB.
        import httpx
        import app.main as main
        from unittest.mock import patch
        with patch.object(main, 'store', self.store):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
                response = await client.get('/api/twins/CNC_01/kpis', params=dict(
                    run_id='kpi-run', start=start.isoformat(), end=(start+timedelta(seconds=2)).isoformat()))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['metrics']['quality']['value'], .8)

    async def test_kpi_migration_preserves_legacy_nulls(self):
        # Simulate an existing 001 row by omitting all new optional inputs.
        await self.save()
        async with self.store.connection() as conn:
            row = await conn.fetchrow('SELECT good_count,total_count,interval_power_kw FROM observations')
            self.assertTrue(all(value is None for value in row.values()))
            self.assertEqual(await conn.fetchval('SELECT count(*) FROM schema_migrations'), 2)
        await self.store.migrate()
        self.assertEqual(len(await self.store.history('CNC_01', 'telemetry')), 1)

    async def test_kpi_upgrade_from_001_preserves_existing_observation(self):
        schema = 'tf_test_' + uuid.uuid4().hex
        await self.admin.execute(f'CREATE SCHEMA "{schema}"')
        old = await asyncpg.connect(self.dsn, server_settings={'search_path': schema})
        upgraded = PostgresStore(self.dsn)
        try:
            migration = Path(__file__).resolve().parents[1] / 'app/storage/migrations/001_initial.sql'
            await old.execute(migration.read_text(encoding='utf-8'))
            await old.execute("""CREATE TABLE schema_migrations(version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now());
                INSERT INTO schema_migrations(version) VALUES ('001_initial.sql');
                INSERT INTO factories VALUES ('F'); INSERT INTO lines VALUES ('F','L');
                INSERT INTO assets VALUES ('OLD','F','L','CNC');
                INSERT INTO source_runs VALUES ('factory_simulator','old-run',now());
                INSERT INTO observations(source,run_id,asset_id,sequence,observed_at,
                    source_timestamp,valid,fresh,quality_source,state)
                VALUES ('factory_simulator','old-run','OLD',1,now(),'2024-01-01',true,true,'factory_simulator','IDLE')""")
            upgraded._pool = await asyncpg.create_pool(self.dsn, min_size=0, max_size=1,
                server_settings={'search_path': schema}, timeout=5, command_timeout=5)
            await upgraded.migrate()
            await upgraded.migrate()
            records = await upgraded.history('OLD', 'telemetry')
            self.assertEqual(len(records), 1)
            async with upgraded.connection() as conn:
                self.assertIsNone(await conn.fetchval("SELECT good_count FROM observations WHERE asset_id='OLD'"))
                self.assertEqual(await conn.fetchval('SELECT count(*) FROM schema_migrations'), 2)
        finally:
            await old.close()
            await upgraded.close()
            await self.admin.execute(f'DROP SCHEMA "{schema}" CASCADE')

    async def test_kpi_query_refuses_silent_row_truncation(self):
        await self.save()
        async with self.store.connection() as conn:
            await conn.execute("""INSERT INTO observations(source,run_id,asset_id,sequence,observed_at,
                source_timestamp,valid,fresh,quality_source,state)
                SELECT 'factory_simulator','run-1','CNC_01',i,now(),
                '2024-01-01'::timestamptz + i * interval '1 second',true,true,'factory_simulator','RUNNING'
                FROM generate_series(2,10002) i""")
        from app.storage.postgres import HistoryWindowTooLarge
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(HistoryWindowTooLarge):
            await self.store.kpi_observations('factory_simulator', 'run-1', 'CNC_01', start, start+timedelta(hours=4))

    async def test_predictive_latest_telemetry_and_forward_compatibility(self):
        from app.predictive.service import assess_predictive_health
        for seq in range(1, 36):
            await self.save(seq, values={'temperature': 0 if seq % 2 else 2})
        await self.save(36, values={'temperature':5})
        await self.save(1, run='other', values={'temperature':999})
        latest = await self.store.history('CNC_01', 'telemetry', 31, 0, 'run-1', latest=True)
        self.assertEqual([r['sequence'] for r in latest], list(range(36,5,-1)))
        forward = await self.store.history('CNC_01', 'telemetry', 2, 0, 'run-1')
        self.assertEqual([r['sequence'] for r in forward], [1,2])
        result = await assess_predictive_health(self.store, asset_id='CNC_01', run_id='run-1')
        self.assertEqual(result.status, 'CRITICAL')
        self.assertEqual(result.top_signals[0].baseline_mean, 1)
        self.assertEqual(result.observations_used, 31)
