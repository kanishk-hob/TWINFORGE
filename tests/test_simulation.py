"""Conditional timing math and API isolation; no live simulator or database needed."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import httpx
from pydantic import ValidationError

import app.main as main
from app.simulation.models import MaintenanceComparisonRequest
from app.simulation.service import compare_maintenance
from app.simulation.snapshot import ContextConflict
from app.twin.mapper import simulator_asset_to_twin
from app.twin.registry import TwinRegistry
from test_source_connectivity import make_asset


def registry():
    result = TwinRegistry()
    result.reset_for_new_run('r')
    result.update(simulator_asset_to_twin(make_asset()))
    result.mark_sync_success()
    return result


def request(**changes):
    data = dict(asset_id='CNC_01', run_id='r', maintenance_duration_seconds=10,
                remaining_batch_seconds=30, expected_sequence=1)
    data.update(changes)
    return MaintenanceComparisonRequest(**data)


class MaintenanceTests(unittest.TestCase):
    def test_exact_timing_and_deltas(self):
        result = compare_maintenance(registry(), request())
        a, b = result.scenario_a.metrics, result.scenario_b.metrics
        expected = {
            'projected_maintenance_downtime_seconds': (10, 10, 0),
            'maintenance_start_offset_seconds': (0, 30, 30),
            'maintenance_end_offset_seconds': (10, 40, 30),
            'current_batch_completion_offset_seconds': (40, 30, -10),
            'current_batch_delay_seconds': (10, 0, -10),
            'scenario_duration_seconds': (40, 40, 0),
        }
        for key, values in expected.items():
            self.assertEqual((a[key].value, b[key].value, result.deltas_b_minus_a[key].value), values)
            self.assertEqual(a[key].status, 'estimated')
        self.assertIsNone(result.preferred_scenario)
        self.assertFalse(result.live_state_mutated)
        self.assertEqual(result.scenario_a.affected_jobs, ['JOB_001'])
        self.assertFalse(result.scenario_a.affected_jobs_complete)
        for key in ('energy_impact', 'throughput_impact', 'good_unit_impact'):
            self.assertIsNone(a[key].value)
            self.assertIsNone(result.deltas_b_minus_a[key].value)

    def test_missing_remaining_is_partial(self):
        result = compare_maintenance(registry(), request(remaining_batch_seconds=None))
        self.assertEqual(result.scenario_b.status, 'partial')
        self.assertIsNone(result.scenario_b.metrics['maintenance_start_offset_seconds'].value)
        self.assertIsNone(result.scenario_a.metrics['current_batch_completion_offset_seconds'].value)
        self.assertEqual(result.scenario_a.metrics['projected_maintenance_downtime_seconds'].value, 10)
        self.assertEqual(result.scenario_a.metrics['maintenance_end_offset_seconds'].value, 10)
        self.assertTrue(result.data_quality)

    def test_already_completed_batch_and_fractional_durations(self):
        result = compare_maintenance(registry(), request(remaining_batch_seconds=0, maintenance_duration_seconds=.5))
        for scenario in (result.scenario_a, result.scenario_b):
            self.assertEqual(scenario.metrics['current_batch_completion_offset_seconds'].value, 0)
            self.assertEqual(scenario.metrics['current_batch_delay_seconds'].value, 0)
            self.assertEqual(scenario.metrics['scenario_duration_seconds'].value, .5)

    def test_quality_and_state_gates(self):
        for change in ('disconnected', 'old_sync', 'invalid', 'stale', 'FAULT', 'IDLE', 'fault', 'job', 'blank_job'):
            r = registry()
            twin = r.get('CNC_01')
            if change == 'disconnected':
                r.mark_sync_failure('unavailable')
            elif change == 'old_sync':
                r.last_sync_at = datetime.now(timezone.utc) - timedelta(days=1)
            elif change == 'invalid':
                twin.quality.valid = False
            elif change == 'stale':
                twin.quality.fresh = False
            elif change == 'fault':
                twin.active_fault = 'jam'
            elif change in ('job', 'blank_job'):
                twin.current_job_id = None if change == 'job' else ' '
            else:
                twin.state = change
            with self.subTest(change=change):
                result = compare_maintenance(r, request())
                self.assertEqual(result.scenario_a.status, 'partial')
                self.assertIsNone(result.scenario_a.metrics['current_batch_delay_seconds'].value)
                self.assertTrue(result.data_quality)

    def test_context_guards_and_snapshot_detachment(self):
        r = registry()
        for req in (request(run_id='old'), request(expected_sequence=2)):
            with self.assertRaises(ContextConflict):
                compare_maintenance(r, req)
        with self.assertRaises(KeyError):
            compare_maintenance(r, request(asset_id='missing'))
        before = copy.deepcopy(r.__dict__)
        result = compare_maintenance(r, request())
        again = compare_maintenance(r, request())
        self.assertEqual(result.scenario_a, again.scenario_a)
        self.assertEqual(r.__dict__, before)
        r.get('CNC_01').current_job_id = 'new'
        self.assertEqual(result.baseline.current_job_id, 'JOB_001')
        with self.assertRaises(ValidationError):
            result.baseline.sequence = 99

    def test_input_validation_including_nonfinite(self):
        for value in (float('nan'), float('inf'), -float('inf'), True, '10'):
            for field in ('maintenance_duration_seconds', 'remaining_batch_seconds'):
                with self.subTest(value=value, field=field), self.assertRaises(ValidationError):
                    request(**{field: value})


class MaintenanceApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_and_no_external_side_effects(self):
        r = registry()
        before = copy.deepcopy(r.__dict__)
        store = AsyncMock()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            with patch.object(main, 'registry', r), patch.object(main, 'store', store), \
                 patch.object(main.sync_service, 'sync_once', AsyncMock()) as sync, \
                 patch('httpx.AsyncClient.request', side_effect=AssertionError('Unexpected outbound HTTP')) as outbound:
                response = await client.send(client.build_request(
                    'POST', '/api/scenarios/maintenance/compare', json=request().model_dump()))
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body['contract_version'], 'simulation.v1')
                self.assertFalse(body['live_state_mutated'])
                self.assertEqual(body['scenario_a']['metrics']['current_batch_delay_seconds']['value'], 10)
                outbound.assert_not_called()
                sync.assert_not_awaited()
                self.assertEqual(store.mock_calls, [])
        self.assertEqual(before, r.__dict__)

    async def test_validation_conflicts_and_minimal_request(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            with patch.object(main, 'registry', registry()):
                path = '/api/scenarios/maintenance/compare'
                for change in ({'maintenance_duration_seconds': 0}, {'maintenance_duration_seconds': -1},
                               {'maintenance_duration_seconds': True}, {'remaining_batch_seconds': -1},
                               {'remaining_batch_seconds': '30'}, {'run_id': ' '}, {'asset_id': ' '},
                               {'maintenance_duration_seconds': 604801}, {'unexpected': 1}):
                    body = request().model_dump()
                    body.update(change)
                    self.assertEqual((await client.post(path, json=body)).status_code, 422, change)
                for change, code in [({'run_id': 'old'}, 409), ({'expected_sequence': 2}, 409), ({'asset_id': 'missing'}, 404)]:
                    body = request().model_dump()
                    body.update(change)
                    self.assertEqual((await client.post(path, json=body)).status_code, code)
                minimal = dict(asset_id='CNC_01', run_id='r', maintenance_duration_seconds=10)
                response = await client.post(path, json=minimal)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['scenario_b']['status'], 'partial')
                self.assertEqual((await client.get(path)).status_code, 405)

    async def test_no_database_required_and_openapi(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            with patch.object(main, 'registry', registry()), patch.object(main, 'store', None):
                self.assertEqual((await client.post('/api/scenarios/maintenance/compare',
                                                  json=request().model_dump())).status_code, 200)
            schema = (await client.get('/openapi.json')).json()
            route = schema['paths']['/api/scenarios/maintenance/compare']['post']
            self.assertTrue(route['requestBody']['required'])
            self.assertTrue(route['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/MaintenanceComparison'))
