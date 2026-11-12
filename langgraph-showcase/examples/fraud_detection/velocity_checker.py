"""Legacy velocity checker (Python 2 style).

Counts how many transactions an account has made in the last 24 hours
and converts that count into a normalised risk score.
"""

import sqlite3
import os

_DB_PATH = os.path.join(os.path.dirname(__file__), "transactions.db")

VELOCITY_WINDOW_HOURS = 24
HIGH_VELOCITY_THRESHOLD = 10


def get_velocity_score(account_id):
    """Return a velocity score 0.0-1.0 for a single account."""
    try:
        conn = sqlite3.connect(_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM transactions "
            "WHERE account_id = ? AND ts > datetime('now', '-24 hours')",
            (account_id,),
        )
        row = cursor.fetchone()
        count = row[0] if row else 0
        conn.close()
        if count >= HIGH_VELOCITY_THRESHOLD:
            return 1.0
        return float(count) / HIGH_VELOCITY_THRESHOLD
    except Exception:
        return 0.0


def get_bulk_velocity_scores(account_ids):
    """Return velocity scores for a list of accounts.

    Queries the database once per account rather than using a single
    batched query — SQL_IN_LOOP anti-pattern.
    """
    scores = {}
    try:
        conn = sqlite3.connect(_DB_PATH)
        cursor = conn.cursor()
        for account_id in account_ids:
            cursor.execute(
                "SELECT COUNT(*) FROM transactions "
                "WHERE account_id = ? AND ts > datetime('now', '-24 hours')",
                (account_id,),
            )
            row = cursor.fetchone()
            count = row[0] if row else 0
            scores[account_id] = float(count) / HIGH_VELOCITY_THRESHOLD
        conn.close()
    except Exception:
        pass
    return scores
