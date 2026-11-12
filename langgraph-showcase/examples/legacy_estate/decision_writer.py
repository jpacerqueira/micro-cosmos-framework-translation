"""Legacy decision output writer (Python 2 style)."""

import csv
import os
import time

_OUT_FILE = os.path.join(os.path.dirname(__file__), "decisions.csv")

_FIELDNAMES = ["timestamp", "customer_id", "decision", "interest"]


def write_decision(customer_id, decision, interest):
    exists = os.path.exists(_OUT_FILE)
    with open(_OUT_FILE, "ab") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "customer_id": customer_id,
            "decision": decision,
            "interest": "%.2f" % interest,
        })
