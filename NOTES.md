# Jev lab notes

What I found running small experiments against TypeSafe's Jev model (`jev-latest`) with the Python SDK (`pip install typesafe-sdk`, version 0.7.5). This file stands on its own: every experiment is described here, and no other files are needed. Docs: https://docs.typesafe.ai (index at https://docs.typesafe.ai/llms.txt).

## Jev in 30 seconds

Jev doesn't write text. You send it:
- **`state`**: the thing to judge. This can be a string, a JSON dict or list, or images.
- **`questions`**: named judgments about that state.

It returns typed probabilities, fast, and your code makes the decisions.

| Primitive | Use it for | You get back |
|---|---|---|
| `Noul(instructions=..., criteria={"true": ..., "false": ...})` | Is X true? | `.noul` = P(yes), 0..1 |
| `Choice(instructions=..., criteria={option: description})` | Pick one option from a set | `.choice`, `.probabilities`, `.confidence` |
| `Score(instructions=..., criteria=[lowest, ..., highest])` | A degree on ordered levels | `.score` (float index), `.probabilities`, `.confidence` |

- Question IDs (the dict keys) are never sent to the model, so the instructions must carry the full meaning.
- To refer to part of a dict state, use backticks, e.g. `` `order.charges` ``.
- All questions in one request run in parallel and can't see each other's answers.
- Read the answers with `response.nouls[id].noul`, `response.choices[id]` and `response.scores[id]`.

## Setup gotchas

- **The model name is `jev-latest`, not `jev`.** The SDK usage docs show `TypeSafeClient(model="jev")`, but the API returned `400 Unknown model: jev`. Run `TypeSafeClient().models.list()` to see what your key can use. Mine returned `jev-latest` and `jev-preview`.
- The SDK reads `TYPESAFE_API_KEY` from the environment. Loading it from a `.env` file with `python-dotenv`, and failing early with a clear message when it's missing, saves confusion.
- An invalid key raises `TypeSafeAuthenticationError` (401), and a bad request raises `TypeSafeBadRequestError` (400). Both are importable from `typesafe_sdk`, and `TypeSafeError` is the base class.
- Use `TypeSafeClient` (sync, `with ... as c`) or `AsyncTypeSafeClient` (`async with ... as c`, then `await c.system_one(...)`). The call is `c.system_one(state=..., questions=..., extra_headers=...)`.

## Observations

### Confidence really does flag the genuinely ambiguous cases
A first test asked a Choice for the tone of a support message, plus an urgency Score and a "billing?" Noul. *"charged twice... fix this ASAP or I'm cancelling"* came back with these tones:

| run | frustrated | angry | confidence |
|---|---|---|---|
| 1 | 0.57 | 0.43 | 0.35 |
| 2 | 0.53 | 0.47 | 0.30 |

Honestly, I'd argue about that one myself. Meanwhile, on the same message, urgency scored 1.00 for "needs a reply today", and billing scored P = 0.99. **Low confidence matched the case where a human would hesitate too**, which is exactly what you want for deciding when to escalate.

Small run-to-run differences in the probabilities (about ±0.04 here) mean thresholds need a margin. Don't build logic that flips at exactly 0.5.

### A Noul is not a sentiment score
A phone review praised the battery but complained about the camera and support. Several Nouls and a satisfaction Score were asked about it. The results:
- `mentions_battery` and `mentions_support` were both 1.00. These are factual, so they're near-certain.
- `would_recommend` was 0.24, a real judgment that leaned no.
- The `satisfaction` Score landed at 0.99 on a 0–2 scale ("mixed") with 0.98 confidence.

Asking "how satisfied?" as a Noul would have collapsed "mixed" into a meaningless ~0.5. The Score captured it exactly.

### Descriptions on Choice options matter
With option descriptions plus a `"none"` escape hatch, `biggest_complaint` picked `camera` (0.88), and `support` came second (0.12). That's the right ranking, since the camera complaint was the stronger one.

### Combining judgments in code works well
With a JSON state (a customer message, an order's charges and a refund policy), three independent Nouls asked whether the customer asked for a refund, whether the charges were actually duplicated, and whether the policy allows it. All three came back at 0.97 or higher. The auto-approve rule `min(...) > 0.8` lives in Python, so I can change policy without touching the questions.

### Routing with speculative arguments is fast and clean
A command router asks a Choice for the intent (reminder, music, notes or unknown), plus every branch's arguments as extra questions, all in **one request**. Code then uses only the answers for the chosen branch:

| input | intent (conf.) | args |
|---|---|---|
| "remind me tomorrow to submit the devpost, this is super important" | reminder (1.00) | `tomorrow`, important = True |
| "put on something to help me grind through this bug at 3am" | music (0.95) | `focus`, energy 1.5 / 2 |
| "where did I write down the wifi password" | notes (0.97) | — |
| "what's the capital of france" | unknown (1.00) | falls back |

The `"unknown"` option stopped off-topic requests from getting forced into a handler.

### Multi-dimension ranking
Five hackathon ideas were each scored (Score) on impact and feasibility. Weighted in code, the result was then gated on a `fits_goal` Noul. All 5 requests run concurrently with `asyncio.gather`. The ranking is sensible: the food-bank matcher came first and the from-scratch Rust kernel last. The joke Discord bot scored high on feasibility (0.97) but was correctly sunk by low impact. Weights live in a dict, so re-ranking costs no API calls.

## Guide: building an image-comparison check with Jev

Written for someone starting from zero (a person or a fresh Claude instance). It covers everything you need to build a "do these two images show a real physical difference?" check on Jev.

### Where the numbers come from

The task was comparing two Gaussian splat scans (3D captures) of objects that are supposed to be identical, and asking "is there a real difference?". Jev can't read 3D files, so the pipeline was:
1. **Align.** Put the two scans in the same pose and scale. Separate captures differ in position, rotation and scale, so all three were solved by fitting the splat centers. Normalizing by the cloud's spread was off by 19% once one scan was missing a chunk.
2. **Render.** Make 12 matched views of each scan from identical cameras.
3. **Ask Jev.** One request per image pair.
4. **Decide in code.** Combine the per-view answers into a verdict.

**Test data:**
- Two real object scans: a running shoe, and a plush moose on a wooden sled.
- From each scan, 5 labelled variants. Every variant was moved to a random pose and scale, as if captured separately:
  - **same:** 10% of splats dropped and slight color noise, as a negative control.
  - **recolor:** one region's color changed.
  - **missing part:** a chunk cut off one end.
  - **extra part:** a copied lump added.
  - **dent:** surface pushed in.
- That makes 11 labelled pairs (one "same" control was run twice) × 12 views = **132 image pairs**. They were scored with two question wordings, and the final wording was run twice.

Only the Jev part matters for reuse. Any source of matched image pairs works: photos, renders or screenshots.

### 1. Sending images to Jev (verified with `typesafe-sdk` 0.7.5)

- **Model:** `jev-latest` (gave `jev-1.13.0`) accepts images. `jev-preview` (`jev-1.14.0`) does too. Plain `jev` fails with `400 Unknown model`.
- **Header:** images are opt-in. Send `TypeSafe-Danger-Zone-Images: true` with **every** request that contains an image. The docs call image support pre-production.
- **Formats and limits** (from the docs):
  - PNG or JPEG stills only.
  - Each side 280–1568 px, total 78,400–2,458,624 px, max 16 MiB per image, max 32 MiB per request.
  - Images outside the limits are **rejected, not resized**, and one bad image fails the whole request.
  - EXIF orientation is ignored, so rotate the pixels upright yourself.
- **Where images go:** put them in `state` as named fields and refer to them in questions with backticks, e.g. `` `model_a` ``. Images can also go in instructions or criteria, but use `state` when several questions need the same image.
- **SDK call shape:**
  ```python
  from typesafe_sdk import AsyncTypeSafeClient, Image, Noul
  async with AsyncTypeSafeClient(model="jev-latest") as c:
      r = await c.system_one(
          state={"context": "...", "view": "front, 10° above", "model_a": Image(png_bytes_a), "model_b": Image(png_bytes_b)},
          questions={"color_diff": Noul(instructions="...", criteria={"true": "...", "false": "..."})},
          extra_headers={"TypeSafe-Danger-Zone-Images": "true"},
      )
  r.nouls["color_diff"].noul   # P(yes), 0..1
  r.model, r.usage            # e.g. "jev-1.13.0", input_tokens≈1.8k
  ```
  - `Image(...)` accepts raw bytes or a `pathlib.Path`.
  - The SDK sends images as multipart automatically.
  - The API key comes from the `TYPESAFE_API_KEY` env var.
  - Errors are importable from `typesafe_sdk`: `TypeSafeError` is the base class, plus `TypeSafeBadRequestError` and `TypeSafeAuthenticationError`.
- **Cost and speed:** two 1024×1024 PNGs plus about 5 Nouls came to about 1.8k input tokens and roughly 1 s per request.
  - Send one request per image pair, all concurrently with `asyncio.gather`. 12 pairs finish in about the time of one.
  - The Nouls inside one request run in parallel and can't see each other's answers.
- **Smoke test first:** two synthetic PNGs (a mug with and without a handle) gave 0.99 for "part differs". The identical pair gave 0.01. Do this before building anything else.

### 2. Preparing the images (whatever produces them)

- **Pairs must be truly matched.** Same viewpoint, same framing and scale, same background. Jev compares what it sees, so misalignment reads as a difference.
- **Use a neutral, uniform background.** Mid-grey worked. Crop away anything that isn't the object.
- **Make the object fill about 85% of the frame.** Early renders where the object filled about a third worked, but they waste resolution.
- **Use several views per object** (12 here: 8 around at 10° elevation, plus 4 at 40°). Any one difference is only visible from some sides. In the recolor case the changed views scored 0.76–0.90 and the views where the patch was hidden scored 0.04–0.06.
- **Give each view a label** in `state` (e.g. `"front-left (azimuth 315°), 40° above"`). It's cheap context.
- **Know what pixels can't show.** In splat renders (color baked in, no relighting), a dent that doesn't change the silhouette is invisible: 0/2 detected. Jev can't judge what isn't in the image. Catch these with geometry in code, or with a shaded/normal render.

### 3. The questions (the v2 wording, which is the current default)

The structure is 5 Nouls per image pair: one alignment gate plus four difference categories. Phrase them so a high value means yes.

Use this context string in `state["context"]`. It's written for 3D-scan renders. For other sources (e.g. photos), keep the structure: what the two images are, which artifacts to ignore (described by size and character), and which differences count even when they look messy. Then swap in the artifacts typical of your source.
> `model_a` and `model_b` are renders of two separate 3D scans (Gaussian splats) of physical objects that are supposed to be identical. The scans were aligned and rendered from the same camera position. Decide whether the physical objects differ. Ignore scan artifacts: soft, blurry or fuzzy edges; faint speckle, thin wisps and small scattered floaters; tiny pinholes; slightly smeared texture; lighting, exposure, white balance and reflections. These ARE real differences, even when their edges look ragged or blurry: a sizeable part or chunk of the object that is present in one and missing in the other (the outline differs); a solid lump, part or object attached to or right next to the object in only one of them; a dent, bulge or bend; a region with a different color, pattern or material.

| id | instructions | criteria `true` / `false` |
|---|---|---|
| `viewpoint_match` | Do `model_a` and `model_b` show the object from the same viewpoint, in the same orientation and at a similar size? | Same side faces the camera, same rotation, small offsets fine / different side, rotated, mirrored, upside down, or no object |
| `shape_diff` | Is the surface shape different between `model_a` and `model_b`: a dent, bulge, bend, warp or different proportions of the same parts? | Some surface is pushed in, pushed out or bent differently / same surface shape apart from scan artifacts |
| `part_diff` | Is a sizeable piece of the object present in one of `model_a` / `model_b` and missing in the other, or is there an extra solid lump or part in only one of them? | Outline differs because a chunk/part/attachment is missing or added, even if edges look ragged / same pieces and outline; at most fuzz, wisps, speckle or pinholes. **A color change alone is not a missing or extra part.** |
| `color_diff` | Does some region of the object have a different color, pattern or material in `model_a` versus `model_b`? | A region is clearly a different color, pattern, marking or material / same colors; at most an overall brightness, tint or exposure shift, or blur |
| `any_diff` | Is there any real physical difference between the object in `model_a` and the object in `model_b`? | At least one sizeable missing or extra piece, shape change, or color/material change / only scan artifacts differ |

**Why it's worded this way** (each point came from a failure):
- **v1 listed artifacts by type.** It said "holes" and "floating blobs" were artifacts. Jev obeyed that, so a sawn-off heel (ragged, hollow edge) scored part 0.37 and an extra lump (looks like a floater) scored 0.23, both missed.
  - v2 describes artifacts by **size and character** (small, faint, thin, scattered) and says explicitly that ragged edges don't make a missing chunk an artifact.
  - That moved real part differences to 0.54–0.71, while same-object pairs stayed ≤ 0.19.
- **Without the "a color change alone is not a missing part" line, categories cross-talk.** Under v1 a recolor also triggered `part_diff` at 0.79; under v2 it dropped to 0.16.
- **The overall question (`any_diff`) is consistently more cautious** than the specific ones: 0.48–0.65 where a specific category was 0.6–0.7. Don't build the verdict on `any_diff` alone; use the specific categories.
- **`viewpoint_match` is a cheap safety net.** It was 0.98–0.99 on the aligned views I inspected, and no aligned view was ever dropped by it. It's there to catch broken alignment before it turns into false "differences". Its behaviour on genuinely misaligned pairs is untested.

### 4. The decision rule (pure code; Jev only supplies probabilities)

1. **Drop misaligned views:** any view with `viewpoint_match` < 0.5. If fewer than 6 usable views remain → **"alignment failed"**, no verdict.
2. **Score each category** (shape, part, color, any): take the **2nd-highest** value across the usable views. A real difference shows from at least 2 neighbouring views, so one noisy view can't flip the result. With "support = 1", a single 0.95 view out of 12 would flip the verdict.
3. **Verdict:**
   - **Different** if any category score ≥ 0.5. Report which categories and which views.
   - **Same** if every category score ≤ 0.25.
   - Otherwise **Uncertain** → send to a person.
4. **Keep the raw per-view answers.** Changing thresholds is then free, with no new Jev calls. Save the image pairs and answers per run so you can re-judge with new wording later.

**Why these thresholds:**
- Same-object pairs never scored above 0.19 on any category.
- Every *visible* edit scored ≥ 0.54.
- The first default (Different ≥ 0.75) turned real differences into "Uncertain"; 0.5 sits in the middle of the gap.
- **These were tuned on the same 11 cases they're evaluated on**, so re-check them on real data.

### 5. Measured results (v2 wording, the rule above)

| case | verdict | category scores (2nd-strongest view) |
|---|---|---|
| same object, re-captured (3) | Same 3/3 | all ≤ 0.19 |
| region recolored (2) | Different 2/2 | color 0.98, any 0.95 |
| chunk cut off one end (2) | Different 2/2 | part 0.54–0.71 |
| extra lump (2) | 1 Different (part 0.70), 1 Uncertain (0.40) | the Uncertain lump is barely visible to a human too |
| dent (2) | missed, "Same" | invisible in the images (see §2) |

- Overall 8/11 correct, with **zero false "Different"**. The misses are the invisible case plus one Uncertain.
- **Repeats agree within ±0.04** (v2 was run twice on all 132 pairs).

### 6. Pitfalls and open risks

- **Check your test data with your own eyes first.** Two early "misses" were bad test cases, not model errors:
  - A deleted surface patch just looked like a scan hole.
  - A detached blob looked like a floater.
  - Put each pair on a contact sheet with its scores (all views, A next to B) before blaming Jev.
- **Low-quality scans are untested.** Expected failure modes:
  - **Unscanned regions read as missing parts.** v2 deliberately treats ragged missing chunks as real, so a scan that never covered one side will look like a missing part, in neighbouring views too.
  - **Baked-in shadows or glare** from different capture lighting can look like local color changes.
  - **Blur hides small differences.**
  - **Untested idea:** add a per-view Noul ("is either image too incomplete or blurry to compare?") and drop failing views, the same way `viewpoint_match` is used.
- **"Same" was tested only on synthetic re-captures:** the same scan, re-posed, with 10% of splats dropped and slight color jitter. Two genuinely separate captures of one object will be noisier. Test that before trusting the Same side.
- **Noul ≈ 0.5 means "unsure", not "half different".** Use a Score if you need a degree of difference.
- **`Box` (locating things in an image) exists but wasn't tried.** It could highlight *where* the difference is. The SDK docstring hints that it may need `jev-preview`.

### 7. How to evaluate a new version quickly

- Keep a folder of labelled pairs, each with its expected answer.
- Re-run all of them concurrently and print one line per pair: expected, verdict, and the four category scores.
- When changing wording, run old and new prompts on the **same saved images** and compare (that's how v1 → v2 was decided, in minutes).
- Look at per-view scores next to the images for every miss: missing evidence, a bad test case, or a wording problem.

## Takeaways for the hackathon

1. Ask several narrow questions per call rather than one broad one. It's the same cost in latency.
2. Always give a Choice a "none" or "unknown" option.
3. Use a Score for anything that has a degree, and a Noul only for real yes/no conditions.
4. Treat confidence below about 0.4 as "ask the user or a bigger model".
5. Keep thresholds and weights in code, and tune them on real examples.
