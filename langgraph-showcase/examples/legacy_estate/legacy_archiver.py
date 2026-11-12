"""Legacy flat-file archiver (Python 2 style)."""

import os
import time

_ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), "archive")


def archive_record(customer_id, decision):
    if not os.path.exists(_ARCHIVE_DIR):
        os.makedirs(_ARCHIVE_DIR)
    stamp = time.strftime("%Y%m%d")
    filename = "%s_%s_%s.txt" % (stamp, customer_id, decision)
    path = os.path.join(_ARCHIVE_DIR, filename)
    with open(path, "wb") as fh:
        fh.write("customer=%s decision=%s ts=%s\n" % (
            customer_id, decision, time.strftime("%Y-%m-%dT%H:%M:%S"),
        ))
