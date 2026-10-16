"""Local web app: upload two splats, align them, render matched views, ask Jev "is there a difference?".

Run:  uvicorn splat_diff.server:app --reload      then open http://localhost:8000
The API key stays here on the server; the browser only sends point samples and PNG renders.
Every comparison is saved under runs/ so 06_splat_diff.py can re-judge it later.
"""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typesafe_sdk import TypeSafeError

from jev import async_client
from splat_diff.align import Cloud, align
from splat_diff.judge import DEFAULT_THRESHOLDS, aggregate, judge_views

ROOT = Path(__file__).resolve().parent
RUNS = ROOT.parent / "runs"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_client() as client:
        app.state.jev = client
        yield


app = FastAPI(lifespan=lifespan)


class Sample(BaseModel):
    points: list[list[float]]
    opacity: list[float] | None = None
    scale: list[float] | None = None

    def cloud(self) -> Cloud:
        arr = lambda x: None if x is None else np.asarray(x, float)  # noqa: E731
        return Cloud(points=np.asarray(self.points, float), opacity=arr(self.opacity), scale=arr(self.scale))


class AlignRequest(BaseModel):
    a: Sample
    b: Sample


class AggregateRequest(BaseModel):
    views: list[dict]
    thresholds: dict = {}


@app.post("/api/align")
async def api_align(req: AlignRequest):
    if min(len(req.a.points), len(req.b.points)) < 100:
        raise HTTPException(400, "Need at least 100 splats in each model.")
    return await run_in_threadpool(align, req.a.cloud(), req.b.cloud())


@app.post("/api/compare")
async def api_compare(request: Request):
    form = await request.form()
    meta = json.loads(form["meta"])
    labels: list[str] = meta["views"]
    views = [(label, await form[f"a_{i}"].read(), await form[f"b_{i}"].read()) for i, label in enumerate(labels)]

    try:
        answers = await judge_views(request.app.state.jev, views)
    except TypeSafeError as e:
        raise HTTPException(502, f"Jev request failed: {e}") from e

    result = aggregate(answers, meta.get("thresholds"))
    run = _save_run(meta, views, answers, result)
    return {"run": run.name, "views": answers, "result": result, "thresholds": {**DEFAULT_THRESHOLDS, **meta.get("thresholds", {})}}


@app.post("/api/aggregate")
async def api_aggregate(req: AggregateRequest):
    """Re-run only the verdict logic with new thresholds: no Jev call."""
    return aggregate(req.views, req.thresholds)


def _save_run(meta: dict, views, answers: list[dict], result: dict) -> Path:
    names = meta.get("names", {})
    slug = re.sub(r"[^\w.-]+", "_", f"{names.get('a', 'a')}__vs__{names.get('b', 'b')}")[:80]
    run = RUNS / f"{datetime.now():%Y%m%d-%H%M%S}_{slug}"
    run.mkdir(parents=True)
    for i, (_, png_a, png_b) in enumerate(views):
        (run / f"view{i:02d}_a.png").write_bytes(png_a)
        (run / f"view{i:02d}_b.png").write_bytes(png_b)
    (run / "result.json").write_text(json.dumps({**meta, "answers": answers, "result": result}, indent=2))
    return run


# Test files in data/ can be opened directly: http://localhost:8000/?a=nike/nike_reference.ply&b=nike/nike_dent.ply
DATA = ROOT.parent / "data"
DATA.mkdir(exist_ok=True)
app.mount("/data", StaticFiles(directory=DATA), name="data")
app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
