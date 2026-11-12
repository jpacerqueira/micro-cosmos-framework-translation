"""Legacy fraud rules engine (Python 2 style).

Combines amount thresholds, blocked merchant codes, and velocity scoring
into a single composite fraud score between 0.0 and 1.0.
"""

from velocity_checker import get_velocity_score

AMOUNT_THRESHOLDS = {
    "HIGH_RISK":   float(5000),
    "MEDIUM_RISK": float(1000),
    "LOW_RISK":    float(200),
}

BLOCKED_MERCHANTS = ["MCC9999", "MCC8888", "MCC7777"]

AMOUNT_WEIGHT   = 0.40
MERCHANT_WEIGHT = 0.40
VELOCITY_WEIGHT = 0.20


def _amount_score(amount):
    if amount >= AMOUNT_THRESHOLDS["HIGH_RISK"]:
        return 0.8
    if amount >= AMOUNT_THRESHOLDS["MEDIUM_RISK"]:
        return 0.5
    if amount >= AMOUNT_THRESHOLDS["LOW_RISK"]:
        return 0.3
    return 0.1


def _merchant_score(merchant_code):
    if merchant_code in BLOCKED_MERCHANTS:
        return 1.0
    return 0.0


def evaluate_transaction(txn_id, account_id, amount, merchant_code):
    """Score a transaction for fraud risk. Returns float between 0.0 and 1.0."""
    amount_s   = _amount_score(float(amount))
    merchant_s = _merchant_score(merchant_code)
    velocity_s = get_velocity_score(account_id)

    score = (amount_s * AMOUNT_WEIGHT) + (merchant_s * MERCHANT_WEIGHT) + (velocity_s * VELOCITY_WEIGHT)
    return min(score, 1.0)
