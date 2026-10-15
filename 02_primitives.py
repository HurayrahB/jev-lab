"""02 - The three primitives in depth, and how to write good questions.

Run:  python 02_primitives.py
"""

from typesafe_sdk import Choice, Noul, Score

from jev import client, show

review = (
    "Battery life is incredible, easily two days. The camera is fine in daylight "
    "but useless at night. Customer service never answered my email."
)

questions = {
    # --- NOUL: one yes/no condition -------------------------------------------
    # Use one Noul per label when several can be true at once (multi-label tagging).
    # 0.5 means "can't tell", NOT "medium". For degrees, use Score.
    "mentions_battery": Noul(instructions="Does the review mention battery life?"),
    "mentions_support": Noul(instructions="Does the review mention customer service?"),
    "would_recommend": Noul(
        instructions="Would this reviewer recommend the product to a friend?",
    ),
    # --- CHOICE: exactly one of a set -------------------------------------------
    # Give options descriptions when the label alone is ambiguous.
    # Include a "none / other" option when nothing might fit, or Jev is forced to pick.
    "biggest_complaint": Choice(
        instructions="What is the reviewer's single biggest complaint?",
        criteria={
            "battery": "Battery life or charging",
            "camera": "Photo or video quality",
            "support": "Customer service or support experience",
            "price": "Cost or value for money",
            "none": "The review contains no complaint",
        },
    ),
    # --- SCORE: a degree on ordered levels --------------------------------------
    # Levels go low -> high. Make each level a concrete, self-contained description.
    "satisfaction": Score(
        instructions="Overall, how satisfied is the reviewer with the product?",
        criteria=[
            "Very unhappy; regrets the purchase",
            "Mixed; real positives and real negatives",
            "Happy; minor gripes at most",
        ],
    ),
}

with client() as c:
    r = c.system_one(state=review, questions=questions)

show(r)

# Confidence (Choice/Score) = how concentrated the probabilities are, 0..1.
# Use it to decide when to trust an answer vs. ask a human / show "unsure".
complaint = r.choices["biggest_complaint"]
if complaint.confidence < 0.5:
    print(f"Unsure between: {sorted(complaint.probabilities, key=complaint.probabilities.get)[-2:]}")
else:
    print(f"Biggest complaint: {complaint.choice}")
