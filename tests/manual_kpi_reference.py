"""Controlled simulator reference comparison using isolated PostgreSQL history.

Run: python tests/manual_kpi_reference.py --simulator-repo PATH
Requires TWINFORGE_TEST_DATABASE_URL naming the dedicated twinforge_test DB.
The simulator executes in a separate process with bytecode disabled and logs in
a workspace temporary directory. Its repository and running server are untouched.
"""
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import asyncpg
from app.kpi.service import asset_kpis
from app.services.sync_service import SyncService
from app.storage.postgres import PostgresStore, source_time
from app.twin.registry import TwinRegistry


GENERATOR = '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.simulation import Simulator
from app.config import Config
sim = Simulator(Config(seed=42), log_path=Path(sys.argv[2]))
snapshots = []
for _ in range(120):
    sim.step()
    snapshots.append(sim.aggregate_snapshot(event_limit=0))
print(json.dumps(snapshots))
'''


async def verify(snapshots):
    dsn = os.environ['TWINFORGE_TEST_DATABASE_URL']
    if urlsplit(dsn).path != '/twinforge_test':
        raise RuntimeError('Dedicated twinforge_test database required')
    admin = await asyncpg.connect(dsn, timeout=5)
    if await admin.fetchval('SELECT current_database()') != 'twinforge_test':
        await admin.close()
        raise RuntimeError('Non-test database refused')
    schema = 'tf_test_' + uuid.uuid4().hex
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    store = PostgresStore(dsn)
    try:
        store._pool = await asyncpg.create_pool(dsn, min_size=0, max_size=2,
            server_settings={'search_path': schema}, timeout=5, command_timeout=5)
        await store.migrate()
        baseline = snapshots[0]['factory']['metrics']
        reference = snapshots[-1]['factory']['metrics']
        # Remove all reference metrics/derived totals before passing snapshots to sync.
        for snapshot in snapshots:
            snapshot['factory'].pop('metrics')
            for asset in snapshot['assets']:
                asset['extensions'].pop('energy_kwh_estimated')
            snapshot.pop('jobs')
            snapshot.pop('buffers')
            snapshot.pop('events')
        current = None

        async def fetch():
            return current

        service = SyncService(TwinRegistry(), snapshot_fetcher=fetch, store=store)
        for snapshot in snapshots:
            current = snapshot
            await service.sync_once()
        first, last = snapshots[0], snapshots[-1]
        start = source_time(first['assets'][0]['dynamic_state']['last_telemetry_timestamp'])
        end = source_time(last['assets'][0]['dynamic_state']['last_telemetry_timestamp'])
        results = {}
        for asset in last['assets']:
            result = await asset_kpis(store, source='factory_simulator', run_id=last['run_id'],
                asset_id=asset['asset_id'], start=start, end=end, max_gap_seconds=5)
            assert result.completeness == 'complete'
            results[asset['asset_id']] = result
        qc = results['QC_01']
        good = reference['completed_good_units'] - baseline['completed_good_units']
        rejects = reference['reject_count'] - baseline['reject_count']
        expected_throughput = good * 3600 / (end-start).total_seconds()
        assert math.isclose(qc.metrics['throughput'].value, expected_throughput)
        assert math.isclose(qc.metrics['quality'].value, good/(good+rejects))
        assert math.isclose(qc.metrics['reject_rate'].value, rejects/(good+rejects))
        energy = sum(r.metrics['energy_consumption'].value for r in results.values())
        expected_energy = reference['energy_kwh'] - baseline['energy_kwh']
        assert math.isclose(energy, expected_energy, abs_tol=1e-12)
        assert math.isclose(qc.metrics['energy_per_good_unit'].value,
                            qc.metrics['energy_consumption'].value / good)
        report = dict(scenario='seed=42, 120 sequential simulator steps',
            observations=120*3, window_start=start.isoformat(), window_end=end.isoformat(),
            quality=qc.metrics['quality'].value, reject_rate=qc.metrics['reject_rate'].value,
            throughput_twinforge=qc.metrics['throughput'].value,
            throughput_reference_windowed=expected_throughput,
            throughput_simulator_since_start=reference['throughput_per_hour'],
            energy_twinforge_sum_kwh=energy, energy_reference_windowed_kwh=expected_energy,
            downtime_estimates_seconds={k:v.metrics['downtime'].value for k,v in results.items()},
            simulator_fault_downtime_steps={k:v['downtime_steps'] for k,v in reference['machines'].items()},
            unsupported=['availability','performance','oee','wip'], result='PASS')
        print(json.dumps(report, indent=2))
    finally:
        await store.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulator-repo', required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='kpi-reference-', dir=ROOT/'.venv') as temp:
        output = subprocess.check_output([sys.executable, '-B', '-c', GENERATOR,
            str(args.simulator_repo.resolve()), str(Path(temp)/'events.jsonl')],
            cwd=temp, text=True, timeout=60)
        asyncio.run(verify(json.loads(output)))
