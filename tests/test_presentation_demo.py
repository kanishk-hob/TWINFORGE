"""Safety and evidence semantics for the opt-in runner; no processes or DB writes."""
import unittest
from datetime import datetime, timezone
from presentation_demo import MemoryEvidence, validate_database, timing_report
from app.storage.postgres import PersistenceError
from app.twin.mapper import simulator_asset_to_twin
from test_source_connectivity import make_asset


class DemoSafetyTests(unittest.TestCase):
    def test_database_requires_local_explicit_test_identity(self):
        for value in (None, '', 'postgresql://user:pass@db.example/twinforge_test',
                      'postgresql://user:pass@127.0.0.1/production'):
            with self.assertRaises(ValueError): validate_database(value)
        value='postgresql://TEST_USER:TEST_PASSWORD@127.0.0.1:55432/twinforge_test'
        self.assertEqual(validate_database(value),value)

    def test_timing_records_baseline_alerts_and_delay_not_lead_time(self):
        events=[dict(type='fault_injected',fault='degradation',step=60)]
        rows=[dict(step=s,rolling_z_score={'status':z},z_score_ewma={'status':e})
              for s,z,e in [(50,'WARNING','NORMAL'),(61,'NORMAL','WARNING'),(65,'CRITICAL','CRITICAL')]]
        result=timing_report(rows,events,2)
        self.assertEqual(result['detectors']['rolling_z_score']['baseline_alert_steps'],[50])
        self.assertEqual(result['detectors']['z_score_ewma']['detection_delay_seconds'],2)
        self.assertIsNone(result['warning_lead_time'])


class DemoMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicates_and_run_isolation_preserve_source_and_receipt_time(self):
        store=MemoryEvidence()
        twin=simulator_asset_to_twin(make_asset(sequence=1))
        received=datetime.now(timezone.utc)
        await store.save('one',[twin],received)
        await store.save('one',[twin],received)
        await store.save('two',[twin],received)
        rows=await store.history(twin.asset_id,'telemetry',100,0,'one')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['observed_at'],received)
        self.assertEqual(rows[0]['raw_source_timestamp'],twin.telemetry.timestamp)
        self.assertEqual(await store.history(twin.asset_id,'telemetry',100,rows[0]['id'],'one'),[])

    async def test_memory_rehearsal_does_not_fake_durable_evidence(self):
        store=MemoryEvidence()
        for call in (store.history('A','history'),store.kpi_observations(),store.health_evidence()):
            with self.assertRaises(PersistenceError): await call
