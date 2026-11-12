"""Legacy transaction data loader (Python 2 style).

Reads the master account list, then opens a separate CSV file per account
to collect that account's transactions for the given batch date.
"""

import csv
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_ACCOUNTS_FILE = os.path.join(_DATA_DIR, "accounts.csv")


def load_transactions(batch_date):
    """Return all transactions for batch_date across all accounts."""
    records = []

    try:
        with open(_ACCOUNTS_FILE, "rb") as fh:
            reader = csv.DictReader(fh)
            account_ids = [row["account_id"] for row in reader]
    except IOError:
        print "WARNING: accounts.csv not found; returning empty transaction set"
        return records

    for account_id in account_ids:
        txn_file = os.path.join(_DATA_DIR, "txns_%s.csv" % account_id)
        try:
            with open(txn_file, "rb") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    if row.get("batch_date") == batch_date:
                        records.append(row)
        except IOError:
            pass

    return records
