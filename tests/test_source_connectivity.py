import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx

import app.main as main_module
from app.services.sync_service import SyncService
from app.twin.registry import TwinRegistry


def make_asset(asset_id="CNC_01", sequence=1):
    return {
        "asset_id": asset_id,
        "identity": {
            "type": "CNC",
            "factory_id": "FACTORY_01",
            "line_id": "LINE_01",
        },
        "dynamic_state": {
            "state": "RUNNING",
            "current_job_id": "JOB_001",
            "active_fault": None,
            "seq": sequence,
            "last_telemetry_timestamp": "2026-10-24T12:00:00Z",
            "values": {"temperature": 42.0},
        },
        "health": {"health_score": 99.0, "anomaly_score": 0.01},
        "data_quality": {
            "valid": True,
            "fresh": True,
            "source": "factory_simulator",
            "reason": None,
        },
        "relationships": {"upstream": None, "downstream": None},
    }


def make_snapshot(run_id="run-1", sequence=1):
    return {"run_id": run_id, "assets": [make_asset(sequence=sequence)]}


def connection_error():
    request = httpx.Request("GET", "http://127.0.0.1:8000/api/v1/snapshot")
    return httpx.ConnectError("connection refused", request=request)


class SyncServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_initial_connection_and_sync(self):
        registry = TwinRegistry()
        service = SyncService(registry, AsyncMock(return_value=make_snapshot()))

        result = await service.sync_once()

        self.assertEqual(result, {"run_id": "run-1", "accepted": 1, "rejected": 0})
        self.assertTrue(registry.source_connected)
        self.assertEqual(registry.current_run_id, "run-1")
        self.assertIsNotNone(registry.last_sync_attempt_at)
        self.assertIsNotNone(registry.last_sync_at)
        self.assertEqual(registry.consecutive_failures, 0)

    async def test_simulator_unavailable_at_startup_does_not_stop_loop(self):
        registry = TwinRegistry()
        service = None

        async def unavailable():
            service.stop()
            raise connection_error()

        service = SyncService(registry, unavailable, poll_interval_seconds=0.01)
        await service.run_forever()

        self.assertFalse(service.running)
        self.assertFalse(registry.source_connected)
        self.assertEqual(registry.consecutive_failures, 1)
        self.assertIn("Simulator unavailable", registry.last_sync_error)

    async def test_disconnect_after_success_preserves_twins(self):
        registry = TwinRegistry()
        fetcher = AsyncMock(side_effect=[make_snapshot(), connection_error()])
        service = SyncService(registry, fetcher)

        await service.sync_once()
        with self.assertRaises(httpx.ConnectError):
            await service.sync_once()

        self.assertFalse(registry.source_connected)
        self.assertEqual(len(registry.get_all()), 1)
        self.assertEqual(registry.get("CNC_01").sequence, 1)

    async def test_failed_poll_does_not_update_last_success(self):
        registry = TwinRegistry()
        fetcher = AsyncMock(side_effect=[make_snapshot(), connection_error()])
        service = SyncService(registry, fetcher)

        await service.sync_once()
        last_success = registry.last_sync_at
        with self.assertRaises(httpx.ConnectError):
            await service.sync_once()

        self.assertEqual(registry.last_sync_at, last_success)
        self.assertGreaterEqual(registry.last_sync_attempt_at, last_success)

    async def test_automatic_recovery_after_simulator_returns(self):
        registry = TwinRegistry()
        service = None
        responses = iter([make_snapshot(sequence=1), connection_error(), make_snapshot(sequence=2)])

        async def changing_source():
            item = next(responses)
            if isinstance(item, Exception):
                raise item
            if item["assets"][0]["dynamic_state"]["seq"] == 2:
                service.stop()
            return item

        service = SyncService(registry, changing_source, poll_interval_seconds=0.01)
        await service.run_forever()

        self.assertTrue(registry.source_connected)
        self.assertEqual(registry.consecutive_failures, 0)
        self.assertIsNone(registry.last_sync_error)
        self.assertEqual(registry.get("CNC_01").sequence, 2)

    async def test_run_id_change_accepts_reset_sequence(self):
        registry = TwinRegistry()
        fetcher = AsyncMock(
            side_effect=[make_snapshot("run-1", 9), make_snapshot("run-2", 0)]
        )
        service = SyncService(registry, fetcher)

        await service.sync_once()
        result = await service.sync_once()

        self.assertEqual(result["accepted"], 1)
        self.assertEqual(registry.current_run_id, "run-2")
        self.assertEqual(registry.get("CNC_01").sequence, 0)

    async def test_same_run_rejects_non_increasing_sequence(self):
        registry = TwinRegistry()
        fetcher = AsyncMock(
            side_effect=[make_snapshot("run-1", 2), make_snapshot("run-1", 2)]
        )
        service = SyncService(registry, fetcher)

        await service.sync_once()
        result = await service.sync_once()

        self.assertEqual(result["rejected"], 1)
        self.assertEqual(registry.get("CNC_01").sequence, 2)

    async def test_timeout_and_http_errors_are_safely_summarized(self):
        request = httpx.Request("GET", "http://simulator/api/v1/snapshot")
        response = httpx.Response(503, request=request)
        errors = [
            (httpx.ReadTimeout("slow", request=request), "timed out"),
            (httpx.HTTPStatusError("bad response", request=request, response=response), "HTTP 503"),
        ]

        for error, expected_message in errors:
            with self.subTest(error=type(error).__name__):
                registry = TwinRegistry()
                service = SyncService(registry, AsyncMock(side_effect=error))
                with self.assertRaises(type(error)):
                    await service.sync_once()
                self.assertIn(expected_message, registry.last_sync_error)
                self.assertNotIn("/api/v1/snapshot", registry.last_sync_error)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main_module.registry.twins.clear()
        main_module.registry.current_run_id = None
        main_module.registry.last_sync_at = None
        main_module.registry.last_sync_attempt_at = None
        main_module.registry.last_sync_error = None
        main_module.registry.consecutive_failures = 0
        main_module.registry.source_connected = False

    async def request(self, method, path):
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path)

    async def test_application_and_last_twins_remain_available_when_disconnected(self):
        service = SyncService(
            main_module.registry,
            AsyncMock(side_effect=[make_snapshot(), connection_error()]),
        )
        await service.sync_once()
        with self.assertRaises(httpx.ConnectError):
            await service.sync_once()

        health = await self.request("GET", "/health")
        twins = await self.request("GET", "/api/twins")
        status = await self.request("GET", "/api/source-status")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(len(twins.json()), 1)
        self.assertFalse(status.json()["connected"])
        self.assertEqual(status.json()["consecutive_failures"], 1)

    async def test_existing_twin_endpoints_return_twins_and_404(self):
        service = SyncService(main_module.registry, AsyncMock(return_value=make_snapshot()))
        await service.sync_once()

        found = await self.request("GET", "/api/twins/CNC_01")
        missing = await self.request("GET", "/api/twins/UNKNOWN")

        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.json()["asset_id"], "CNC_01")
        self.assertEqual(missing.status_code, 404)

    async def test_manual_sync_keeps_existing_success_contract(self):
        original_fetcher = main_module.sync_service.snapshot_fetcher
        main_module.sync_service.snapshot_fetcher = AsyncMock(
            return_value=make_snapshot("manual-run", 1)
        )

        try:
            response = await self.request("POST", "/sync")
        finally:
            main_module.sync_service.snapshot_fetcher = original_fetcher

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "synced",
                "run_id": "manual-run",
                "accepted": 1,
                "rejected": 0,
            },
        )

    async def test_source_status_marks_old_success_stale(self):
        main_module.registry.source_connected = True
        main_module.registry.last_sync_at = datetime.now(timezone.utc) - timedelta(hours=1)

        response = await self.request("GET", "/api/source-status")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["connected"])
        self.assertGreater(response.json()["sync_lag_seconds"], 3000)


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_stops_background_task(self):
        original_fetcher = main_module.sync_service.snapshot_fetcher
        original_interval = main_module.sync_service.poll_interval_seconds
        main_module.sync_service.snapshot_fetcher = AsyncMock(return_value=make_snapshot())
        main_module.sync_service.poll_interval_seconds = 60

        try:
            async with main_module.lifespan(main_module.app):
                await asyncio.sleep(0)
                self.assertTrue(main_module.sync_service.running)
            self.assertFalse(main_module.sync_service.running)
        finally:
            main_module.sync_service.snapshot_fetcher = original_fetcher
            main_module.sync_service.poll_interval_seconds = original_interval


if __name__ == "__main__":
    unittest.main()
