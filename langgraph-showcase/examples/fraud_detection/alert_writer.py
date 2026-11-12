"""Legacy fraud alert writer (Python 2 style).

Appends a row to the fraud_alerts CSV whenever a transaction is flagged.
"""

import csv
import os
import time

_OUT_FILE = os.path.join(os.path.dirname(__file__), "fraud_alerts.csv")

_FIELDNAMES = ["timestamp", "txn_id", "account_id", "score", "amount", "status"]


def write_alert(txn_id, account_id, score, amount):
    exists = os.path.exists(_OUT_FILE)
    with open(_OUT_FILE, "ab") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp":  time.strftime("%Y-%m-%dT%H:%M:%S"),
            "txn_id":     txn_id,
            "account_id": account_id,
            "score":      "%.4f" % float(score),
            "amount":     "%.2f" % float(amount),
            "status":     "PENDING_REVIEW",
        })
