# Lab notes

What I found running these experiments against `jev-latest`. Raw outputs are in [`sample_outputs/`](sample_outputs/).

## Setup gotchas

- **The model name is `jev-latest`, not `jev`.** The SDK usage docs show `TypeSafeClient(model="jev")`, but the API returned `400 Unknown model: jev`. Run `TypeSafeClient().models.list()` to see what your key can use. Mine returned `jev-latest` and `jev-preview`.
- The SDK reads `TYPESAFE_API_KEY` from the environment. I load it from `.env` with `python-dotenv` and fail early with a friendly message when it's missing (see `jev.py`).
- An invalid key raises `TypeSafeAuthenticationError` (401), and a bad request raises `TypeSafeBadRequestError` (400). Both are importable from `typesafe_sdk`.

## Observations

### Confidence really does flag the genuinely ambiguous cases
In `01_quickstart`, *"charged twice... fix this ASAP or I'm cancelling"* came back with these tones:

| run | frustrated | angry | confidence |
|---|---|---|---|
| 1 | 0.57 | 0.43 | 0.35 |
| 2 | 0.53 | 0.47 | 0.30 |

Honestly, I'd argue about that one myself. Meanwhile, on the same message, urgency scored 1.00 for "needs a reply today", and billing scored P = 0.99. **Low confidence matched the case where a human would hesitate too**, which is exactly what you want for deciding when to escalate.

Small run-to-run differences in the probabilities (about ±0.04 here) mean thresholds need a margin. Don't build logic that flips at exactly 0.5.

### A Noul is not a sentiment score
In `02_primitives`, the review praised the battery but complained about the camera and support. The results:
- `mentions_battery` and `mentions_support` were both 1.00. These are factual, so they're near-certain.
- `would_recommend` was 0.24, a real judgment that leaned no.
- The `satisfaction` Score landed at 0.99 on a 0–2 scale ("mixed") with 0.98 confidence.

Asking "how satisfied?" as a Noul would have collapsed "mixed" into a meaningless ~0.5. The Score captured it exactly.

### Descriptions on Choice options matter
With option descriptions plus a `"none"` escape hatch, `biggest_complaint` picked `camera` (0.88), and `support` came second (0.12). That's the right ranking, since the camera complaint was the stronger one.

### Combining judgments in code works well
In `03_structured_state`, three independent Nouls (customer asked for a refund, charges actually duplicated, policy allows it) all came back at 0.97 or higher. The auto-approve rule `min(...) > 0.8` lives in Python, so I can change policy without touching the questions.

### Routing with speculative arguments is fast and clean
`04_router` asks the intent plus every branch's arguments in **one request**:

| input | intent (conf.) | args |
|---|---|---|
| "remind me tomorrow to submit the devpost, this is super important" | reminder (1.00) | `tomorrow`, important = True |
| "put on something to help me grind through this bug at 3am" | music (0.95) | `focus`, energy 1.5 / 2 |
| "where did I write down the wifi password" | notes (0.97) | — |
| "what's the capital of france" | unknown (1.00) | falls back |

The `"unknown"` option stopped off-topic requests from getting forced into a handler.

### Multi-dimension ranking
`05_rank_async` scores 5 hackathon ideas on impact and feasibility, then gates the result on a `fits_goal` Noul. All 5 requests run concurrently with `asyncio.gather`. The ranking is sensible: the food-bank matcher came first and the from-scratch Rust kernel last. The joke Discord bot scored high on feasibility (0.97) but was correctly sunk by low impact. Weights live in a dict, so re-ranking costs no API calls.

## Takeaways for the hackathon

1. Ask several narrow questions per call rather than one broad one. It's the same cost in latency.
2. Always give a Choice a "none" or "unknown" option.
3. Use a Score for anything that has a degree, and a Noul only for real yes/no conditions.
4. Treat confidence below about 0.4 as "ask the user or a bigger model".
5. Keep thresholds and weights in code, and tune them on real examples.
