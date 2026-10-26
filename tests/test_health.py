import unittest
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone

from app.health.models import Observation, Event
from app.health.engine import calculate
from app.health.service import asset_health
from app.storage.postgres import PersistenceError, HistoryWindowTooLarge


START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def observation(n=0, **changes):
    data = dict(id=n+1, asset_id='A', source='factory_simulator', run_id='r',
                sequence=n, observed_at=START+timedelta(seconds=n),
                source_timestamp=START+timedelta(seconds=n), state='RUNNING',
                active_fault=None, valid=True, fresh=True, telemetry_values={'temperature_c': 0},
                quality_source='factory_simulator')
    data.update(changes)
    return Observation(**data)


def event(n=0, kind='fault_started', **changes):
    data = dict(id=n+1, asset_id='A', source='factory_simulator', run_id='r',
                sequence=n, observed_at=START+timedelta(seconds=n), kind=kind,
                value='jam' if kind != 'fault_recovered' else None,
                previous_value='jam' if kind == 'fault_recovered' else None)
    data.update(changes)
    return Event(**data)


def assess(rows=None, events=(), **changes):
    args = dict(asset_id='A', source='factory_simulator', run_id='r',
                window_start=START, window_end=START+timedelta(seconds=3),
                assessment_generated_at=START+timedelta(days=1), evidence_complete=True)
    args.update(changes)
    return calculate([observation(0), observation(1)] if rows is None else rows, events, **args)


class HealthTests(unittest.TestCase):
    def test_baseline(self):
        result = assess()
        self.assertEqual(result.availability, 'available')
        self.assertEqual(result.contract_version, 'health.v1')
        self.assertEqual(result.method, 'observed_condition_rules')
        self.assertTrue(all(i.status == 'not_observed' for i in result.indicators.values()))
        self.assertEqual(result.indicators['fault_start_observations'].value, 0)
        self.assertEqual(result.data_quality.usable_observation_count, 2)

    def test_latest_fault_exact_reference(self):
        r = assess([observation(0), observation(1, active_fault='jam')])
        i = r.indicators['fault_reported_at_last_observation']
        self.assertEqual((i.status, i.value), ('observed', 'jam'))
        self.assertEqual(i.evidence[0].model_dump(), dict(kind='observation', id=2, sequence=1,
                         observed_at=START+timedelta(seconds=1), source_timestamp=START+timedelta(seconds=1)))
        self.assertEqual(i.reason, 'Explicit recorded evidence; not a physical-health diagnosis')

    def test_fault_state_anywhere_not_just_latest(self):
        r = assess([observation(0, state='FAULT'), observation(1)])
        self.assertTrue(r.indicators['fault_state_observed'].value)
        self.assertEqual(r.indicators['fault_reported_at_last_observation'].status, 'not_observed')

    def test_offline_is_recorded_machine_state(self):
        r = assess([observation(0, state='OFFLINE', valid=False, fresh=False)])
        self.assertTrue(r.indicators['offline_state_observed'].value)
        self.assertEqual(r.availability, 'partial')

    def test_distinct_events(self):
        r = assess(events=[event(), event(), event(1, 'fault_recovered')])
        self.assertEqual(r.indicators['fault_start_observations'].value, 1)
        self.assertEqual(r.indicators['fault_clear_observations'].value, 1)
        ref = r.indicators['fault_clear_observations'].evidence[0]
        self.assertEqual((ref.kind, ref.id, ref.sequence, ref.source_timestamp), ('event', 2, 1, None))

    def test_initial_fault_is_not_onset(self):
        r = assess(events=[event(kind='fault_observed')])
        self.assertEqual(r.indicators['fault_start_observations'].value, 0)

    def test_missing_invalid_stale_preserve_fault(self):
        r = assess([observation(active_fault='jam', valid=False, fresh=False, telemetry_values=None)])
        self.assertEqual(r.availability, 'partial')
        self.assertEqual(r.indicators['fault_reported_at_last_observation'].value, 'jam')
        self.assertEqual(r.indicators['fault_start_observations'].status, 'unavailable')
        self.assertEqual(r.data_quality.invalid_observations, 1)
        self.assertEqual(r.data_quality.stale_observations, 1)
        self.assertEqual(r.data_quality.missing_telemetry, 1)

    def test_missing_source_timestamp(self):
        r = assess([observation(source_timestamp=None)])
        self.assertEqual(r.data_quality.missing_source_timestamps, 1)
        self.assertTrue(r.indicators['evidence_discontinuity'].value)

    def test_sequence_gap(self):
        r = assess([observation(), observation(2)])
        self.assertEqual(r.data_quality.sequence_gaps, 1)
        self.assertEqual([x.id for x in r.indicators['evidence_discontinuity'].evidence], [1, 3])

    def test_sequence_reversal(self):
        r = assess([observation(sequence=2), observation(1)])
        self.assertEqual(r.data_quality.sequence_reversals, 1)

    def test_nonincreasing_time(self):
        for timestamp in (START, START-timedelta(seconds=1)):
            with self.subTest(timestamp=timestamp):
                r = assess([observation(), observation(1, source_timestamp=timestamp)])
                self.assertEqual(r.data_quality.nonincreasing_source_timestamps, 1)

    def test_context_isolation(self):
        for key in ('run_id', 'source', 'asset_id'):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, 'Mixed'):
                    assess([observation(**{key: 'other'})])
                with self.assertRaisesRegex(ValueError, 'Mixed'):
                    assess(events=[event(**{key: 'other'})])

    def test_empty(self):
        r = assess([])
        self.assertEqual(r.availability, 'unavailable')
        self.assertTrue(all(i.status == 'unavailable' and i.value is None for i in r.indicators.values()))

    def test_duplicate_observations_and_conflicts(self):
        self.assertEqual(assess([observation(), observation(), observation(1)]), assess())
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            assess([observation(), observation(state='FAULT')])
        with self.assertRaisesRegex(ValueError, 'one sequence'):
            assess([observation(), observation(id=8)])
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            assess(events=[event(), event(value='different')])

    def test_half_open_boundaries(self):
        r = assess([observation(0), observation(1), observation(2)],
                   [event(0), event(2)], window_end=START+timedelta(seconds=2))
        self.assertEqual(r.data_quality.observation_count, 2)
        self.assertEqual(r.indicators['fault_start_observations'].value, 1)

    def test_invalid_bounds_and_assessment_time(self):
        for changes in (dict(window_end=START), dict(window_end=START-timedelta(seconds=1)),
                        dict(window_start=START.replace(tzinfo=None)),
                        dict(window_end=START.replace(tzinfo=None)),
                        dict(assessment_generated_at=START.replace(tzinfo=None))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                assess(**changes)
        with self.assertRaises(ValueError):
            observation(observed_at=START.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            observation(source_timestamp=START.replace(tzinfo=None))

    def test_deterministic_and_order_independent(self):
        self.assertEqual(assess().model_dump_json(), assess().model_dump_json())
        self.assertEqual(assess([observation(1), observation(0)]), assess())

    def test_source_scores_ignored(self):
        self.assertEqual(assess([observation(0, health_score=10, anomaly_score=90), observation(1)]),
                         assess([observation(0, health_score=100, anomaly_score=0), observation(1)]))

    def test_incomplete_retrieval_and_event_only(self):
        r = assess(evidence_complete=False)
        self.assertEqual(r.availability, 'unavailable')
        self.assertTrue(all(i.status == 'unavailable' for i in r.indicators.values()))
        r = assess([], [event()], evidence_complete=False)
        self.assertEqual(r.availability, 'partial')
        self.assertEqual(r.indicators['fault_start_observations'].value, 1)

    def test_single_observation_and_timezone_normalization(self):
        r = assess([observation()])
        self.assertEqual(r.availability, 'partial')
        self.assertEqual(r.indicators['evidence_discontinuity'].status, 'unavailable')
        offset = timezone(timedelta(hours=5, minutes=30))
        self.assertEqual(assess(window_start=START.astimezone(offset)), assess())

    def test_latest_timestamps_do_not_mix_clocks(self):
        old = START-timedelta(days=5)
        r = assess([observation(source_timestamp=old), observation(1, source_timestamp=None)])
        self.assertEqual(r.latest_source_timestamp, old)
        self.assertEqual(r.latest_observed_at, START+timedelta(seconds=1))


class HealthServiceTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, store, **changes):
        args = dict(source='factory_simulator', run_id='r', asset_id='A',
                    window_start=START, window_end=START+timedelta(seconds=3),
                    assessment_generated_at=START+timedelta(days=1))
        args.update(changes)
        return await asset_health(store, **args)

    def store(self, rows=(), events=(), **changes):
        evidence = dict(observations=[r.model_dump() for r in rows],
                        events=[e.model_dump() for e in events], before=None, after=None,
                        asset_exists=True, run_exists=True)
        evidence.update(changes)
        store = AsyncMock()
        store.health_evidence.return_value = evidence
        return store

    async def test_mapping_duplicates_and_repeatability(self):
        store = self.store([observation(), observation(), observation(1)], [event(), event()])
        result = await self.call(store)
        self.assertEqual(result, await self.call(store))
        self.assertEqual(result.data_quality.observation_count, 2)
        self.assertEqual(result.indicators['fault_start_observations'].value, 1)

    async def test_validation_before_io(self):
        store = self.store()
        for changes in (dict(asset_id=' '), dict(source=None), dict(run_id=''),
                        dict(window_end=START), dict(window_start=START.replace(tzinfo=None)),
                        dict(window_end=START+timedelta(days=2)),
                        dict(assessment_generated_at=START.replace(tzinfo=None))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                await self.call(store, **changes)
        store.health_evidence.assert_not_awaited()

    async def test_storage_and_capacity_failures_propagate(self):
        with self.assertRaises(PersistenceError):
            await self.call(None)
        for error in (PersistenceError('Database operation failed or timed out'),
                      HistoryWindowTooLarge('Too many rows')):
            store = self.store()
            store.health_evidence.side_effect = error
            with self.assertRaises(type(error)) as caught:
                await self.call(store)
            self.assertIs(caught.exception, error)

    async def test_unknown_empty_and_insufficient_are_distinct(self):
        unknown = await self.call(self.store(asset_exists=False, run_exists=False))
        self.assertEqual(unknown.availability, 'unavailable')
        self.assertIn('Unknown persisted asset', unknown.reasons)
        self.assertIn('Unknown persisted source/run', unknown.reasons)
        empty = await self.call(self.store(before=observation(observed_at=START-timedelta(seconds=1)).model_dump()))
        self.assertIn('Empty receipt window', empty.reasons)
        single = await self.call(self.store([observation()]))
        self.assertEqual(single.availability, 'partial')


if __name__ == '__main__':
    unittest.main()
