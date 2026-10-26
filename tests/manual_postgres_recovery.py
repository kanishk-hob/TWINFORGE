"""Explicit real-process verification; never runs in normal unittest discovery.

Requires the dedicated twinforge-persistence-verification Docker container,
TWINFORGE_TEST_DATABASE_URL and its exact TWINFORGE_TEST_CONTAINER_ID.
Stops/restarts only that verified container. Leaves its database intact.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_source_connectivity import make_asset

CONTAINER = "twinforge-persistence-verification"


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=30)


def wait_for(predicate, description):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (httpx.HTTPError, KeyError, IndexError):
            pass
        time.sleep(.1)
    raise AssertionError("Timed out: " + description)


def main():
    dsn = os.environ["TWINFORGE_TEST_DATABASE_URL"]
    parsed = urlsplit(dsn)
    assert (parsed.hostname, parsed.port, parsed.path) == ("127.0.0.1", 55432, "/twinforge_test")
    container = json.loads(docker("inspect", CONTAINER))[0]
    assert container["Id"] == os.environ["TWINFORGE_TEST_CONTAINER_ID"]
    assert container["Config"]["Image"] == "postgres:17.11-alpine"
    assert "POSTGRES_DB=twinforge_test" in container["Config"]["Env"]
    assert container["NetworkSettings"]["Ports"]["5432/tcp"] == [{"HostIp": "127.0.0.1", "HostPort": "55432"}]
    env = os.environ.copy()
    env["TWINFORGE_DATABASE_URL"] = dsn
    env["TWINFORGE_DATABASE_TIMEOUT_SECONDS"] = "1"
    env["TWINFORGE_SYNC_POLL_INTERVAL_SECONDS"] = ".1"
    subprocess.run([sys.executable, "-m", "app.storage.migrate"], cwd=ROOT, env=env, check=True, timeout=20)
    token = uuid.uuid4().hex
    asset_id = "VERIFY_" + token
    asset = make_asset(asset_id=asset_id, sequence=1)
    fixture = {"available": True, "snapshot": {"run_id": token, "assets": [asset]}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = json.dumps(fixture["snapshot"]).encode()
            self.send_response(200 if fixture["available"] else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env["TWINFORGE_SIMULATOR_URL"] = f"http://127.0.0.1:{server.server_port}"
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        app_port = port_socket.getsockname()[1]
    client = httpx.Client(base_url=f"http://127.0.0.1:{app_port}", timeout=3, trust_env=False)
    process = None
    stopped_database = False

    def start():
        return subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(app_port)], cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def get(path):
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    path = f"/api/twins/{asset_id}"
    try:
        process = start()
        wait_for(lambda: get(path)["sequence"] == 1, "initial persisted sync")
        first = get(path + "/telemetry")
        assert len(first) == 1
        fixture["available"] = False
        wait_for(lambda: not get("/api/source-status")["connected"], "source disconnection")
        assert get(path + "/telemetry") == first
        assert get(path)["sequence"] == 1
        print("PASS: source disconnection retains live twins and PostgreSQL history", flush=True)

        process.terminate()
        process.wait(timeout=10)
        process = start()
        wait_for(lambda: get("/health")["status"] == "ok", "restarted app")
        assert get("/api/twins") == []
        assert get(path + "/telemetry") == first
        fixture["available"] = True
        wait_for(lambda: get(path)["sequence"] == 1, "registry repopulation")
        assert get(path + "/telemetry") == first
        print("PASS: process restart preserves history and repopulates registry without duplicates", flush=True)

        docker("stop", "--time", "5", CONTAINER)
        stopped_database = True
        wait_for(lambda: get("/api/persistence-status")["last_error"] is not None, "database outage")
        saved_status = get("/api/persistence-status")
        saved_source = get("/api/source-status")
        asset["dynamic_state"]["seq"] = 2
        asset["dynamic_state"]["state"] = "FAULT"
        asset["dynamic_state"]["active_fault"] = "TEST_FAULT"
        response = client.post("/sync")
        assert response.status_code == 503
        assert get("/api/persistence-status")["last_persisted_at"] == saved_status["last_persisted_at"]
        assert get("/api/source-status")["last_sync_at"] == saved_source["last_sync_at"]
        assert get(path)["sequence"] == 1
        assert get("/health")["status"] == "ok"
        assert client.get(path + "/telemetry").status_code == 503
        print("PASS: actual database outage reports failure; success timestamps and twins do not advance", flush=True)

        docker("start", CONTAINER)
        stopped_database = False
        wait_for(lambda: get(path)["sequence"] == 2, "automatic retry after database recovery")
        assert get("/api/persistence-status")["last_error"] is None
        rows = get(path + "/telemetry")
        assert [row["sequence"] for row in rows] == [1, 2]
        assert rows[0] == first[0]
        assert [row["kind"] for row in get(path + "/history")] == ["state_observed", "state_changed", "fault_started"]
        asset["dynamic_state"].update(seq=3, state="RUNNING", active_fault=None)
        wait_for(lambda: get(path)["sequence"] == 3, "fault recovery")
        assert [row["kind"] for row in get(path + "/history")][-2:] == ["state_changed", "fault_recovered"]
        print("PASS: automatic retry persists new telemetry and state/fault/recovery events after database restart", flush=True)
        print("REAL PROCESS RECOVERY CHECK: 4/4 passed", flush=True)
    finally:
        if stopped_database:
            docker("start", CONTAINER)
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
