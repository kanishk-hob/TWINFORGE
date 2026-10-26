"""Read-only API tests: actual service/engine, controlled storage evidence."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import app.main as main
from app.storage.postgres import PersistenceError, HistoryWindowTooLarge


START = datetime(2024, 1, 1, tzinfo=timezone.utc)
PATH = '/api/twins/A/health-assessment'


def evidence():
    return dict(observations=[dict(id=n+1, asset_id='A', source='factory_simulator',
        run_id='r', sequence=n, observed_at=START+timedelta(seconds=n),
        source_timestamp=None, state='FAULT' if n==1 else 'RUNNING',
        active_fault='jam' if n==1 else None, valid=True, fresh=True,
        telemetry_values={'temperature_c':42}, quality_source='factory_simulator', reason=None)
        for n in range(3)], events=[], before=None, after=None, asset_exists=True, run_exists=True)


class HealthApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.params = dict(source='factory_simulator', run_id='r', start=START.isoformat(),
                           end=(START+timedelta(seconds=2)).isoformat(),
                           assessment_generated_at=(START+timedelta(days=1)).isoformat())
        self.store = AsyncMock()
        self.store.health_evidence.return_value = evidence()
        self.patcher = patch.object(main, 'store', self.store)
        self.patcher.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.patcher.stop()

    async def test_success_receipt_boundary_and_determinism(self):
        response = await self.client.get(PATH, params=self.params)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['contract_version'], 'health.v1')
        self.assertEqual(body['method'], 'observed_condition_rules')
        self.assertEqual(body['time_basis'], 'receipt')
        self.assertEqual(body['data_quality']['observation_count'], 2)
        self.assertEqual(body['indicators']['fault_reported_at_last_observation']['value'], 'jam')
        self.assertEqual(body['assessment_generated_at'], '2024-01-02T00:00:00Z')
        self.assertEqual(body, (await self.client.get(PATH, params=self.params)).json())

    async def test_required_parameters(self):
        for key in self.params:
            params = dict(self.params)
            del params[key]
            with self.subTest(key=key):
                self.assertEqual((await self.client.get(PATH, params=params)).status_code, 422)
        self.store.health_evidence.assert_not_awaited()

    async def test_invalid_inputs(self):
        changes = [dict(start='invalid'), dict(end=self.params['start']),
                   dict(end='2023-01-01T00:00:00Z'), dict(end='2024-01-03T00:00:00Z'),
                   dict(source=' '), dict(run_id=''), dict(run_id='x'*201)]
        changes += [{key:'2024-01-01T00:00:00'} for key in ('start','end','assessment_generated_at')]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual((await self.client.get(PATH, params=dict(self.params, **change))).status_code, 422)
        self.store.health_evidence.assert_not_awaited()

    async def test_unknown_and_empty_are_unavailable(self):
        for known in (True, False):
            self.store.health_evidence.return_value = dict(observations=[],events=[],before=None,after=None,
                                                           asset_exists=known,run_exists=known)
            response = await self.client.get(PATH, params=self.params)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['availability'], 'unavailable')
            self.assertTrue(all(i['value'] is None for i in response.json()['indicators'].values()))
            if not known:
                self.assertIn('Unknown persisted asset', response.json()['reasons'])

    async def test_errors_are_sanitized(self):
        for error, status in [(HistoryWindowTooLarge('secret SQL'),422),
                              (PersistenceError('secret password'),503),
                              (RuntimeError('secret host'),500),
                              (ValueError('secret malformed DB row'),500)]:
            self.store.health_evidence.side_effect = error
            with self.subTest(error=type(error).__name__):
                response = await self.client.get(PATH, params=self.params)
                self.assertEqual(response.status_code, status)
                self.assertNotIn('secret', response.text)

    async def test_disabled_persistence(self):
        with patch.object(main, 'store', None):
            response = await self.client.get(PATH, params=self.params)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail'], 'Persistence is not configured')

    async def test_context_forwarding_and_mixed_evidence_rejected(self):
        for field in ('source','run_id','asset_id'):
            data = evidence()
            data['observations'][0][field] = 'wrong'
            self.store.health_evidence.return_value = data
            response = await self.client.get(PATH, params=self.params)
            self.assertEqual(response.status_code, 500)
        args = self.store.health_evidence.call_args.args
        self.assertEqual(args[:3], ('factory_simulator','r','A'))
        self.assertEqual(args[3:], (START, START+timedelta(seconds=2)))

    async def test_get_does_not_mutate_or_sync(self):
        before = copy.deepcopy(self.store.health_evidence.return_value)
        with patch.object(main.sync_service, 'sync_once', AsyncMock()) as sync:
            self.assertEqual((await self.client.get(PATH, params=self.params)).status_code, 200)
            sync.assert_not_awaited()
        self.assertEqual(before, self.store.health_evidence.return_value)
        self.assertEqual([c[0] for c in self.store.mock_calls], ['health_evidence'])
        self.assertEqual((await self.client.post(PATH, params=self.params)).status_code, 405)

    async def test_openapi_response_and_required_queries(self):
        schema = (await self.client.get('/openapi.json')).json()
        route = schema['paths']['/api/twins/{asset_id}/health-assessment']
        self.assertEqual(set(route), {'get'})
        self.assertEqual({p['name'] for p in route['get']['parameters'] if p['required']},
                         {'asset_id','source','run_id','start','end','assessment_generated_at'})
        self.assertTrue(route['get']['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/Assessment'))
