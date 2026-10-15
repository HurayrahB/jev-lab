"""Playground - edit STATE and QUESTIONS, then run:  python playground.py"""

from typesafe_sdk import Choice, Noul, Score

from jev import client, show

STATE = "Paste or build whatever you want Jev to judge here."

QUESTIONS = {
    "my_noul": Noul(instructions="Is this a placeholder?"),
    "my_choice": Choice(instructions="What kind of text is this?", criteria={"instructions": None, "story": None, "other": None}),
    "my_score": Score(instructions="How finished does this text feel?", criteria=["draft", "rough", "polished"]),
}

with client() as c:
    show(c.system_one(state=STATE, questions=QUESTIONS))
