import os
import math


SIMULATOR_URL = os.getenv("TWINFORGE_SIMULATOR_URL", "http://127.0.0.1:8000")
SYNC_POLL_INTERVAL_SECONDS = float(
    os.getenv("TWINFORGE_SYNC_POLL_INTERVAL_SECONDS", "1.0")
)
SIMULATOR_TIMEOUT_SECONDS = float(
    os.getenv("TWINFORGE_SIMULATOR_TIMEOUT_SECONDS", "2.0")
)
SOURCE_STALE_AFTER_SECONDS = float(
    os.getenv("TWINFORGE_SOURCE_STALE_AFTER_SECONDS", "5.0")
)

# Never log this value: it may contain database credentials.
DATABASE_URL = os.getenv("TWINFORGE_DATABASE_URL") or None
DATABASE_TIMEOUT_SECONDS = float(os.getenv("TWINFORGE_DATABASE_TIMEOUT_SECONDS", "5"))
if not math.isfinite(DATABASE_TIMEOUT_SECONDS) or DATABASE_TIMEOUT_SECONDS <= 0:
    raise ValueError("TWINFORGE_DATABASE_TIMEOUT_SECONDS must be positive and finite")

KPI_MAX_GAP_SECONDS = float(os.getenv("TWINFORGE_KPI_MAX_GAP_SECONDS", "5"))
if not math.isfinite(KPI_MAX_GAP_SECONDS) or KPI_MAX_GAP_SECONDS <= 0:
    raise ValueError("TWINFORGE_KPI_MAX_GAP_SECONDS must be positive and finite")
