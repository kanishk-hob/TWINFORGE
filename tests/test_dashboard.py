"""Static delivery and route isolation; no lifespan/source or database writes."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
import app.main as main
from app.twin.registry import TwinRegistry


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_html_and_assets(self):
        response = await self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Operator dashboard', response.text)
        for name in ('styles.css', 'api.js', 'dashboard.js', 'kpi.js', 'history.js'):
            response = await self.client.get('/dashboard/' + name)
            self.assertEqual(response.status_code, 200, name)
            self.assertTrue(response.content)

    async def test_static_path_independent_of_working_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual((await self.client.get('/dashboard/')).status_code, 200)
            finally:
                os.chdir(previous)

    async def test_console_modules_and_built_assets(self):
        for name in ('client.js', 'data.js', 'console.js', 'components.js',
                     'analysis-view.js', 'evidence-view.js', 'charts.js'):
            self.assertEqual((await self.client.get('/dashboard/' + name)).status_code, 200)
        build = Path(main.__file__).parent / 'static/dashboard/build'
        if not build.exists():
            self.skipTest('Run npm ci and npm run build in frontend for bundled asset verification')
        for name in ('console.js', 'console.css'):
            response = await self.client.get('/dashboard/build/' + name)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content)

    async def test_api_routes_preserved(self):
        with patch.object(main, 'registry', TwinRegistry()), patch.object(main, 'store', None):
            self.assertEqual((await self.client.get('/health')).json()['status'], 'ok')
            self.assertEqual((await self.client.get('/api/twins')).json(), [])
            self.assertEqual((await self.client.get('/api/twins/unknown')).status_code, 404)
            self.assertFalse((await self.client.get('/api/source-status')).json()['connected'])
            self.assertFalse((await self.client.get('/api/persistence-status')).json()['enabled'])
            self.assertEqual((await self.client.get('/api/twins/unknown/telemetry')).status_code, 503)
            self.assertEqual((await self.client.get('/api/twins/unknown/kpis')).status_code, 422)
            self.assertEqual((await self.client.get('/openapi.json')).status_code, 200)

    async def test_missing_asset_and_traversal(self):
        for path in ('/dashboard/missing.js', '/dashboard/%2e%2e/main.py'):
            self.assertEqual((await self.client.get(path)).status_code, 404)

    def test_read_only_safe_source(self):
        directory = Path(main.__file__).parent / 'static/dashboard'
        scripts = '\n'.join(p.read_text() for p in directory.glob('*.js'))
        for forbidden in ('innerHTML', 'insertAdjacentHTML', '/sync', 'localhost:8000', '127.0.0.1:8000', 'CNC_01', 'QC_01'):
            self.assertNotIn(forbidden, scripts)
        self.assertIn("method:'GET'", scripts)
