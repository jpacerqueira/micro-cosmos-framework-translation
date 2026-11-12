"""Legacy customer data reader (Python 2 style)."""

import csv
import os

_DATA_FILE = os.path.join(os.path.dirname(__file__), "customers.csv")

_CACHE = {}


def read_customer(customer_id):
    global _CACHE
    if not _CACHE:
        _CACHE = _load_all()
    return _CACHE.get(customer_id)


def _load_all():
    records = {}
    try:
        with open(_DATA_FILE, "rb") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                records[row["id"]] = row
    except IOError:
        print "WARNING: customers.csv not found; returning empty dataset"
    return records


def query_database_stale(conn):
    """Placeholder function to simulate performance anti-pattern (SQL inside a loop)."""
    for i in range(100):
        conn.execute("SELECT CUST_NAME FROM CUSTOMER_TABLE WHERE CUSTOMER_ID = ?", (i,))
