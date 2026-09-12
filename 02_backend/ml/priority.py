"""Presentation priority mapping for the demo's account alert queue.

The weighted account evidence determines rank; the displayed score is a
batch-relative review priority, not a calibrated probability.
"""

import hashlib

TARGET_ALERTS = 20
PRIORITY_BASE = 0.65
RANK_WEIGHT = 0.30
MIN_PRIORITY = 0.63
MAX_PRIORITY = 0.96


def priority_jitter(account_id: str) -> float:
    """Stable, small display offset so tied ranks remain visually distinct."""
    h = int(hashlib.md5(str(account_id).encode()).hexdigest(), 16) % 1000
    return (h / 1000.0 - 0.5) * 0.03


def display_priority(account_id: str, queue_percentile: float) -> float:
    raw = PRIORITY_BASE + RANK_WEIGHT * queue_percentile + priority_jitter(account_id)
    return min(MAX_PRIORITY, max(MIN_PRIORITY, raw))


def recover_legacy_queue_position(account_id: str, stored_score: float) -> dict | None:
    """Recover the rank mapping for old 20-alert batches without inventing inputs.

    Historical weighted signals were not persisted. We accept the reconstructed
    rank only when the score matches a valid position in a full 20-alert batch
    within the original four-decimal storage precision. Clipped scores and
    scores from other methods return None rather than a misleading explanation.
    """
    if stored_score is None or not account_id:
        return None
    score = float(stored_score)
    if score <= MIN_PRIORITY or score >= MAX_PRIORITY:
        return None
    estimated_rank = (score - PRIORITY_BASE - priority_jitter(account_id)) / RANK_WEIGHT
    position = round(estimated_rank * TARGET_ALERTS)
    if not 1 <= position <= TARGET_ALERTS:
        return None
    percentile = position / TARGET_ALERTS
    if abs(display_priority(account_id, percentile) - score) > 0.000051:
        return None
    return {
        "method": "recovered_legacy_queue_mapping",
        "account_evidence_score": None,
        "daily_queue_percentile": percentile,
        "display_priority_score": score,
        "base_priority": PRIORITY_BASE,
        "rank_contribution": RANK_WEIGHT * percentile,
        "jitter_contribution": round(priority_jitter(account_id), 5),
        "signals": [],
    }
