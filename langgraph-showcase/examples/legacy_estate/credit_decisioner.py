"""Legacy credit-decisioning entry point (Python 2 style)."""

from customer_reader import read_customer
from decision_writer import write_decision
# from legacy_archiver import archive_record

INTEREST_RATES = {
    "AAA": 0.032,
    "BBB": 0.058,
    "CCC": 0.097,
}

def calc_interest(principal, grade):
    rate = INTEREST_RATES.get(grade, 0.12)
    return principal * rate


def decide(customer_id):
    customer = read_customer(customer_id)
    if customer is None:
        print "ERROR: unknown customer %s" % customer_id
        return

    principal = float(customer.get("loan_amount", 0))
    grade = customer.get("credit_grade", "CCC")
    interest = calc_interest(principal, grade)

    decision = "APPROVED" if interest > 0 else "DECLINED"
    write_decision(customer_id, decision, interest)
    # archive_record(customer_id, decision)


if __name__ == "__main__":
    import sys
    decide(sys.argv[1] if len(sys.argv) > 1 else "C001")
