"""Transactional PostgreSQL boundary; no simulator protocol dependencies."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

SOURCE = "factory_simulator"
HEALTH_EVIDENCE_LIMIT = 10000


class PersistenceError(Exception):
    """Public message never contains SQL, credentials, or source payloads."""


class HistoryWindowTooLarge(ValueError):
    pass


def source_time(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


class PostgresStore:
    def __init__(self, dsn, timeout=5):
        self._dsn = dsn
        self.timeout = timeout
        self._pool = None
        self._open_lock = asyncio.Lock()

    async def open(self):
        async with self._open_lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(
                    self._dsn, min_size=0, max_size=4,
                    timeout=self.timeout, command_timeout=self.timeout,
                )

    async def close(self):
        if self._pool is not None:
            try:
                await asyncio.wait_for(self._pool.close(), self.timeout)
            except TimeoutError:
                self._pool.terminate()
            finally:
                self._pool = None

    @asynccontextmanager
    async def connection(self):
        try:
            async with asyncio.timeout(self.timeout):
                await self.open()
                async with self._pool.acquire() as conn:
                    yield conn
        except Exception:
            raise PersistenceError("Database operation failed or timed out") from None

    async def migrate(self):
        async with self.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(71422001)")
            await conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
            for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
                if not await conn.fetchval("SELECT 1 FROM schema_migrations WHERE version=$1", path.name):
                    await conn.execute(path.read_text(encoding="utf-8"))
                    await conn.execute("INSERT INTO schema_migrations(version) VALUES ($1)", path.name)

    async def save(self, run_id, twins, observed_at):
        async with self.connection() as conn, conn.transaction():
            # Serialize writers so transitions are derived from committed predecessors.
            await conn.execute("SELECT pg_advisory_xact_lock(71422002)")
            await conn.execute("INSERT INTO source_runs VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", SOURCE, run_id, observed_at)
            for twin in twins:
                await conn.execute("INSERT INTO factories VALUES ($1) ON CONFLICT DO NOTHING", twin.factory_id)
                await conn.execute("INSERT INTO lines VALUES ($1,$2) ON CONFLICT DO NOTHING", twin.factory_id, twin.line_id)
                await conn.execute("""INSERT INTO assets VALUES ($1,$2,$3,$4)
                    ON CONFLICT (asset_id) DO UPDATE SET factory_id=$2,line_id=$3,asset_type=$4""",
                    twin.asset_id, twin.factory_id, twin.line_id, twin.asset_type)
                previous = await conn.fetchrow("""SELECT sequence,state,active_fault FROM observations
                    WHERE source=$1 AND run_id=$2 AND asset_id=$3 ORDER BY sequence DESC LIMIT 1""", SOURCE, run_id, twin.asset_id)
                if previous and twin.sequence <= previous["sequence"]:
                    continue
                oid = await conn.fetchval("""INSERT INTO observations
                    (source,run_id,asset_id,sequence,observed_at,source_timestamp,raw_source_timestamp,
                     telemetry_values,valid,fresh,quality_source,reason,state,active_fault,
                     good_count,reject_count,total_count,interval_power_kw,interval_seconds)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
                    ON CONFLICT DO NOTHING RETURNING id""",
                    SOURCE, run_id, twin.asset_id, twin.sequence, observed_at,
                    source_time(twin.telemetry.timestamp), twin.telemetry.timestamp,
                    None if twin.telemetry.values is None else json.dumps(twin.telemetry.values, allow_nan=False),
                    twin.quality.valid, twin.quality.fresh, twin.quality.source, twin.quality.reason,
                    twin.state, twin.active_fault, twin.operations.good_count,
                    twin.operations.reject_count, twin.operations.total_count,
                    twin.operations.interval_power_kw, twin.operations.interval_seconds)
                if oid is None:
                    continue
                events = []
                if previous is None:
                    events.append(("state_observed", None, twin.state))
                    if twin.active_fault is not None:
                        events.append(("fault_observed", None, twin.active_fault))
                else:
                    if previous["state"] != twin.state:
                        events.append(("state_changed", previous["state"], twin.state))
                    if previous["active_fault"] != twin.active_fault:
                        if previous["active_fault"] is not None:
                            events.append(("fault_recovered", previous["active_fault"], None))
                        if twin.active_fault is not None:
                            events.append(("fault_started", None, twin.active_fault))
                for kind, before, after in events:
                    await conn.execute("INSERT INTO machine_events(observation_id,kind,previous_value,value) VALUES ($1,$2,$3,$4)", oid, kind, before, after)

    async def history(self, asset_id, kind, limit=100, after_id=0, run_id=None, *, latest=False):
        if kind not in ("telemetry", "history") or not 1 <= limit <= 1000 or after_id < 0:
            raise ValueError("Invalid history query")
        async with self.connection() as conn:
            if kind == "telemetry":
                # Opt-in bounded recent telemetry; existing forward paging is unchanged.
                order = "DESC" if latest else "ASC"
                rows = await conn.fetch(f"""SELECT id,source,run_id,asset_id,sequence,observed_at,
                    source_timestamp,raw_source_timestamp,telemetry_values,valid,fresh,quality_source,reason
                    FROM observations WHERE asset_id=$1 AND id>$2 AND ($3::text IS NULL OR run_id=$3)
                    ORDER BY id {order} LIMIT $4""", asset_id, after_id, run_id, limit)
            else:
                rows = await conn.fetch("""SELECT e.id,o.source,o.run_id,o.asset_id,o.sequence,o.observed_at,
                    e.kind,e.previous_value,e.value FROM machine_events e JOIN observations o ON o.id=e.observation_id
                    WHERE o.asset_id=$1 AND e.id>$2 AND ($3::text IS NULL OR o.run_id=$3)
                    ORDER BY e.id LIMIT $4""", asset_id, after_id, run_id, limit)
            result = [dict(row) for row in rows]
            for row in result:
                if isinstance(row.get("telemetry_values"), str):
                    row["telemetry_values"] = json.loads(row["telemetry_values"])
            return result

    async def kpi_observations(self, source, run_id, asset_id, start, end):
        # The query is bounded and never silently truncates a calculation window.
        async with self.connection() as conn:
            rows = await conn.fetch("""SELECT source,run_id,asset_id,sequence,source_timestamp,
                valid,fresh,state,active_fault,good_count,reject_count,total_count,
                interval_power_kw,interval_seconds FROM observations
                WHERE source=$1 AND run_id=$2 AND asset_id=$3
                AND source_timestamp >= $4 AND source_timestamp <= $5
                ORDER BY id LIMIT 10001""", source, run_id, asset_id, start, end)
        if len(rows) > 10000:
            raise HistoryWindowTooLarge("KPI window exceeds 10000 observations; use a smaller window")
        return [dict(row) for row in rows]

    async def health_evidence(self, source, run_id, asset_id, start, end):
        """Bounded receipt-time evidence and separate nearest boundary records.

        All reads share a snapshot; capacity checks are outside connection() so
        validation errors are not sanitized into PersistenceError.
        """
        if not all(isinstance(v, str) and v.strip() for v in (source, run_id, asset_id)):
            raise ValueError("Nonempty source/run/asset required")
        if (not isinstance(start, datetime) or not isinstance(end, datetime)
                or start.utcoffset() is None or end.utcoffset() is None
                or not 0 < (end-start).total_seconds() <= 86400):
            raise ValueError("Health window must be timezone-aware, positive and at most 24 hours")
        columns = """id,source,run_id,asset_id,sequence,observed_at,source_timestamp,
            state,active_fault,telemetry_values,valid,fresh,quality_source,reason"""
        scope = "source=$1 AND run_id=$2 AND asset_id=$3"
        args = (source, run_id, asset_id, start, end)
        events, adjacent, identities = [], [], None
        async with self.connection() as conn, conn.transaction(isolation='repeatable_read', readonly=True):
            rows = await conn.fetch(f"""SELECT {columns} FROM observations
                WHERE {scope} AND observed_at >= $4 AND observed_at < $5
                ORDER BY observed_at,id LIMIT $6""", *args, HEALTH_EVIDENCE_LIMIT+1)
            if len(rows) <= HEALTH_EVIDENCE_LIMIT:
                # Joining only selected observation IDs bounds the event input too.
                events = await conn.fetch("""SELECT e.id,o.source,o.run_id,o.asset_id,
                    o.sequence,o.observed_at,o.source_timestamp,e.kind,e.previous_value,e.value
                    FROM machine_events e JOIN observations o ON o.id=e.observation_id
                    WHERE o.id=ANY($1::bigint[]) ORDER BY o.observed_at,e.id LIMIT $2""",
                    [r['id'] for r in rows], HEALTH_EVIDENCE_LIMIT+1)
                if len(events) <= HEALTH_EVIDENCE_LIMIT:
                    adjacent = await conn.fetch(f"""
                        (SELECT {columns}, 'before' AS boundary FROM observations
                         WHERE {scope} AND observed_at < $4
                         ORDER BY observed_at DESC,id DESC LIMIT 1)
                        UNION ALL
                        (SELECT {columns}, 'after' AS boundary FROM observations
                         WHERE {scope} AND observed_at >= $5
                         ORDER BY observed_at,id LIMIT 1)""", *args)
                    if not rows:
                        identities = await conn.fetchrow("""SELECT
                            EXISTS(SELECT 1 FROM assets WHERE asset_id=$1) AS asset_exists,
                            EXISTS(SELECT 1 FROM source_runs WHERE source=$2 AND run_id=$3) AS run_exists""",
                            asset_id, source, run_id)
        if len(rows) > HEALTH_EVIDENCE_LIMIT or len(events) > HEALTH_EVIDENCE_LIMIT:
            raise HistoryWindowTooLarge("Health evidence exceeds 10000 observations or events; use a smaller window")

        def observation(row):
            result = dict(row)
            result.pop('boundary', None)
            if isinstance(result.get('telemetry_values'), str):
                result['telemetry_values'] = json.loads(result['telemetry_values'])
            return result

        return dict(observations=[observation(r) for r in rows],
                    events=[dict(e) for e in events],
                    before=next((observation(r) for r in adjacent if r['boundary']=='before'), None),
                    after=next((observation(r) for r in adjacent if r['boundary']=='after'), None),
                    asset_exists=identities['asset_exists'] if identities else True,
                    run_exists=identities['run_exists'] if identities else True)
