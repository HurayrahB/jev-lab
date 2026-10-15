"""01 - Your first Jev call.

One request = one STATE (the thing being judged) + a dict of QUESTIONS.
Every question gets a typed answer back. Run:  python 01_quickstart.py
"""

from typesafe_sdk import Choice, Noul, Score

from jev import client, show

state = "I was charged twice for my order last night. Please fix this ASAP or I'm cancelling."

questions = {
    # Noul = yes/no. Answer is P(yes), a float 0..1.
    "is_billing": Noul(instructions="Is this message about a billing problem?"),
    # Choice = pick exactly one option from a set. Values can be None or a description.
    "tone": Choice(
        instructions="What is the customer's tone?",
        criteria={"calm": None, "frustrated": None, "angry": None},
    ),
    # Score = position on an ORDERED list of levels (index 0, 1, 2...). Answer can land between levels.
    "urgency": Score(
        instructions="How urgently does this need a response?",
        criteria=["can wait a week", "should be handled this week", "needs a reply today"],
    ),
}

with client() as c:
    response = c.system_one(state=state, questions=questions)

# Read answers by the same key you used in `questions`:
print("billing?", response.nouls["is_billing"].noul)
print("tone:   ", response.choices["tone"].choice)
print("urgency:", response.scores["urgency"].score)
print()

# Or dump everything, including probabilities and confidence:
show(response)
