"""06 - Is there a difference between two Gaussian splats? Jev judges matched renders, code decides.

The web app (uvicorn splat_diff.server:app) aligns two splats, renders 12 matched views of each and
saves them under runs/. This script re-asks Jev about saved runs, so you can check how stable the
answers are, or try different question wording, without re-rendering anything.

Run:  python 06_splat_diff.py                         # re-judge every saved run, one line each
      python 06_splat_diff.py --prompt v2             # same, with the v2 question wording
      python 06_splat_diff.py runs/<folder> -v        # one run, with every view's answers
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from jev import async_client
from splat_diff.judge import DEFAULT_PROMPT, PROMPTS, aggregate, judge_views

COLS = ["viewpoint_match", "shape_diff", "part_diff", "color_diff", "any_diff"]


def expected(run: Path) -> str:
    """Runs made from tools/make_variants.py outputs carry their ground truth in the file name."""
    m = re.search(r"__vs__\w+?_(same|missing_part|recolor|dent|extra_part)\.", run.name)
    return "?" if not m else "same" if m[1] == "same" else "different"


async def rejudge(run: Path, client, prompt: str) -> list[dict]:
    meta = json.loads((run / "result.json").read_text())
    views = [
        (label, (run / f"view{i:02d}_a.png").read_bytes(), (run / f"view{i:02d}_b.png").read_bytes())
        for i, label in enumerate(meta["views"])
    ]
    return await judge_views(client, views, prompt)


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # view labels contain "°"
    p = argparse.ArgumentParser()
    p.add_argument("runs", nargs="*", type=Path, help="run folders (default: all of runs/)")
    p.add_argument("--prompt", choices=PROMPTS, default=DEFAULT_PROMPT, help="question wording to use")
    p.add_argument("-v", "--verbose", action="store_true", help="print every view's answers")
    args = p.parse_args()
    runs = args.runs or sorted(d for d in Path("runs").iterdir() if (d / "result.json").exists())

    async with async_client() as c:
        all_answers = await asyncio.gather(*(rejudge(run, c, args.prompt) for run in runs))

    print(f"prompt {args.prompt}   evidence = {2}nd-strongest view per category\n")
    print(f"{'run':58s} {'expected':>9s} {'verdict':>16s}  shape  part  color   any")
    hits = scored = 0
    for run, answers in zip(runs, all_answers):
        result = aggregate(answers)
        exp, verdict = expected(run), result["verdict"]
        mark = "" if exp == "?" else " ok" if verdict == exp else " MISS"
        if exp != "?":
            scored += 1
            hits += verdict == exp
        ev = [result["categories"].get(k, {}).get("evidence", float("nan")) for k in COLS[1:]]
        print(f"{run.name[16:74]:58s} {exp:>9s} {verdict:>16s}  " + "  ".join(f"{e:.2f}" for e in ev) + mark)
        if args.verbose:
            for a in answers:
                print(f"     {a['view']:42s}" + "".join(f"{a[k]:7.2f}" for k in COLS))
    if scored:
        print(f"\n{hits}/{scored} runs with known ground truth judged correctly")


asyncio.run(main())
