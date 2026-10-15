"""04 - Routing: turn free-form user text into a call to one of YOUR functions.

The pattern: one Choice picks the handler, and every branch's arguments are asked in
the SAME request (they run in parallel). Code then uses only the answers it needs.
This is how you'd build a natural-language command bar, a chatbot that does things, etc.
Run:  python 04_router.py
"""

from typesafe_sdk import Choice, Noul, Score

from jev import client

# --- your app's real functions ------------------------------------------------
def set_reminder(when: str, important: bool) -> None:
    print(f"   set_reminder(when={when!r}, important={important})")

def play_music(mood: str, energy: float) -> None:
    print(f"   play_music(mood={mood!r}, energy={energy:.1f})")

def search_notes() -> None:
    print("   search_notes()")


QUESTIONS = {
    "intent": Choice(
        instructions="Which action does the user want?",
        criteria={
            "reminder": "Set a reminder or alarm",
            "music": "Play music",
            "notes": "Look something up in their notes",
            "unknown": "None of the above",
        },
    ),
    # Speculative args: only consumed if that intent wins. State the premise explicitly.
    "reminder_when": Choice(
        instructions="If the user wants a reminder, when should it fire?",
        criteria={"tonight": None, "tomorrow": None, "next week": None, "unspecified": None},
    ),
    "reminder_important": Noul(instructions="If the user wants a reminder, did they say it's important?"),
    "music_mood": Choice(
        instructions="If the user wants music, what mood?",
        criteria={"focus": None, "chill": None, "party": None, "sad": None},
    ),
    "music_energy": Score(
        instructions="If the user wants music, how energetic should it be?",
        criteria=["very calm", "moderate", "high energy"],
    ),
}

requests = [
    "remind me tomorrow to submit the devpost, this is super important",
    "put on something to help me grind through this bug at 3am",
    "where did I write down the wifi password",
    "what's the capital of france",
]

with client() as c:
    for text in requests:
        r = c.system_one(state={"user_request": text}, questions=QUESTIONS)
        intent = r.choices["intent"]
        print(f"{text!r}\n   intent={intent.choice} (confidence {intent.confidence:.2f})")

        if intent.confidence < 0.4 or intent.choice == "unknown":
            print("   -> fallback: ask the user to rephrase / hand to an LLM")
        elif intent.choice == "reminder":
            set_reminder(r.choices["reminder_when"].choice, r.nouls["reminder_important"].noul > 0.5)
        elif intent.choice == "music":
            play_music(r.choices["music_mood"].choice, r.scores["music_energy"].score)
        elif intent.choice == "notes":
            search_notes()
        print()
