import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import app.main as main
from app.predictive.engine import predict_health, normalize_risk
from app.storage.models import ObservationRecord
from app.storage.postgres import PostgresStore, PersistenceError


def records(values):
    return [ObservationRecord(id=i+1, source='factory_simulator', run_id='r', asset_id='A',
        sequence=i, observed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        source_timestamp=None, raw_source_timestamp=None, telemetry_values={'temperature': v},
        valid=True, fresh=True, quality_source='factory_simulator', reason=None)
        for i, v in enumerate(values)]


def assess(rows):
    return predict_health('A', rows, source='factory_simulator', run_id='r')


class PredictiveEngineTests(unittest.TestCase):
    def test_baseline_excludes_current_and_is_bounded(self):
        result = assess(records([999]*40 + [0, 2]*15 + [5]))
        signal = result.top_signals[0]
        self.assertEqual((signal.baseline_mean, signal.baseline_std, signal.z_score), (1, 1, 4))
        self.assertEqual((result.status, result.risk_score, result.observations_used), ('CRITICAL', 1, 31))

    def test_thresholds_and_negative_deviations(self):
        for current, status in [(1, 'NORMAL'), (3.5, 'WARNING'), (5, 'CRITICAL'), (-3, 'CRITICAL')]:
            with self.subTest(current=current):
                self.assertEqual(assess(records([0, 2]*15 + [current])).status, status)
        self.assertAlmostEqual(normalize_risk(2.35), .45)
        self.assertEqual(normalize_risk(1), 0)

    def test_minimum_and_missing(self):
        for values in ([], [1]*9, [None]*31, [True]*31, ['2']*31, [float('nan')]*31,
                       [float('inf')]*31):
            result = assess(records(values))
            self.assertEqual(result.status, 'INSUFFICIENT_DATA')
            self.assertIsNone(result.risk_score)
        self.assertEqual(assess(records([1]*10)).status, 'NORMAL')

    def test_zero_variance(self):
        result = assess(records([1]*30 + [2]))
        self.assertEqual(result.status, 'INSUFFICIENT_DATA')
        self.assertIsNone(result.top_signals[0].z_score)
        self.assertIsNone(result.top_signals[0].risk)
        self.assertEqual(result.top_signals[0].baseline_std, 0)
        result.model_dump_json()  # No Infinity/NaN output.

    def test_quality_latest_and_no_backfill(self):
        for field in ('valid', 'fresh'):
            rows = records([0, 2]*15 + [5])
            setattr(rows[-1], field, False)
            self.assertEqual(assess(rows).status, 'INSUFFICIENT_DATA')
            rows[-1] = records([5])[0].model_copy(update={'id':31, 'sequence':30})
            for row in rows[:-9]:
                setattr(row, field, False)
            self.assertEqual(assess(rows).status, 'INSUFFICIENT_DATA')
        rows = records([1]*30 + [None])
        self.assertEqual(assess(rows).status, 'INSUFFICIENT_DATA')

    def test_scores_are_not_inputs_and_context_isolated(self):
        rows = records([1]*31)
        for row in rows:
            row.telemetry_values = {'health_score':100, 'anomaly_score':0}
        self.assertEqual(assess(rows).status, 'INSUFFICIENT_DATA')
        for field in ('asset_id', 'source', 'run_id'):
            rows = records([1]*31)
            setattr(rows[0], field, 'other')
            with self.assertRaises(ValueError):
                assess(rows)

    def test_sort_dedup_and_signal_ranking(self):
        rows = records([0, 2]*15 + [5])
        for row in rows:
            row.telemetry_values['current_a'] = 1
        result = assess(list(reversed(rows)) + [rows[0]])
        self.assertEqual(result.top_signals[0].signal, 'temperature')
        self.assertEqual(result.observations_used, 31)
        rows[-1].telemetry_values['current_a'] = 2
        self.assertEqual(assess(rows).status, 'CRITICAL')
        self.assertIsNotNone(assess(rows).reason)


class PredictiveApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = AsyncMock()
        self.store.history.return_value = [r.model_dump() for r in records([0, 2]*15 + [5])]
        self.patcher = patch.object(main, 'store', self.store)
        self.patcher.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test')
        self.path = '/api/twins/A/predictive-health'

    async def asyncTearDown(self):
        await self.client.aclose()
        self.patcher.stop()

    async def test_success_and_bounded_storage_reuse(self):
        response = await self.client.get(self.path, params={'run_id':'r'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'CRITICAL')
        self.store.history.assert_awaited_once_with('A', 'telemetry', 31, 0, 'r', latest=True)
        self.assertEqual([c[0] for c in self.store.mock_calls], ['history'])

    async def test_empty_and_validation(self):
        self.store.history.return_value = []
        response = await self.client.get(self.path, params={'run_id':'r'})
        self.assertEqual(response.json()['status'], 'INSUFFICIENT_DATA')
        for params in ({}, {'run_id':''}, {'run_id':' '}, {'run_id':'x'*201}):
            self.assertEqual((await self.client.get(self.path, params=params)).status_code, 422)

    async def test_safe_errors(self):
        with patch.object(main, 'store', None):
            self.assertEqual((await self.client.get(self.path, params={'run_id':'r'})).status_code, 503)
        for error, status in [(PersistenceError('secret'),503), (ValueError('secret'),500)]:
            self.store.history.side_effect = error
            response = await self.client.get(self.path, params={'run_id':'r'})
            self.assertEqual(response.status_code, status)
            self.assertNotIn('secret', response.text)

    async def test_storage_query_order(self):
        connection = AsyncMock()
        connection.fetch.return_value = []
        @asynccontextmanager
        async def fake_connection():
            yield connection
        store = PostgresStore('unused')
        with patch.object(store, 'connection', fake_connection):
            await store.history('A', 'telemetry', 31, 0, 'r', latest=True)
            self.assertIn('ORDER BY id DESC LIMIT $4', connection.fetch.call_args.args[0])
            self.assertEqual(connection.fetch.call_args.args[1:], ('A',0,'r',31))
            await store.history('A', 'telemetry')
            self.assertIn('ORDER BY id ASC LIMIT $4', connection.fetch.call_args.args[0])

class PredictiveEwmaTests(unittest.TestCase):
    def combined(self, values):
        from app.predictive.combined import predict_combined
        return predict_combined('A', records(values), source='factory_simulator', run_id='r')

    def test_stable_and_noisy_stable(self):
        for values in ([41]*60, [40,42]*30, [40,42,41,42,40,41]*10):
            result = self.combined(values)
            self.assertEqual(result.status, 'NORMAL')
            self.assertEqual(result.contract_version, 'predictive.v2')
            self.assertEqual(result.method, 'z_score_ewma')
            self.assertEqual(result.risk_score, max(result.z_score_risk, result.ewma_risk))

    def test_spike_and_gradual_drift(self):
        spike = self.combined([40,42]*29 + [40,50])
        self.assertEqual(spike.status, 'CRITICAL')
        self.assertEqual(spike.z_score_risk, 1)
        result = self.combined([40,42]*15 + [41 + .1*i for i in range(1,31)])
        self.assertEqual(result.status, 'CRITICAL')
        self.assertLess(result.z_score_risk, .45)
        self.assertEqual(result.ewma_risk, 1)
        self.assertEqual(result.dominant_method, 'ewma')
        self.assertEqual(result.dominant_signal, 'temperature')
        self.assertIn('ewma', result.explanation)

    def test_insufficient_and_missing_values(self):
        for values in ([], [41]*39, [40,42]*15 + [None]*30,
                       [40,42]*15 + [41]*29 + [None],
                       [40,42]*15 + [41]*5 + [None] + [41]*24):
            result = self.combined(values)
            self.assertEqual(result.status, 'INSUFFICIENT_DATA')
            self.assertIsNone(result.risk_score)
        self.assertEqual(self.combined([40,42]*15 + [41]*10).status, 'NORMAL')

    def test_exact_formula(self):
        from app.predictive.ewma import assess_ewma
        from math import sqrt
        trend = assess_ewma([40,42]*15, [42,43])
        expected = .2*43 + .8*(.2*42 + .8*41)
        self.assertAlmostEqual(trend.value, expected)
        self.assertAlmostEqual(trend.standardized_deviation,
            (expected-41)/sqrt(.2/1.8*(1-.8**4)))

    def test_constant_change_is_unscorable_and_downward_drift(self):
        result = self.combined([41]*30 + [42]*30)
        self.assertEqual(result.status, 'INSUFFICIENT_DATA')
        self.assertIsNone(result.ewma_risk)
        self.assertEqual(self.combined([40,42]*15 + [41-.1*i for i in range(1,31)]).status,
                         'CRITICAL')

    def test_partial_signals_quality_and_determinism(self):
        from app.predictive.combined import predict_combined
        rows = records([40,42]*15 + [41+.1*i for i in range(1,31)])
        for row in rows:
            row.telemetry_values['power_kw'] = None
            row.telemetry_values['health_score'] = 100
        args = dict(source='factory_simulator', run_id='r')
        result = predict_combined('A', rows, **args)
        self.assertEqual(result, predict_combined('A', list(reversed(rows)), **args))
        self.assertEqual([s.signal for s in result.top_signals], ['temperature'])
        rows[40].fresh = False
        self.assertEqual(predict_combined('A', rows, **args).status, 'INSUFFICIENT_DATA')


class PredictiveV2ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_opt_in_and_default_compatibility(self):
        store = AsyncMock()
        store.history.return_value = [r.model_dump() for r in records(
            [40,42]*15 + [41+.1*i for i in range(1,31)])]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            with patch.object(main, 'store', store):
                path = '/api/twins/A/predictive-health'
                response = await client.get(path, params={'run_id':'r','method':'z_score_ewma'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['dominant_method'], 'ewma')
                self.assertEqual(response.json()['contract_version'], 'predictive.v2')
                store.history.assert_awaited_with('A', 'telemetry', 60, 0, 'r', latest=True)
                response = await client.get(path, params={'run_id':'r'})
                self.assertEqual(response.json()['contract_version'], 'predictive.v1')
                self.assertEqual(response.json()['method'], 'rolling_z_score')
                store.history.assert_awaited_with('A', 'telemetry', 31, 0, 'r', latest=True)
                response = await client.get(path, params={'run_id':'r','method':'unknown'})
                self.assertEqual(response.status_code, 422)
