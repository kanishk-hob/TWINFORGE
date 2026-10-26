"""Advisory decisions with actual predictive/simulation engines and controlled storage."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx

import app.main as main
from app.predictive.combined import predict_combined
from app.recommendation.config import MAX_WARNING_DEFERRAL_SECONDS
from app.recommendation.models import MaintenanceRecommendationRequest, EvidenceReference
from app.recommendation.policy import evaluate
from app.recommendation.service import recommend_maintenance
from app.simulation.models import MaintenanceComparisonRequest
from app.simulation.service import compare_maintenance
from app.storage.models import ObservationRecord
from app.storage.postgres import PersistenceError
from app.twin.mapper import simulator_asset_to_twin
from app.twin.registry import TwinRegistry
from test_source_connectivity import make_asset

PATH = '/api/recommendations/maintenance'


def request(**changes):
    values = dict(asset_id='CNC_01', run_id='r', maintenance_duration_seconds=10,
                  remaining_batch_seconds=30, expected_sequence=60)
    values.update(changes)
    return MaintenanceRecommendationRequest(**values)


def fixture(status='NORMAL'):
    now = datetime.now(timezone.utc)
    values = [40, 42]*29 + [40, {'NORMAL': 42, 'WARNING': 43.5, 'CRITICAL': 45}[status]]
    rows = [ObservationRecord(
        id=i+1, sequence=i+1, source='factory_simulator', run_id='r', asset_id='CNC_01',
        observed_at=now-timedelta(seconds=59-i), source_timestamp=now-timedelta(seconds=59-i),
        raw_source_timestamp=(now-timedelta(seconds=59-i)).isoformat(),
        telemetry_values={'temperature': value}, valid=True, fresh=True,
        quality_source='factory_simulator', reason=None,
    ) for i, value in enumerate(values)]
    r = TwinRegistry()
    r.reset_for_new_run('r')
    raw = make_asset(sequence=60)
    raw['dynamic_state'].update(values=rows[-1].telemetry_values.copy(),
                                last_telemetry_timestamp=rows[-1].raw_source_timestamp)
    r.update(simulator_asset_to_twin(raw))
    r.mark_sync_success(now)
    return r, rows


def evidence(status='NORMAL', **request_changes):
    r, rows = fixture(status)
    req = request(**request_changes)
    comparison = compare_maintenance(r, MaintenanceComparisonRequest(**req.model_dump(exclude={'predictive_method'})))
    prediction = predict_combined('CNC_01', rows, source='factory_simulator', run_id='r')
    reference = EvidenceReference(latest_observation_id=60, latest_sequence=60,
        latest_observed_at=rows[-1].observed_at, receipt_age_seconds=0,
        matches_canonical_sequence=True)
    return comparison, prediction, reference


def decide(comparison, prediction, reference, **kwargs):
    return evaluate(comparison, prediction, reference,
                    generated_at=comparison.baseline.captured_at, **kwargs)


class RecommendationPolicyTests(unittest.TestCase):
    def test_normal_warning_critical_and_approval(self):
        for status, action, rule in (
            ('NORMAL', 'continue_monitoring', 'R2_NORMAL'),
            ('WARNING', 'maintenance_after_current_batch', 'R4_WARNING_BOUNDED_DEFERRAL'),
            ('CRITICAL', 'maintenance_now', 'R6_CRITICAL'),
        ):
            args = evidence(status)
            before = copy.deepcopy(args)
            result = decide(*args)
            self.assertEqual(result.predictive_status_used, status)
            self.assertEqual(result.recommended_action, action)
            self.assertEqual(result.rule_id, rule)
            self.assertEqual(result.recommendation_status, 'recommended')
            self.assertEqual(result.data_quality.classification, 'adequate')
            self.assertEqual(result.human_approval_required, status != 'NORMAL')
            self.assertFalse(result.automatic_execution_allowed)
            self.assertIsNone(result.estimated_scenario_evidence.preferred_scenario)
            self.assertEqual(args, before)
            self.assertEqual(result, decide(*args))

    def test_warning_deferral_limit_inclusive(self):
        for seconds, expected in ((0, 'maintenance_after_current_batch'),
                                  (MAX_WARNING_DEFERRAL_SECONDS, 'maintenance_after_current_batch'),
                                  (MAX_WARNING_DEFERRAL_SECONDS+.01, 'manual_review_required')):
            result = decide(*evidence('WARNING', remaining_batch_seconds=seconds))
            self.assertEqual(result.recommended_action, expected)
            self.assertTrue(result.human_approval_required)

    def test_incomplete_comparison(self):
        for status in ('NORMAL', 'WARNING', 'CRITICAL'):
            result = decide(*evidence(status, remaining_batch_seconds=None))
            self.assertFalse(result.data_quality.timing_complete)
            self.assertEqual(result.data_quality.classification, 'partial')
            self.assertEqual(result.recommended_action, 'continue_monitoring' if status == 'NORMAL' else 'manual_review_required')
            self.assertEqual(result.recommendation_status, 'degraded' if status == 'NORMAL' else 'review_required')

    def test_missing_or_partial_predictive_evidence(self):
        comparison, prediction, reference = evidence('CRITICAL')
        for changed in (None,
                        prediction.model_copy(update={'status': 'INSUFFICIENT_DATA', 'risk_score': None}),
                        prediction.model_copy(update={'reason': 'Some detectors are unscorable'}),
                        prediction.model_copy(update={'top_signals': []}),
                        prediction.model_copy(update={'status': 'NORMAL'}),
                        prediction.model_copy(update={'run_id': 'other'})):
            result = decide(comparison, changed, reference)
            self.assertEqual(result.recommended_action, 'manual_review_required')
            self.assertTrue(result.missing_evidence)

    def test_stale_invalid_and_faulted_canonical_state(self):
        comparison, prediction, reference = evidence('CRITICAL')
        for update in ({'source_connected': False}, {'valid': False}, {'fresh': False},
                       {'state': 'OFFLINE'}, {'active_fault': 'jam'}):
            changed = comparison.model_copy(update={'baseline': comparison.baseline.model_copy(update=update)})
            result = decide(changed, prediction, reference)
            self.assertEqual(result.recommended_action, 'manual_review_required')
            self.assertFalse(result.data_quality.canonical_usable)

    def test_receipt_age_and_alignment(self):
        comparison, prediction, reference = evidence('CRITICAL')
        for update in ({'receipt_age_seconds': 60.01}, {'receipt_age_seconds': -1},
                       {'receipt_age_seconds': None}, {'matches_canonical_sequence': False}):
            result = decide(comparison, prediction, reference.model_copy(update=update))
            self.assertEqual(result.recommended_action, 'manual_review_required')
        self.assertEqual(decide(comparison, prediction, reference.model_copy(update={'receipt_age_seconds': 60})).recommended_action,
                         'maintenance_now')

    def test_missing_required_timing_metric_is_not_zero(self):
        comparison, prediction, reference = evidence('WARNING')
        del comparison.scenario_b.metrics['maintenance_start_offset_seconds']
        self.assertEqual(decide(comparison, prediction, reference).recommended_action, 'manual_review_required')


class RecommendationApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry, self.rows = fixture('WARNING')
        self.store = AsyncMock()
        self.store.history.return_value = [row.model_dump() for row in self.rows]
        self.registry_patch = patch.object(main, 'registry', self.registry)
        self.store_patch = patch.object(main, 'store', self.store)
        self.registry_patch.start()
        self.store_patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.registry_patch.stop()
        self.store_patch.stop()

    async def post(self, **changes):
        return await self.client.post(PATH, json=request(**changes).model_dump())

    async def test_actual_services_single_read_and_no_actuation(self):
        before = copy.deepcopy(self.registry.__dict__)
        with patch.object(main.sync_service, 'sync_once', AsyncMock()) as sync, \
             patch('httpx.AsyncClient.request', side_effect=AssertionError('Unexpected outbound HTTP')) as outbound:
            response = await self.client.send(self.client.build_request('POST', PATH, json=request().model_dump()))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['recommended_action'], 'maintenance_after_current_batch')
        self.assertEqual(body['predictive_status_used'], 'WARNING')
        self.assertEqual(body['predictive_risk_used'], .5)
        self.assertEqual(body['calculated_predictive_evidence']['method'], 'z_score_ewma')
        self.assertTrue(body['human_approval_required'])
        self.assertFalse(body['automatic_execution_allowed'])
        self.assertEqual(body['policy_version'], 'maintenance_policy.v1')
        self.assertEqual(body['predictive_evidence_reference']['latest_sequence'], 60)
        self.store.history.assert_awaited_once_with('CNC_01', 'telemetry', 60, 0, 'r', latest=True)
        self.assertEqual([call[0] for call in self.store.mock_calls], ['history'])
        sync.assert_not_awaited()
        outbound.assert_not_called()
        self.assertEqual(before, self.registry.__dict__)

    async def test_normal_and_critical_api(self):
        for status, expected in (('NORMAL', 'continue_monitoring'), ('CRITICAL', 'maintenance_now')):
            r, rows = fixture(status)
            self.store.history.return_value = [row.model_dump() for row in rows]
            with patch.object(main, 'registry', r):
                response = await self.post()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['recommended_action'], expected)

    async def test_unavailable_persistence_and_empty_history(self):
        with patch.object(main, 'store', None):
            response = await self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['recommended_action'], 'manual_review_required')
        self.assertIsNone(response.json()['calculated_predictive_evidence'])
        self.store.history.side_effect = PersistenceError('secret DSN')
        response = await self.post()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('secret', response.text)
        self.assertEqual(response.json()['recommended_action'], 'manual_review_required')
        self.store.history.side_effect = None
        self.store.history.return_value = []
        response = await self.post()
        self.assertEqual(response.json()['predictive_status_used'], 'INSUFFICIENT_DATA')
        self.assertEqual(response.json()['recommended_action'], 'manual_review_required')

    async def test_persisted_sequence_lag_and_old_receipt(self):
        self.store.history.return_value = [r.model_dump() for r in self.rows[:-1]]
        response = await self.post()
        self.assertEqual(response.json()['recommended_action'], 'manual_review_required')
        self.assertFalse(response.json()['predictive_evidence_reference']['matches_canonical_sequence'])
        rows = [r.model_copy(update={'observed_at': r.observed_at-timedelta(minutes=2)}) for r in self.rows]
        self.store.history.return_value = [r.model_dump() for r in rows]
        response = await self.post()
        self.assertEqual(response.json()['recommended_action'], 'manual_review_required')

    async def test_stale_context_and_invalid_evidence_window(self):
        self.registry.mark_sync_failure('unavailable')
        self.assertEqual((await self.post()).json()['recommended_action'], 'manual_review_required')
        self.registry.mark_sync_success()
        for changed in (self.rows[0].model_copy(update={'valid': False}),
                        self.rows[0].model_copy(update={'sequence': 0})):
            rows = [changed] + self.rows[1:]
            self.store.history.return_value = [r.model_dump() for r in rows]
            self.assertEqual((await self.post()).json()['recommended_action'], 'manual_review_required')

    async def test_initial_and_inflight_context_conflicts(self):
        self.assertEqual((await self.post(run_id='old')).status_code, 409)
        self.assertEqual((await self.post(expected_sequence=61)).status_code, 409)
        self.store.history.assert_not_awaited()
        self.assertEqual((await self.post(asset_id='missing')).status_code, 404)

        async def change_context(*args, **kwargs):
            self.registry.get('CNC_01').sequence = 61
            return [r.model_dump() for r in self.rows]

        self.store.history.side_effect = change_context
        self.assertEqual((await self.post(expected_sequence=None)).status_code, 409)

    async def test_v1_selection_and_request_validation(self):
        self.store.history.return_value = [r.model_dump() for r in self.rows[-31:]]
        response = await self.post(predictive_method='rolling_z_score')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['calculated_predictive_evidence']['contract_version'], 'predictive.v1')
        self.store.history.assert_awaited_with('CNC_01', 'telemetry', 31, 0, 'r', latest=True)
        for change in ({'predictive_method': 'unknown'}, {'maintenance_duration_seconds': 0},
                       {'remaining_batch_seconds': -1}, {'human_approval_required': False}):
            body = request().model_dump()
            body.update(change)
            self.assertEqual((await self.client.post(PATH, json=body)).status_code, 422)

    async def test_malformed_evidence_sanitization_and_openapi(self):
        self.store.history.return_value = [{'id': 'secret malformed row'}]
        response = await self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['recommended_action'], 'manual_review_required')
        self.assertNotIn('secret', response.text)
        self.store.history.side_effect = RuntimeError('secret backend error')
        response = await self.post()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('secret', response.text)
        schema = (await self.client.get('/openapi.json')).json()
        route = schema['paths'][PATH]
        self.assertEqual(set(route), {'post'})
        self.assertTrue(route['post']['requestBody']['required'])
        self.assertTrue(route['post']['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/MaintenanceRecommendation'))
