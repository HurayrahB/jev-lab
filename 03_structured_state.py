"""03 - Structured state: give Jev everything it needs to judge, as JSON.

State can be a string, a dict, or a list. A dict with named fields is usually best:
questions can then point at parts of it with backticked paths like `ticket.messages[0].text`.
Run:  python 03_structured_state.py
"""

from typesafe_sdk import Noul, Score

from jev import client, show

state = {
    "ticket": {
        "subject": "Duplicate charge",
        "messages": [
            {"from": "customer", "text": "I was charged twice for order A-104. Please refund the duplicate."},
            {"from": "support", "text": "We are checking the charges."},
        ],
    },
    "order": {
        "id": "A-104",
        "charges": [
            {"amount_usd": 49, "status": "captured"},
            {"amount_usd": 49, "status": "captured"},
        ],
    },
    "refund_policy": "Duplicate charges are eligible for a full refund of the duplicate.",
}

questions = {
    "asks_refund": Noul(instructions="In `ticket.messages`, does the customer ask for a refund?"),
    "charges_confirm_duplicate": Noul(
        instructions="Do the charges in `order.charges` show the customer was actually charged twice?"
    ),
    "policy_allows": Noul(instructions="Does `refund_policy` allow a refund in this situation?"),
    "support_progress": Score(
        instructions="How far has support gotten in resolving the ticket?",
        criteria=["No response yet", "Acknowledged but not resolved", "Fully resolved"],
    ),
}

with client() as c:
    r = c.system_one(state=state, questions=questions)

show(r)

# Jev gives judgments; YOUR CODE owns the decision. Keep policy explicit and tweakable.
p = {k: v.noul for k, v in r.nouls.items()}
if min(p["asks_refund"], p["charges_confirm_duplicate"], p["policy_allows"]) > 0.8:
    print("-> Auto-approve refund")
else:
    print("-> Send to a human")
