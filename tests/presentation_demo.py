"""Opt-in isolated simulator replay. Never contacts the shared simulator.

Memory mode is a labelled rehearsal, NOT PostgreSQL verification. SQL mode requires
an explicitly configured local twinforge_test database and owns only one schema.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Thread, Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
import uvicorn
from app.storage.postgres import PersistenceError, PostgresStore, source_time

GENERATOR = '''
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app.simulation import Simulator
from app.config import Config
sim=Simulator(Config(seed=42,cycle_times=(1000,1000,1000)),log_path=Path(sys.argv[2]))
snapshots=[]
for step in range(1,121):
    if step==61: sim.inject('CNC_01','degradation',60)
    sim.step()
    snapshots.append(sim.aggregate_snapshot())
print(json.dumps(dict(snapshots=snapshots,events=sim.log.events,config=sim.config.to_dict())))
'''


class MemoryEvidence:
    """Demo-only ephemeral raw observations; no durable-persistence claim."""
    def __init__(self):
        self.rows = []

    async def save(self, run, twins, received):
        for twin in twins:
            previous = [r for r in self.rows if r['run_id']==run and r['asset_id']==twin.asset_id]
            if previous and twin.sequence <= previous[-1]['sequence']:
                continue
            self.rows.append(dict(id=len(self.rows)+1, source='factory_simulator', run_id=run,
                asset_id=twin.asset_id, sequence=twin.sequence, observed_at=received,
                source_timestamp=source_time(twin.telemetry.timestamp),
                raw_source_timestamp=twin.telemetry.timestamp, telemetry_values=twin.telemetry.values,
                valid=twin.quality.valid, fresh=twin.quality.fresh,
                quality_source=twin.quality.source, reason=twin.quality.reason))

    async def history(self, asset, kind, limit=100, after_id=0, run_id=None, *, latest=False):
        if kind != 'telemetry':
            raise PersistenceError('Event persistence unavailable in memory rehearsal')
        rows=[r.copy() for r in self.rows if r['asset_id']==asset and r['id']>after_id
              and (run_id is None or r['run_id']==run_id)]
        return (rows[::-1] if latest else rows)[:limit]

    async def health_evidence(self, *args):
        raise PersistenceError('Durable health evidence unavailable in memory rehearsal')

    async def kpi_observations(self, *args):
        raise PersistenceError('Durable KPI evidence unavailable in memory rehearsal')

    async def close(self):
        pass


def validate_database(dsn):
    p=urlsplit(dsn or '')
    if p.scheme not in ('postgresql','postgres') or p.hostname not in ('127.0.0.1','localhost') or p.path!='/twinforge_test':
        raise ValueError('Require explicit local TWINFORGE_TEST_DATABASE_URL naming twinforge_test')
    return dsn


def timing_report(results, events, step_seconds):
    injection=next(e for e in events if e['type']=='fault_injected' and e.get('fault')=='degradation')
    report={}
    for method in ('rolling_z_score','z_score_ewma'):
        alerts=[r['step'] for r in results if r[method]['status'] in ('WARNING','CRITICAL')]
        after=[s for s in alerts if s>injection['step']]
        report[method]=dict(baseline_alert_steps=[s for s in alerts if s<=injection['step']],
            first_post_injection_alert_step=after[0] if after else None,
            detection_delay_seconds=(after[0]-injection['step'])*step_seconds if after else None)
    return dict(injection_event=injection,detectors=report,
                warning_lead_time=None,limitation='No subsequent physical failure event is established')


async def run(args, capture, output):
    # Child/application environment is not changed globally. Configure this demo process only.
    import app.main as main
    from app.connectors.simulator import get_snapshot
    from app.services.sync_service import SyncService
    from app.twin.registry import TwinRegistry
    from starlette.responses import HTMLResponse, JSONResponse
    store=MemoryEvidence()
    admin=None
    schema=None
    owner=None
    schema_created=False
    server=None
    task=None
    source=None
    results=[]
    try:
        if args.mode=='postgres':
            import asyncpg
            dsn=validate_database(os.getenv('TWINFORGE_TEST_DATABASE_URL'))
            admin=await asyncpg.connect(dsn,timeout=5)
            if await admin.fetchval('SELECT current_database()')!='twinforge_test':
                raise ValueError('Database identity mismatch')
            owner=await admin.fetchval('SELECT current_user')
            schema='tf_test_'+uuid.uuid4().hex
            await admin.execute(f'CREATE SCHEMA "{schema}"')
            schema_created=True
            store=PostgresStore(dsn)
            store._pool=await asyncpg.create_pool(dsn,min_size=0,max_size=4,
                timeout=5,command_timeout=5,server_settings={'search_path':schema})
            await store.migrate()
        lock=Lock()
        state={'snapshot':capture['snapshots'][0]}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path!='/api/v1/snapshot':
                    self.send_error(404)
                    return
                with lock: data=json.dumps(state['snapshot']).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self,*args): pass
        source=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        Thread(target=source.serve_forever,daemon=True).start()
        async def fetch():
            return await get_snapshot(f'http://127.0.0.1:{source.server_port}')
        main.registry=TwinRegistry()
        main.store=store
        main.sync_service=SyncService(main.registry,snapshot_fetcher=fetch,poll_interval_seconds=.1,store=store)
        label=('ISOLATED SIMULATOR REPLAY — PostgreSQL test schema' if args.mode=='postgres' else
               'ISOLATED SIMULATOR REPLAY — TEMPORARY MEMORY ONLY; no PostgreSQL, durable history, KPI or health evidence')
        @main.app.middleware('http')
        async def demo_label(request,call_next):
            if request.url.path=='/dashboard/':
                text=(ROOT/'app/static/dashboard/index.html').read_text(encoding='utf-8')
                banner=f'<div role="status" style="position:sticky;top:0;z-index:100;background:#fff2c9;color:#463400;padding:12px;text-align:center">{label}</div>'
                return HTMLResponse(text.replace('<body>','<body>'+banner))
            if args.mode=='memory' and request.url.path=='/api/persistence-status':
                return JSONResponse(dict(enabled=False,last_persisted_at=None,last_error='Demo temporary memory; not durable persistence'))
            return await call_next(request)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(main.app,host='127.0.0.1',port=port,log_level='warning'))
        task=asyncio.create_task(server.serve())
        for _ in range(100):
            if task.done(): await task
            if server.started: break
            await asyncio.sleep(.05)
        if not server.started: raise RuntimeError('Demo server did not start')
        run_id=capture['snapshots'][0]['run_id']
        base=f'http://127.0.0.1:{port}'
        url=f'{base}/dashboard/#/decision?asset=CNC_01&run={run_id}&source=factory_simulator'
        print(label, '\nDashboard:',url, '\nEvidence directory:',output,flush=True)
        async with httpx.AsyncClient(base_url=base,timeout=10,trust_env=False) as client:
            async def get(path,**params):
                response=await client.get(path,params=params)
                response.raise_for_status()
                return response.json()
            for snapshot in capture['snapshots']:
                step=snapshot['factory']['step']
                with lock: state['snapshot']=snapshot
                expected=next(a['dynamic_state']['seq'] for a in snapshot['assets'] if a['asset_id']=='CNC_01')
                for _ in range(200):
                    twin=main.registry.get('CNC_01')
                    rows=await store.history('CNC_01','telemetry',1,0,run_id,latest=True)
                    if twin and twin.sequence==expected and rows and rows[0]['sequence']==expected:break
                    await asyncio.sleep(.05)
                else: raise RuntimeError(f'Replay acceptance timed out at step {step}')
                record={'step':step,'sequence':expected,'evidence':rows[0]}
                for method in ('rolling_z_score','z_score_ewma'):
                    record[method]=await get('/api/twins/CNC_01/predictive-health',run_id=run_id,method=method)
                body=dict(asset_id='CNC_01',run_id=run_id,expected_sequence=expected,
                          maintenance_duration_seconds=120,remaining_batch_seconds=180)
                for path,key in [('/api/scenarios/maintenance/compare','comparison'),('/api/recommendations/maintenance','recommendation')]:
                    response=await client.post(path,json=body)
                    response.raise_for_status()
                    record[key]=response.json()
                assert main.registry.get('CNC_01').sequence==expected
                assert record['comparison']['live_state_mutated'] is False
                assert record['recommendation']['automatic_execution_allowed'] is False
                results.append(record)
                if step in (60,90):
                    print(f"Step {step}: {record['z_score_ewma']['status']} / {record['recommendation']['recommended_action']}",flush=True)
                    if args.interactive:
                        print('Inspect the dashboard now. Evidence ages after 60 receipt seconds; this is intentional. Enter to continue.',flush=True)
                        await asyncio.to_thread(input)
            await asyncio.sleep(.3)
            rows=await store.history('CNC_01','telemetry',1000,0,run_id)
            if len(rows)!=120 or len({r['sequence'] for r in rows})!=120:
                raise AssertionError('Replay lost or duplicated observations')
            assert (await client.get('/health')).status_code==200
            assert (await client.get('/dashboard/')).status_code==200
            assert (await client.get('/dashboard/build/console.js')).status_code==200
            if args.mode=='postgres':
                events=await get('/api/twins/CNC_01/history',run_id=run_id,limit=1000)
                assert any(e['kind']=='fault_started' for e in events)
                assert any(e['kind']=='fault_recovered' for e in events)
                health=await get('/api/twins/CNC_01/health-assessment',source='factory_simulator',
                    run_id=run_id,start=rows[0]['observed_at'].isoformat(),
                    end=datetime.now(timezone.utc).isoformat(),assessment_generated_at=datetime.now(timezone.utc).isoformat())
                kpi=await get('/api/twins/CNC_01/kpis',run_id=run_id,
                    start=rows[0]['source_timestamp'].isoformat(),end=rows[-1]['source_timestamp'].isoformat())
                assert health['contract_version']=='health.v1'
                assert kpi['contract_version']=='kpi.v1'
            else:
                assert (await client.get('/api/persistence-status')).json()['enabled'] is False
                assert (await client.get('/api/twins/CNC_01/history')).status_code==503
            report=dict(mode=args.mode,durable_persistence_verified=args.mode=='postgres',
                asset_id='CNC_01',observation_count=len(rows),timing=timing_report(results,capture['events'],capture['config']['step_seconds']),results=results)
            (output/'report.json').write_text(json.dumps(report,default=str,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in report.items() if k!='results'},default=str,indent=2),flush=True)
            if args.interactive:
                print('Final dashboard remains available; Enter stops only this demo.',flush=True)
                await asyncio.to_thread(input)
    finally:
        if server: server.should_exit=True
        if task: await task
        if source: source.shutdown(); source.server_close()
        await store.close()
        if admin:
            if schema_created:
                actual=await admin.fetchval('SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=$1',schema)
                if actual==owner and schema.startswith('tf_test_'):
                    await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
                else: print('Cleanup refused: schema ownership mismatch',flush=True)
            await admin.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator-repo',type=Path,required=True)
    parser.add_argument('--mode',choices=['memory','postgres'],required=True)
    parser.add_argument('--interactive',action='store_true')
    args=parser.parse_args()
    if args.mode=='postgres':validate_database(os.getenv('TWINFORGE_TEST_DATABASE_URL'))
    if not (ROOT/'app/static/dashboard/build/console.js').exists():
        parser.error('Build frontend first: npm.cmd --prefix frontend run build')
    repo=args.simulator_repo.resolve()
    if not (repo/'app/simulation.py').is_file():parser.error('Simulator checkout not found')
    output=Path(tempfile.mkdtemp(prefix='twinforge-demo-'))
    captured=subprocess.check_output([sys.executable,'-B','-c',GENERATOR,str(repo),str(output/'source-events.jsonl')],cwd=output,text=True,timeout=60)
    capture=json.loads(captured)
    (output/'source-capture.json').write_text(captured,encoding='utf-8')
    asyncio.run(run(args,capture,output))


if __name__=='__main__':main()
