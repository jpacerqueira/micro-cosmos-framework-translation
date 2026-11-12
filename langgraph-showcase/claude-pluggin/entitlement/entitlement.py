"""Account entitlement for Micro-Focus runs.

The first 10 runs are free. After that, a monthly license at $10 allows
unlimited runs. The ledger is an account record. This module never lowers
free_runs_used.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

FREE_RUN_LIMIT = 10
MONTHLY_PRICE_USD = 10
PAYMENT_MESSAGE = (
    "Micro-Focus license required. The first 10 runs are free. "
    "A license is $10 a month for unlimited runs."
)


class EntitlementError(Exception):
    """The account cannot start another run."""


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def subscription_active(record: dict, now: datetime | None = None) -> bool:
    subscription = record.get("subscription")
    if not isinstance(subscription, dict):
        return False
    if subscription.get("status") != "active":
        return False
    renews_at = subscription.get("renews_at")
    if not isinstance(renews_at, str) or not renews_at:
        return False
    return _parse_time(renews_at) > _now(now)


def assess(record: dict, now: datetime | None = None) -> dict:
    used = int(record.get("free_runs_used") or 0)
    if used < 0:
        used = 0
    active = subscription_active(record, now)
    remaining = max(FREE_RUN_LIMIT - used, 0)
    if active:
        return {
            "allowed": True,
            "reason": "subscription",
            "free_runs_used": used,
            "remaining_free": remaining,
            "price_usd_per_month": MONTHLY_PRICE_USD,
            "message": "Monthly license active. Runs are unlimited.",
        }
    if used < FREE_RUN_LIMIT:
        return {
            "allowed": True,
            "reason": "free",
            "free_runs_used": used,
            "remaining_free": remaining,
            "price_usd_per_month": MONTHLY_PRICE_USD,
            "message": f"{remaining} free runs remaining.",
        }
    return {
        "allowed": False,
        "reason": "payment_required",
        "free_runs_used": used,
        "remaining_free": 0,
        "price_usd_per_month": MONTHLY_PRICE_USD,
        "message": PAYMENT_MESSAGE,
    }


def consume(record: dict, now: datetime | None = None) -> tuple[dict, dict]:
    before = assess(record, now)
    if not before["allowed"]:
        raise EntitlementError(before["message"])
    updated = deepcopy(record)
    if before["reason"] == "free":
        updated["free_runs_used"] = int(updated.get("free_runs_used") or 0) + 1
    remaining = max(FREE_RUN_LIMIT - int(updated.get("free_runs_used") or 0), 0)
    if before["reason"] == "subscription":
        message = "Monthly license active. This run is not counted against the free runs."
        remaining_free = max(FREE_RUN_LIMIT - int(updated.get("free_runs_used") or 0), 0)
    elif remaining:
        message = f"Free run counted. {remaining} free runs remaining."
        remaining_free = remaining
    else:
        message = (
            "Free run counted. No free runs remaining. "
            "A license is $10 a month for unlimited runs."
        )
        remaining_free = 0
    receipt = {
        "allowed": True,
        "reason": before["reason"],
        "free_runs_used": int(updated.get("free_runs_used") or 0),
        "remaining_free": remaining_free,
        "price_usd_per_month": MONTHLY_PRICE_USD,
        "message": message,
    }
    return updated, receipt


def empty_ledger(account_id: str) -> dict:
    return {"account_id": account_id, "free_runs_used": 0, "subscription": None}


def _load(path: Path, account_id: str | None) -> dict:
    if not path.exists():
        if not account_id:
            raise EntitlementError("Pass --account when the ledger does not exist yet.")
        return empty_ledger(account_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise EntitlementError("The ledger must be a JSON object.")
    if account_id and record.get("account_id") not in (None, "", account_id):
        raise EntitlementError("The ledger account does not match --account.")
    if account_id and not record.get("account_id"):
        record["account_id"] = account_id
    return record


def _print(payload: dict) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or consume a Micro-Focus run.")
    parser.add_argument("action", choices=("check", "consume"))
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--account", default="")
    args = parser.parse_args(argv)
    path = Path(args.ledger).expanduser()
    account_id = args.account or None
    try:
        if args.action == "check":
            if path.exists():
                record = json.loads(path.read_text(encoding="utf-8"))
            elif account_id:
                record = empty_ledger(account_id)
            else:
                raise EntitlementError("Pass --account when the ledger does not exist yet.")
            _print(assess(record))
            return 0
        record = _load(path, account_id)
        updated, receipt = consume(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
        _print(receipt)
        return 0
    except (EntitlementError, json.JSONDecodeError, OSError, ValueError) as exc:
        _print({"allowed": False, "message": str(exc), "price_usd_per_month": MONTHLY_PRICE_USD})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
