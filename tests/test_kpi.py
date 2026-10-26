import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import app.main as main
from app.kpi.engine import calculate, oee_components
from app.kpi.models import Observation
from app.storage.postgres import PersistenceError, HistoryWindowTooLarge
from app.twin.mapper import simulator_asset_to_twin
from test_source_connectivity import make_asset

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def sample(second, **changes):
    row = Observation(source="factory_simulator", run_id="r1", asset_id="A",
        sequence=second, source_timestamp=START + timedelta(seconds=second),
        valid=True, fresh=True, state="RUNNING", good_count=second * 8,
        reject_count=second * 2, total_count=second * 10,
        interval_power_kw=3.6, interval_seconds=1)
    return replace(row, **changes)


def compute(rows, **kwargs):
    return calculate(rows, source="factory_simulator", run_id="r1", asset_id="A",
                     start=kwargs.pop("start", START),
                     end=kwargs.pop("end", START + timedelta(seconds=2)), **kwargs)


class KpiTests(unittest.TestCase):
    def test_known_production_energy_and_oee_example(self):
        result = compute([sample(i) for i in range(3)])
        self.assertEqual(result.coverage, 1)
        self.assertEqual(result.metrics['quality'].value, .8)
        self.assertEqual(result.metrics['reject_rate'].value, .2)
        self.assertEqual(result.metrics['throughput'].value, 28800)
        self.assertAlmostEqual(result.metrics['energy_consumption'].value, .002)
        self.assertAlmostEqual(result.metrics['energy_per_good_unit'].value, .002 / 16)
        oee = oee_components(100, 80, 1, 54, 60)
        self.assertEqual(oee['availability'].value, .8)
        self.assertEqual(oee['performance'].value, .75)
        self.assertEqual(oee['quality'].value, .9)
        self.assertAlmostEqual(oee['oee'].value, .54)
        self.assertAlmostEqual(oee['oee'].value, oee['availability'].value * oee['performance'].value * oee['quality'].value)

    def test_downtime_boundary_and_reason_estimate(self):
        result = compute([sample(0, state="FAULT", active_fault="jam"), sample(1), sample(2, state="FAULT")])
        self.assertEqual(result.metrics['downtime'].value, 1)
        self.assertEqual(result.metrics['downtime'].status, 'estimated')
        self.assertEqual(result.downtime_reasons_seconds, {'jam': 1})

    def test_setup_idle_and_running_boundaries(self):
        for state in ('IDLE', 'SETUP', 'BLOCKED', 'STARVED', 'OFFLINE'):
            with self.subTest(state=state):
                r = compute([sample(0, state=state), sample(1, state=state), sample(2)])
                self.assertEqual(r.metrics['downtime'].value, 2)

    def test_oee_missing_zero_and_invalid_inputs(self):
        for inputs in ((None, 80, 1, 54, 60), (100, None, 1, 54, 60),
                       (100, 80, None, 54, 60), (0, 0, 1, 0, 0),
                       (100, 80, 0, 54, 60), (100, 80, -1, 54, 60),
                       (100, 80, 2, 54, 60), (100, 110, 1, 54, 60),
                       (100, 80, 1, 61, 60), (float('nan'), 80, 1, 54, 60)):
            with self.subTest(inputs=inputs):
                self.assertIsNone(oee_components(*inputs)['oee'].value)

    def test_unsupported_metrics_are_never_invented(self):
        result = compute([sample(i) for i in range(3)])
        for key in ('availability', 'performance', 'oee', 'wip'):
            self.assertIsNone(result.metrics[key].value)
            self.assertEqual(result.metrics[key].status, 'unknown')
            self.assertTrue(result.metrics[key].reason)

    def test_zero_production_not_unknown_but_ratios_not_applicable(self):
        result = compute([sample(i, good_count=0, reject_count=0, total_count=0) for i in range(3)])
        self.assertEqual(result.metrics['throughput'].value, 0)
        for key in ('quality', 'reject_rate', 'energy_per_good_unit'):
            self.assertEqual(result.metrics[key].status, 'not_applicable')
            self.assertIsNone(result.metrics[key].value)

    def test_identical_duplicate_is_idempotent_conflict_is_unknown(self):
        rows = [sample(0), sample(1), sample(1), sample(2)]
        self.assertEqual(compute(rows).observation_count, 3)
        rows[2] = sample(1, state="IDLE")
        self.assertIsNone(compute(rows).metrics['throughput'].value)

    def test_gap_disconnect_and_stale_data_do_not_imply_zero(self):
        cases = ([sample(0), sample(2)],
                 [sample(0), sample(1, valid=False), sample(2)],
                 [sample(0), sample(1, fresh=False), sample(2)],
                 [sample(0), sample(1, source_timestamp=None), sample(2)])
        for rows in cases:
            with self.subTest(rows=rows):
                result = compute(rows)
                self.assertEqual(result.completeness, 'incomplete')
                for key in ('throughput', 'downtime', 'energy_consumption'):
                    self.assertIsNone(result.metrics[key].value)
                self.assertIsNone(result.downtime_reasons_seconds)

    def test_timestamp_gap_even_with_contiguous_sequence(self):
        result = compute([sample(0), sample(1, source_timestamp=START+timedelta(seconds=10))], end=START+timedelta(seconds=10))
        self.assertIn('Source timestamp gap', result.reasons)

    def test_partial_coverage_and_exact_boundaries(self):
        result = compute([sample(0), sample(1), sample(3)], end=START+timedelta(seconds=3))
        self.assertAlmostEqual(result.coverage, 1/3)
        self.assertIsNone(result.metrics['throughput'].value)
        result = compute([sample(0), sample(1), sample(2)], start=START+timedelta(milliseconds=500))
        self.assertIn('Exact start and end observations required', result.reasons)

    def test_out_of_order_times_and_sequences(self):
        for rows in ([sample(0), sample(2), sample(1)],
                     [sample(0), sample(1, source_timestamp=START), sample(2)]):
            self.assertEqual(compute(rows).completeness, 'incomplete')

    def test_context_cannot_cross_run(self):
        with self.assertRaises(ValueError):
            compute([sample(0), sample(1, run_id='r2'), sample(2)])

    def test_counter_reset_and_invalid_totals(self):
        for middle in (sample(1, good_count=999, total_count=1001), sample(1, total_count=999),
                       sample(1, good_count=None), sample(1, good_count=-1), sample(1, good_count=True)):
            result = compute([sample(0), middle, sample(2)])
            self.assertIsNone(result.metrics['throughput'].value)
            self.assertIsNone(result.metrics['quality'].value)

    def test_invalid_power_interval_and_unknown_state(self):
        for middle in (sample(1, interval_power_kw=None), sample(1, interval_power_kw=float('nan')),
                       sample(1, interval_power_kw=-1), sample(1, interval_seconds=2)):
            result = compute([sample(0), middle, sample(2)])
            self.assertIsNone(result.metrics['energy_consumption'].value)
            self.assertEqual(result.metrics['quality'].value, .8)
        self.assertIsNone(compute([sample(0, state='mystery'), sample(1), sample(2)]).metrics['downtime'].value)

    def test_timezone_equivalence_and_rejected_naive_window(self):
        local = START.astimezone(timezone(timedelta(hours=5, minutes=30)))
        self.assertEqual(compute([sample(i) for i in range(3)], start=local).coverage, 1)
        for start, end in ((START.replace(tzinfo=None), START), (START, START),
                           (START, START+timedelta(days=2))):
            with self.assertRaises(ValueError):
                compute([], start=start, end=end)

    def test_empty_history_has_unknown_metrics(self):
        result = compute([])
        self.assertEqual(result.coverage, 0)
        self.assertTrue(all(m.value is None for m in result.metrics.values()))

    def test_mapper_preserves_contract_and_does_not_consume_reference_metrics(self):
        asset = make_asset()
        asset['production'] = dict(good_quantity=7, rejected_quantity=2, total_quantity=9)
        asset['extensions'] = dict(last_interval_power_kw=3.6, energy_kwh_estimated=999)
        twin = simulator_asset_to_twin(asset, 1)
        self.assertEqual(twin.operations.good_count, 7)
        self.assertEqual(twin.operations.interval_power_kw, 3.6)
        self.assertNotIn('operations', twin.model_dump())
        asset['production']['good_quantity'] = '7'
        asset['extensions']['last_interval_power_kw'] = float('nan')
        twin = simulator_asset_to_twin(asset)
        self.assertIsNone(twin.operations.good_count)
        self.assertIsNone(twin.operations.interval_power_kw)


class KpiApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_validation_unknown_window_and_bounds(self):
        store = AsyncMock()
        store.kpi_observations.return_value = []
        params = dict(run_id='r1', start=START.isoformat(), end=(START+timedelta(seconds=2)).isoformat())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            with patch.object(main, 'store', store):
                r = await client.get('/api/twins/A/kpis', params=params)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()['contract_version'], 'kpi.v1')
                self.assertIsNone(r.json()['metrics']['oee']['value'])
                bad = dict(params, start='2024-01-01T00:00:00')
                self.assertEqual((await client.get('/api/twins/A/kpis', params=bad)).status_code, 422)
                store.kpi_observations.side_effect = HistoryWindowTooLarge('too many rows')
                self.assertEqual((await client.get('/api/twins/A/kpis', params=params)).status_code, 422)
                store.kpi_observations.side_effect = PersistenceError('secret')
                r = await client.get('/api/twins/A/kpis', params=params)
                self.assertEqual(r.status_code, 503)
                self.assertNotIn('secret', r.text)
            with patch.object(main, 'store', None):
                self.assertEqual((await client.get('/api/twins/A/kpis', params=params)).status_code, 503)
