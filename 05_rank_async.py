"""05 - Ranking many items fast: async requests + scores combined in code.

Score each item on a few dimensions once, then let code weight/sort them.
Changing the weights does NOT need another API call.
Run:  python 05_rank_async.py
"""

import asyncio

from typesafe_sdk import Noul, Score

from jev import async_client

goal = "A weekend hackathon project for a beginner team that wants to win a 'social good' prize."

ideas = [
    "An app that matches food bank surplus with nearby shelters in real time.",
    "A blockchain-based NFT marketplace for rare sneakers.",
    "A browser extension that rewrites dense government forms in plain language.",
    "A custom operating system kernel written from scratch in Rust.",
    "A Discord bot that tells jokes.",
]

QUESTIONS = {
    "impact": Score(
        instructions="How much social good would `idea` do if it worked?",
        criteria=["None", "Small or niche benefit", "Meaningful benefit to a real group", "Large, clear benefit"],
    ),
    "feasibility": Score(
        instructions="How realistic is it for a beginner team to build a working demo of `idea` in one weekend?",
        criteria=["Impossible", "Very hard", "Doable with effort", "Easy"],
    ),
    "fits_goal": Noul(instructions="Does `idea` fit what is described in `goal`?"),
}

WEIGHTS = {"impact": 0.6, "feasibility": 0.4}  # tweak freely: no re-query needed


async def judge(c, idea: str):
    return idea, await c.system_one(state={"goal": goal, "idea": idea}, questions=QUESTIONS)


async def main() -> None:
    async with async_client() as c:
        results = await asyncio.gather(*(judge(c, idea) for idea in ideas))  # all in parallel

    rows = []
    for idea, r in results:
        # normalise each score to 0..1 by dividing by the top level index
        norm = {k: r.scores[k].score / (len(r.scores[k].legend) - 1) for k in WEIGHTS}
        total = sum(WEIGHTS[k] * norm[k] for k in WEIGHTS) * r.nouls["fits_goal"].noul
        rows.append((total, norm, idea))

    for total, norm, idea in sorted(rows, reverse=True):
        print(f"{total:.2f}  impact={norm['impact']:.2f} feas={norm['feasibility']:.2f}  {idea}")


asyncio.run(main())
