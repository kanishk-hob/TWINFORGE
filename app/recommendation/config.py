"""Provisional, explicit policy settings; calibrate before operational use."""
from app.predictive.config import WARNING_THRESHOLD, CRITICAL_THRESHOLD

POLICY_VERSION = 'maintenance_policy.v1'
MAX_WARNING_DEFERRAL_SECONDS = 300.0
MAX_PREDICTIVE_RECEIPT_AGE_SECONDS = 60.0
MIN_MAINTENANCE_EVIDENCE_QUALITY = 'adequate'

# Reuse the predictive status boundaries; never reinterpret risk as probability.
STATUS_RISK_BOUNDS = {
    'NORMAL': (0.0, WARNING_THRESHOLD),
    'WARNING': (WARNING_THRESHOLD, CRITICAL_THRESHOLD),
    'CRITICAL': (CRITICAL_THRESHOLD, 1.0),
}
