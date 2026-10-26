"""Pure kpi.v1 calculations. No HTTP, database, simulator or wall-clock access."""
import math
from datetime import timezone

from app.kpi.models import Metric, KpiResult


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def ratio(numerator, denominator, unit="fraction", estimated=False):
    if not number(numerator) or not number(denominator):
        return Metric(unit=unit, reason="Missing or invalid inputs")
    if denominator == 0:
        return Metric(unit=unit, status="not_applicable", reason="Zero denominator")
    return Metric(value=numerator / denominator, unit=unit, status="estimated" if estimated else "ok")


def oee_components(planned_seconds, runtime_seconds, ideal_cycle_seconds, good_count, total_count):
    """Use only with independently established complete inputs, never sampled runtime."""
    availability = ratio(runtime_seconds, planned_seconds)
    if number(runtime_seconds) and number(planned_seconds) and runtime_seconds > planned_seconds:
        availability = Metric(unit="fraction", reason="Runtime exceeds planned production time")
    performance = Metric(unit="fraction", reason="Positive ideal cycle time and total count required")
    counts_valid = all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (good_count, total_count))
    if number(ideal_cycle_seconds) and ideal_cycle_seconds > 0 and counts_valid:
        performance = ratio(ideal_cycle_seconds * total_count, runtime_seconds)
        if performance.value is not None and performance.value > 1:
            performance = Metric(unit="fraction", reason="Performance exceeds 1; verify ideal cycle and counts")
    quality = ratio(good_count, total_count) if counts_valid and good_count <= total_count else Metric(unit="fraction", reason="Invalid counts")
    components = dict(availability=availability, performance=performance, quality=quality)
    components['oee'] = Metric(unit="fraction", reason="All three OEE components must be valid")
    if all(m.status == 'ok' for m in (availability, performance, quality)):
        components['oee'] = Metric(value=availability.value * performance.value * quality.value, unit="fraction", status="ok")
    return components


def validate_window(start, end):
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("start and end must include timezone offsets")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if not 0 < (end - start).total_seconds() <= 86400:
        raise ValueError("Window must be positive and at most 24 hours")
    return start, end


def calculate(observations, *, source, run_id, asset_id, start, end, max_gap_seconds=5):
    start, end = validate_window(start, end)
    if not number(max_gap_seconds) or max_gap_seconds == 0:
        raise ValueError("max_gap_seconds must be positive and finite")
    units = dict(availability="fraction", performance="fraction", quality="fraction", oee="fraction",
                 throughput="good units/hour", wip="units", downtime="seconds", reject_rate="fraction",
                 energy_consumption="kWh", energy_per_good_unit="kWh/good unit")
    metrics = {key: Metric(unit=unit, reason="Incomplete observation window") for key, unit in units.items()}
    for key, reason in dict(availability="Planned production schedule and trustworthy runtime unavailable",
                            performance="Certified ideal cycle time and trustworthy runtime unavailable",
                            oee="Availability and performance unavailable",
                            wip="Unit/job/buffer ledger unavailable").items():
        metrics[key].reason = reason
    reasons, rows, seen = [], [], {}
    for row in observations:
        if (row.source, row.run_id, row.asset_id) != (source, run_id, asset_id):
            raise ValueError("Mixed source/run/asset context")
        if not isinstance(row.sequence, int) or isinstance(row.sequence, bool) or row.sequence < 0:
            raise ValueError("Sequence must be a nonnegative integer")
        if row.sequence in seen:
            if seen[row.sequence] != row:
                reasons.append("Conflicting duplicate sequence")
            continue
        seen[row.sequence] = row
        rows.append(row)
    duration = (end - start).total_seconds()
    result = KpiResult(source=source, run_id=run_id, asset_id=asset_id, start=start, end=end,
                       window_seconds=duration, max_gap_seconds=max_gap_seconds, coverage=0,
                       observation_count=len(rows), completeness="incomplete", reasons=[], metrics=metrics)
    if len(rows) < 2:
        reasons.append("At least two boundary observations required")
    times = [r.source_timestamp for r in rows]
    if any(t is None or t.utcoffset() is None for t in times):
        reasons.append("Missing or timezone-naive source timestamp")
    if reasons:
        result.reasons = list(dict.fromkeys(reasons))
        return result
    if times[0] != start or times[-1] != end:
        reasons.append("Exact start and end observations required")
    if any(b.sequence <= a.sequence or b.source_timestamp <= a.source_timestamp for a, b in zip(rows, rows[1:])):
        result.reasons = ["Out-of-order sequence or source timestamp"]
        return result
    covered = 0.0
    for a, b in zip(rows, rows[1:]):
        seconds = (b.source_timestamp - a.source_timestamp).total_seconds()
        if b.sequence != a.sequence + 1:
            reasons.append("Sequence gap")
        elif seconds > max_gap_seconds:
            reasons.append("Source timestamp gap")
        elif not (a.valid and a.fresh and b.valid and b.fresh):
            reasons.append("Invalid or stale observation")
        else:
            covered += max(0, (min(end, b.source_timestamp) - max(start, a.source_timestamp)).total_seconds())
    result.coverage = min(1.0, covered / duration)
    if reasons:
        result.reasons = list(dict.fromkeys(reasons))
        return result
    result.completeness = "complete"

    counts_valid = all(all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                           for v in (r.good_count, r.reject_count, r.total_count))
                       and r.good_count + r.reject_count == r.total_count for r in rows)
    if counts_valid:
        counts_valid = all(b.good_count >= a.good_count and b.reject_count >= a.reject_count
                           and b.total_count >= a.total_count for a, b in zip(rows, rows[1:]))
    good = None
    if counts_valid:
        good = rows[-1].good_count - rows[0].good_count
        rejects = rows[-1].reject_count - rows[0].reject_count
        total = rows[-1].total_count - rows[0].total_count
        metrics['quality'] = ratio(good, total)
        metrics['reject_rate'] = ratio(rejects, total)
        metrics['throughput'] = ratio(good * 3600, duration, "good units/hour")
    else:
        for key in ('quality', 'reject_rate', 'throughput', 'energy_per_good_unit'):
            metrics[key].reason = "Missing/inconsistent production counters or counter reset"

    energy, energy_valid = 0.0, True
    for a, b in zip(rows, rows[1:]):
        seconds = (b.source_timestamp - a.source_timestamp).total_seconds()
        if not number(b.interval_power_kw) or not number(b.interval_seconds) or not math.isclose(b.interval_seconds, seconds, rel_tol=0, abs_tol=1e-6):
            energy_valid = False
            break
        energy += b.interval_power_kw * seconds / 3600
    if energy_valid and math.isfinite(energy):
        metrics['energy_consumption'] = Metric(value=energy, unit="kWh", status="estimated", reason="Integrated source interval-average power")
        metrics['energy_per_good_unit'] = ratio(energy, good, "kWh/good unit", estimated=True)
    else:
        metrics['energy_consumption'].reason = "Missing/invalid interval power or mismatched interval duration"
        metrics['energy_per_good_unit'].reason = "Energy unavailable"

    states = {'RUNNING', 'IDLE', 'SETUP', 'BLOCKED', 'STARVED', 'FAULT', 'OFFLINE'}
    if all(row.state in states for row in rows):
        breakdown = {}
        for a, b in zip(rows, rows[1:]):
            if a.state != 'RUNNING':
                reason = a.active_fault or a.state
                breakdown[reason] = breakdown.get(reason, 0) + (b.source_timestamp - a.source_timestamp).total_seconds()
        metrics['downtime'] = Metric(value=sum(breakdown.values()), unit="seconds", status="estimated", reason="Left-held sampled states; not verified OEE downtime")
        result.downtime_reasons_seconds = breakdown
    else:
        metrics['downtime'].reason = "Unrecognized machine state"
    result.metrics = metrics
    return result
