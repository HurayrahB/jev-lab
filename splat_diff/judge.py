"""Ask Jev whether two aligned renders show a physically different object, and turn many views into a verdict.

One request per view (model_a + model_b images in state), all views in parallel.
The verdict logic lives in `aggregate()`: plain Python, so thresholds can change without new API calls.
"""

from __future__ import annotations

import asyncio

from typesafe_sdk import Image, Noul

IMAGES_HEADER = {"TypeSafe-Danger-Zone-Images": "true"}  # images are opt-in (pre-production) per the docs

CONTEXT = (
    "`model_a` and `model_b` are renders of two separate 3D scans (Gaussian splats) of physical objects "
    "that are supposed to be identical. The scans were aligned and rendered from the same camera position. "
    "Scanning is imperfect: blur, soft or fuzzy edges, speckles, floating blobs, small holes, missing thin "
    "detail, smeared texture, lighting, exposure, white balance, reflections and leftover background are scan "
    "artifacts and are NOT real differences. Only differences in the physical object itself matter."
)

ARTIFACTS = "Differences explained by scan artifacts (blur, noise, holes, floaters, lighting, background) only."

QUESTIONS = {
    "viewpoint_match": Noul(
        instructions="Do `model_a` and `model_b` show the object from the same viewpoint, in the same orientation and at a similar size?",
        criteria={
            "true": "Same side of the object is facing the camera, same rotation; small offsets are fine.",
            "false": "The object is seen from a different side, rotated, mirrored or upside down, or one image shows no object.",
        },
    ),
    "shape_diff": Noul(
        instructions="Is the physical shape of the object different between `model_a` and `model_b`, such as a dent, bend, break, warp or different proportions?",
        criteria={"true": "The object's geometry clearly differs.", "false": "Same shape. " + ARTIFACTS},
    ),
    "part_diff": Noul(
        instructions="Is a physical part, component, attachment or object feature present in one of `model_a` / `model_b` but absent in the other?",
        criteria={
            "true": "A part that is clearly part of the object is missing or added (e.g. a handle, knob, label, cable, lid).",
            "false": "The same parts are present. " + ARTIFACTS,
        },
    ),
    "color_diff": Noul(
        instructions="Is the actual color, pattern or surface material of the object different between `model_a` and `model_b`?",
        criteria={
            "true": "A region of the object has a different paint, color, pattern, marking or material.",
            "false": "Same colors and materials; at most an overall brightness, tint or exposure shift. " + ARTIFACTS,
        },
    ),
    "any_diff": Noul(
        instructions="Taking scan artifacts into account, are `model_a` and `model_b` physically different objects (or the same object in a different physical state)?",
        criteria={
            "true": "There is at least one real physical difference in the object.",
            "false": "They look like two imperfect scans of the very same physical object.",
        },
    ),
}

# v2: v1 listed "holes" and "floating blobs" as artifacts, and Jev (reasonably) excused a sawn-off heel and
# an extra lump as scan noise. v2 separates artifacts from differences by size and character instead.
CONTEXT_V2 = (
    "`model_a` and `model_b` are renders of two separate 3D scans (Gaussian splats) of physical objects "
    "that are supposed to be identical. The scans were aligned and rendered from the same camera position. "
    "Decide whether the physical objects differ. "
    "Ignore scan artifacts: soft, blurry or fuzzy edges; faint speckle, thin wisps and small scattered "
    "floaters; tiny pinholes; slightly smeared texture; lighting, exposure, white balance and reflections. "
    "These ARE real differences, even when their edges look ragged or blurry: a sizeable part or chunk of the "
    "object that is present in one and missing in the other (the outline differs); a solid lump, part or "
    "object attached to or right next to the object in only one of them; a dent, bulge or bend; a region "
    "with a different color, pattern or material."
)

QUESTIONS_V2 = {
    "viewpoint_match": QUESTIONS["viewpoint_match"],
    "shape_diff": Noul(
        instructions="Is the surface shape different between `model_a` and `model_b`: a dent, bulge, bend, warp or different proportions of the same parts?",
        criteria={"true": "Some surface is pushed in, pushed out or bent differently.", "false": "Same surface shape, apart from scan artifacts."},
    ),
    "part_diff": Noul(
        instructions="Is a sizeable piece of the object present in one of `model_a` / `model_b` and missing in the other, or is there an extra solid lump or part in only one of them?",
        criteria={
            "true": "The outline differs because a chunk, part or attachment is missing or added, even if its edges look ragged.",
            "false": "Same pieces and outline; at most fuzz, wisps, speckle or pinholes. A color change alone is not a missing or extra part.",
        },
    ),
    "color_diff": Noul(
        instructions="Does some region of the object have a different color, pattern or material in `model_a` versus `model_b`?",
        criteria={
            "true": "A region is clearly a different color, pattern, marking or material.",
            "false": "Same colors; at most an overall brightness, tint or exposure shift, or blur.",
        },
    ),
    "any_diff": Noul(
        instructions="Is there any real physical difference between the object in `model_a` and the object in `model_b`?",
        criteria={
            "true": "At least one sizeable missing or extra piece, shape change, or color/material change.",
            "false": "Only scan artifacts differ: fuzz, wisps, speckle, pinholes, lighting.",
        },
    ),
}

PROMPTS = {"v1": (CONTEXT, QUESTIONS), "v2": (CONTEXT_V2, QUESTIONS_V2)}
DEFAULT_PROMPT = "v2"

CATEGORIES = ["shape_diff", "part_diff", "color_diff", "any_diff"]

DEFAULT_THRESHOLDS = {
    "viewpoint_min": 0.5,  # views below this are treated as misaligned and ignored
    "min_views": 6,  # fewer usable views than this -> no verdict
    "different": 0.5,  # category evidence at or above -> Different (same-object runs stayed <= 0.17, visible edits >= 0.66)
    "same": 0.25,  # every category at or below -> Same
    "support": 2,  # a difference must show up in this many views (2nd-highest value is used)
}


async def judge_view(client, label: str, png_a: bytes, png_b: bytes, prompt: str = DEFAULT_PROMPT) -> dict:
    context, questions = PROMPTS[prompt]
    r = await client.system_one(
        state={"context": context, "view": label, "model_a": Image(png_a), "model_b": Image(png_b)},
        questions=questions,
        extra_headers=IMAGES_HEADER,
    )
    return {"view": label, "model": r.model, "prompt": prompt, **{k: a.noul for k, a in r.nouls.items()}}


async def judge_views(client, views: list[tuple[str, bytes, bytes]], prompt: str = DEFAULT_PROMPT) -> list[dict]:
    return list(await asyncio.gather(*(judge_view(client, *v, prompt=prompt) for v in views)))


def aggregate(views: list[dict], thresholds: dict | None = None) -> dict:
    """Combine per-view Nouls into Same / Different / Uncertain / Alignment failed."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    usable = [v for v in views if v["viewpoint_match"] >= th["viewpoint_min"]]
    if len(usable) < th["min_views"]:
        return {
            "verdict": "alignment_failed",
            "usable_views": len(usable),
            "categories": {},
            "reason": f"Only {len(usable)} of {len(views)} views looked aligned; fix the orientation and retry.",
        }

    support = int(th["support"])
    categories = {}
    for cat in CATEGORIES:
        values = sorted((v[cat] for v in usable), reverse=True)
        evidence = values[support - 1] if len(values) >= support else 0.0
        categories[cat] = {
            "evidence": evidence,
            "max": values[0],
            "views": [v["view"] for v in usable if v[cat] >= th["different"]],
        }

    flagged = [c for c, s in categories.items() if s["evidence"] >= th["different"]]
    if flagged:
        verdict = "different"
        kinds = [c for c in flagged if c != "any_diff"] or ["any_diff"]
        reason = "Seen in several views: " + ", ".join(kinds) + "."
    elif all(s["evidence"] <= th["same"] for s in categories.values()):
        verdict, reason = "same", "No view showed a real difference."
    else:
        top = max(categories, key=lambda c: categories[c]["max"])
        verdict = "uncertain"
        reason = f"Mixed signals (strongest: {top} at {categories[top]['max']:.2f}); have a person look."
    return {"verdict": verdict, "usable_views": len(usable), "categories": categories, "reason": reason}
