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

### Splat diff: "are these two Gaussian splats the same object?" (`06_splat_diff`, `splat_diff/`)
Jev can't read splats, but it does take images. The setup:
- `splat_diff/align.py` registers the two scans, solving for rotation, translation and scale.
- The browser renders 12 matched views of each scan.
- Jev answers 5 Nouls per view pair: same viewpoint, shape diff, part diff, color diff, and any diff.
- Code turns the answers into a verdict.

Test pairs come from `tools/make_variants.py`. It takes a real object scan (a Nike shoe and a plush moose on a sled) and produces a randomly re-posed and rescaled "re-capture", plus 4 edited versions. All 11 test pairs are summarized in [`sample_outputs/06_splat_diff.txt`](sample_outputs/06_splat_diff.txt).

| case | verdict | notes |
|---|---|---|
| same object, re-captured (3 runs) | **Same**, 3/3 | Every category stayed ≤ 0.19 in every run. No false alarms. |
| region recolored (2) | **Different**, 2/2 | Color 0.98. Per view it's very clean: 0.8–0.9 where the patch is visible, ~0.05 where it's hidden. |
| chunk cut off one end (2) | **Different**, 2/2 | Part 0.54–0.71. |
| extra lump stuck on (2) | 1 Different, 1 Uncertain | The plush lump is tiny and I can barely see it myself. |
| dent (2) | **Same**, 0/2 | Not Jev's fault, see the "dents" point below. |

What I learned:
- **Images work on `jev-latest`.** You need the `TypeSafe-Danger-Zone-Images: true` header. A 1024² image pair costs about 1.8k input tokens per request.
- **The artifact rules fought the real differences.** The v1 context listed "holes" and "floating blobs" as scan artifacts to ignore. Jev followed that, so a sawn-off heel (ragged, hollow edge) and an extra lump (looks like a floater) came back as Same or Uncertain. v2 separates artifacts from differences by **size and character** instead ("ragged edges don't make a missing chunk an artifact"). That raised part evidence from 0.22–0.60 to 0.54–0.71, kept same-object runs ≤ 0.19, and stopped the recolor from also triggering `part_diff` (0.79 → 0.16).
- **The "overall" Noul (`any_diff`) is more conservative than the specific ones.** The verdict uses all four categories, not just `any_diff`.
- **Dents are invisible in splat renders.** Splats have their color baked in and there's no relighting, so a dent that doesn't change the outline doesn't change the pixels. Fixing that needs a geometry-shaded render pass (normals or depth), or a code-side surface-distance check. The current `align.py` overlap metric is too coarse for small dents.
- **Separate captures need scale solved by fitting, not by spread.** Normalizing by median radius was off by 19% once one scan was missing a chunk. `align.py` now searches scale using the better of the two one-sided fits. All 10 real pairs align within ~2% of the true scale.
- **Thresholds:** the gap between same-object runs (≤ 0.19) and visible edits (≥ 0.54) is wide, so the defaults are Different ≥ 0.5 and Same ≤ 0.25 (Uncertain in between). Evidence is the 2nd-strongest view, so one noisy view can't flip the verdict. These were picked on the same 11 cases, so re-check them on real captures. The UI sliders re-score without new Jev calls.
- **Repeat runs agree within ±0.04**, so the margins above aren't noise.
- **Capture speed:** a background or automated Chrome tab throttles timers to ~1/s, and Spark's sorting rides on timers. That makes 12 views take ~2.5 min there, versus seconds in a focused tab.

## Takeaways for the hackathon

1. Ask several narrow questions per call rather than one broad one. It's the same cost in latency.
2. Always give a Choice a "none" or "unknown" option.
3. Use a Score for anything that has a degree, and a Noul only for real yes/no conditions.
4. Treat confidence below about 0.4 as "ask the user or a bigger model".
5. Keep thresholds and weights in code, and tune them on real examples.
