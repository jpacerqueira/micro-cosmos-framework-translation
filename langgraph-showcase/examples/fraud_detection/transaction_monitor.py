"""Legacy fraud detection entry point (Python 2 style).

Loads a batch of transactions, scores each one against the rules engine,
and writes an alert for anything above the fraud threshold.
"""

from transaction_loader import load_transactions
from rules_engine import evaluate_transaction
from alert_writer import write_alert

FRAUD_THRESHOLD = 0.75
HIGH_VALUE_FLOOR = float(10000)


def monitor_batch(batch_date):
    transactions = load_transactions(batch_date)
    if not transactions:
        print "WARNING: no transactions found for batch %s" % batch_date
        return

    flagged = 0
    for txn in transactions:
        amount = float(txn.get("amount", 0))
        score = evaluate_transaction(
            txn["id"],
            txn["account_id"],
            amount,
            txn.get("merchant_code", ""),
        )
        if score >= FRAUD_THRESHOLD:
            write_alert(txn["id"], txn["account_id"], score, amount)
            flagged += 1
            print "ALERT: transaction %s flagged (score=%.3f amount=%.2f)" % (
                txn["id"], score, amount
            )
        elif amount >= HIGH_VALUE_FLOOR:
            print "INFO: high-value transaction %s passed screening (score=%.3f)" % (
                txn["id"], score
            )

    print "Batch %s complete: %d of %d transactions flagged" % (
        batch_date, flagged, len(transactions)
    )


if __name__ == "__main__":
    import sys
    monitor_batch(sys.argv[1] if len(sys.argv) > 1 else "20240101")
