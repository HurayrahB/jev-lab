# Jev Lab: learning TypeSafe's System One model

A hands-on set of experiments for **[Jev](https://docs.typesafe.ai/)**, TypeSafe's System One model, built to get hackathon-ready. Each script isolates one concept, runs against the live API, and its real output is saved in [`sample_outputs/`](sample_outputs/). Findings and gotchas are written up in **[NOTES.md](NOTES.md)**.

```
$ python 04_router.py
'remind me tomorrow to submit the devpost, this is super important'
   intent=reminder (confidence 1.00)
   set_reminder(when='tomorrow', important=True)

"what's the capital of france"
   intent=unknown (confidence 1.00)
   -> fallback: ask the user to rephrase / hand to an LLM
```

## What Jev is (30-second version)

Jev is **not a chatbot**. It doesn't write text. You give it:

- **state**: the thing to judge (a string, or a JSON dict or list), and
- **questions**: named judgments you want made about it.

It returns **typed answers with probabilities**, fast. Your code makes the decisions.

| Primitive | Use it for | You get back |
|---|---|---|
| `Noul(instructions=...)` | yes or no: "is X true?" | `.noul` = P(yes), 0..1 |
| `Choice(instructions=..., criteria={opt: desc})` | pick exactly one option from a set | `.choice`, `.probabilities`, `.confidence` |
| `Score(instructions=..., criteria=[low, ..., high])` | a degree on ordered levels | `.score` (a float index, which can fall between levels), `.legend`, `.probabilities`, `.confidence` |

```python
from typesafe_sdk import Choice, Noul, Score
from jev import client

with client() as c:
    r = c.system_one(
        state="I was charged twice, fix it ASAP!",
        questions={
            "billing": Noul(instructions="Is this about billing?"),
            "tone": Choice(instructions="Tone?", criteria={"calm": None, "angry": None}),
            "urgency": Score(instructions="How urgent?", criteria=["low", "medium", "high"]),
        },
    )
r.nouls["billing"].noul      # 0.97
r.choices["tone"].choice     # "angry"
r.scores["urgency"].score    # 1.8
```

## Setup (one time)

```bash
git clone https://github.com/HurayrahB/jev-lab.git
cd jev-lab
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
python 01_quickstart.py
```

Paste your own key (from https://console.typesafe.ai/) into `.env`.

> **Gotcha:** the model id is `jev-latest` (or `jev-preview`), not `jev`. See [NOTES.md](NOTES.md#setup-gotchas).

Run the offline tests (no API key needed) with `python -m pytest`.

## Project layout

```
jev.py               shared client setup and the show() pretty-printer
01..05_*.py          experiments, each one isolating a single concept
playground.py        scratch file
sample_outputs/      real responses captured from jev-latest
tests/               offline pytest suite for the helpers
NOTES.md             findings, gotchas and takeaways
```

## Work through these in order

| File | Teaches |
|---|---|
| `01_quickstart.py` | One request with all three primitives, and how to read the answers |
| `02_primitives.py` | Writing good questions: option descriptions, a "none" option, multi-label Nouls, confidence |
| `03_structured_state.py` | JSON state, pointing at fields with backticks, and keeping the final decision in your code |
| `04_router.py` | Natural language mapped to *your* functions plus their arguments, with a low-confidence fallback |
| `05_rank_async.py` | Scoring many items in parallel, then weighting and ranking them in code |
| `playground.py` | Blank slate for trying your own ideas |

`jev.py` holds the shared helpers: `client()`, `async_client()` and `show(response)`. `show()` pretty-prints every answer with probability bars.

## Rules of thumb

1. **One narrow judgment per question.** "Is it urgent and about billing?" should be two questions.
2. **Batch questions about the same state into one call.** They run in parallel and can't see each other's answers.
3. **Questions are self-contained.** The dict keys (`"tone"`) are *never* sent to Jev, so put the full meaning in `instructions`.
4. **Include a "none" or "other" option** in a Choice when nothing might fit. Otherwise Jev is forced to pick something.
5. **A Noul of 0.5 means "unsure", not "medium".** For a degree, use a Score.
6. **Score levels go low to high,** and each one should describe a concrete situation.
7. **Let code own the logic.** Jev supplies the judgments, and your thresholds and weights decide what to do with them. Tune the thresholds on real examples.
8. **Use confidence** to decide when to fall back to a human, an LLM, or an "are you sure?" prompt.
9. **Keep the API key server-side.** In a web app, call Jev from your backend, never from the browser.

## Hackathon patterns worth stealing

- **Command bar or agent actions:** a Choice picks the function and other questions fill in its arguments (see `04_router.py`).
- **Moderation and triage:** one Noul per rule, plus a Score for severity.
- **Ranking and recommendation:** Score each item on several dimensions, and let users drag the weight sliders (see `05_rank_async.py`).
- **Verification:** "Does `source` support `claim`?" as a Noul, with escalation when it's unclear.
- **Reranking search or RAG results:** Score each retrieved chunk's relevance to the query.

## Docs

- Concepts: https://docs.typesafe.ai/concepts/how-to-build-with-system-one
- Python SDK: https://docs.typesafe.ai/sdk/python
- Cookbooks (function calling, reranking, citation checks...): https://docs.typesafe.ai/llms.txt
- Try questions in the browser: https://console.typesafe.ai/
