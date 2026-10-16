"""Make labelled test pairs from one splat: a "re-capture" of the same object, plus edited versions.

Every output is moved to a random pose and scale, as if it had been captured separately, so the
alignment step is exercised too. Edits hit a region on the outside of the object, so they are visible.

    python -m tools.make_variants data/downloads/nike.splat --out data/nike

Input is a 3DGS .ply or an antimatter15 .splat. Outputs are 3DGS .ply files (SH degree 0: view-dependent
color is dropped from every file, the reference included, so it can't count as a difference).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement
from scipy.spatial.transform import Rotation

from splat_diff.align import isolate

SH_C0 = 0.28209479177387814


def load(path: Path) -> dict[str, np.ndarray]:
    """Return centers, log-scales, wxyz quaternions, opacity logits and SH DC color for every splat."""
    if path.suffix == ".splat":
        raw = np.fromfile(path, dtype=np.uint8).reshape(-1, 32)
        f = raw[:, :24].copy().view(np.float32)
        rgba = raw[:, 24:28].astype(np.float64) / 255
        q = (raw[:, 28:32].astype(np.float64) - 128) / 128
        alpha = np.clip(rgba[:, 3], 1e-4, 1 - 1e-4)
        return {
            "xyz": f[:, 0:3].astype(np.float64),
            "scale": np.log(np.maximum(f[:, 3:6], 1e-8)).astype(np.float64),
            "rot": q / np.linalg.norm(q, axis=1, keepdims=True),
            "opacity": np.log(alpha / (1 - alpha)),
            "dc": (rgba[:, :3] - 0.5) / SH_C0,
        }
    v = PlyData.read(str(path))["vertex"]
    col = lambda *names: np.stack([np.asarray(v[n], np.float64) for n in names], axis=1)  # noqa: E731
    rot = col("rot_0", "rot_1", "rot_2", "rot_3")
    return {
        "xyz": col("x", "y", "z"),
        "scale": col("scale_0", "scale_1", "scale_2"),
        "rot": rot / np.linalg.norm(rot, axis=1, keepdims=True),
        "opacity": np.asarray(v["opacity"], np.float64),
        "dc": col("f_dc_0", "f_dc_1", "f_dc_2"),
    }


def save(splats: dict[str, np.ndarray], path: Path) -> None:
    fields = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
              "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    data = np.hstack([splats["xyz"], splats["dc"], splats["opacity"][:, None], splats["scale"], splats["rot"]])
    arr = np.empty(len(data), dtype=[(f, "f4") for f in fields])
    for i, f in enumerate(fields):
        arr[f] = data[:, i]
    PlyData([PlyElement.describe(arr, "vertex")]).write(str(path))


def subset(s: dict, mask: np.ndarray) -> dict:
    return {k: v[mask] for k, v in s.items()}


def concat(a: dict, b: dict) -> dict:
    return {k: np.concatenate([a[k], b[k]]) for k in a}


def object_frame(s: dict) -> tuple[np.ndarray, float]:
    alpha = 1 / (1 + np.exp(-s["opacity"]))
    _, center, radius = isolate(s["xyz"][alpha > 0.3])
    return center, radius


def region(s: dict, center: np.ndarray, radius: float, direction: np.ndarray, size: float = 0.22):
    """Pick a patch on the object's outer surface in `direction`; return (mask, anchor, region radius)."""
    xyz = s["xyz"]
    near = np.linalg.norm(xyz - center, axis=1) < radius
    alpha = 1 / (1 + np.exp(-s["opacity"]))
    candidates = np.where(near & (alpha > 0.5))[0]
    anchor = xyz[candidates[np.argmax((xyz[candidates] - center) @ direction)]]
    r = size * radius
    return np.linalg.norm(xyz - anchor, axis=1) < r, anchor, r


def recapture(s: dict, rng: np.random.Generator, radius: float) -> tuple[dict, dict]:
    """Move to a random pose/scale and lose/jitter a little, like a second independent capture."""
    keep = rng.random(len(s["xyz"])) > 0.10
    s = subset(s, keep)
    rot = Rotation.random(random_state=rng)
    k = float(rng.uniform(0.5, 2.0))
    shift = rng.uniform(-3, 3, 3) * radius
    q_xyzw = (rot * Rotation.from_quat(s["rot"][:, [1, 2, 3, 0]])).as_quat()
    out = {
        "xyz": k * rot.apply(s["xyz"]) + shift,
        "scale": s["scale"] + np.log(k),
        "rot": q_xyzw[:, [3, 0, 1, 2]],
        "opacity": s["opacity"],
        "dc": s["dc"] + rng.normal(0, 0.03 / SH_C0, s["dc"].shape),  # ~3% color noise
    }
    return out, {"rotation_xyzw": rot.as_quat().tolist(), "scale": k, "shift": shift.tolist()}


def make(path: Path, out: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    base = load(path)
    center, radius = object_frame(base)
    out.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    save(base, out / f"{stem}_reference.ply")

    # Different directions per edit so each one lands on a different part of the object.
    dirs = Rotation.random(4, random_state=rng).apply([1.0, 0, 0])
    edits = {"same": lambda s: (s, {})}

    def missing(s, d=None):
        # Cut a chunk off one end along the object's longest axis (like a snapped-off toe or tab).
        # A patch deleted from a flat surface just looks like a scan hole, which isn't a fair test.
        core = s["xyz"][np.linalg.norm(s["xyz"] - center, axis=1) < radius]
        d = np.linalg.eigh(np.cov((core - center).T))[1][:, -1] * rng.choice([-1, 1]) if d is None else d
        proj = (s["xyz"] - center) @ d
        cut = np.percentile((core - center) @ d, 85)
        m = (proj > cut) & (np.linalg.norm(s["xyz"] - center, axis=1) < 1.5 * radius)
        return subset(s, ~m), {"axis": d.tolist(), "cut_at": float(cut), "splats": int(m.sum())}

    def recolor(s, d=dirs[1]):
        m, anchor, r = region(s, center, radius, d)
        rgb = s["dc"][m] * SH_C0 + 0.5
        lum = rgb @ [0.299, 0.587, 0.114]
        target = np.array([0.15, 0.35, 1.0]) if rgb.mean(0)[2] < 0.5 else np.array([1.0, 0.25, 0.1])
        s = {k: v.copy() for k, v in s.items()}
        s["dc"][m] = ((np.clip(lum, 0.15, 1)[:, None] * target / target.mean()).clip(0, 1) - 0.5) / SH_C0
        return s, {"anchor": anchor.tolist(), "radius": r, "splats": int(m.sum()), "color": target.tolist()}

    def dent(s, d=dirs[2]):
        m, anchor, r = region(s, center, radius, d, size=0.3)
        s = {k: v.copy() for k, v in s.items()}
        falloff = (1 - np.linalg.norm(s["xyz"][m] - anchor, axis=1) / r) ** 2
        s["xyz"][m] -= (0.6 * r * falloff)[:, None] * d
        return s, {"anchor": anchor.tolist(), "radius": r, "splats": int(m.sum())}

    def extra(s, d=dirs[3]):
        m, anchor, r = region(s, center, radius, d, size=0.18)
        blob = subset(s, m)
        blob["xyz"] = blob["xyz"] + 1.2 * r * d
        return concat(s, blob), {"anchor": anchor.tolist(), "radius": r, "splats": int(m.sum())}

    edits.update(missing_part=missing, recolor=recolor, dent=dent, extra_part=extra)

    manifest = {"source": str(path), "seed": seed, "object_center": center.tolist(), "object_radius": radius, "variants": {}}
    for name, edit in edits.items():
        edited, info = edit(base)
        moved, pose = recapture(edited, rng, radius)
        save(moved, out / f"{stem}_{name}.ply")
        manifest["variants"][name] = {"expected": "same" if name == "same" else "different", "edit": info, "pose": pose}
        print(f"{name:13s} {len(moved['xyz']):>9,} splats  scale x{pose['scale']:.2f}  {info.get('splats', '')}")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {len(edits) + 1} files to {out}. Compare {stem}_reference.ply against each variant.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", type=Path, help="3DGS .ply or .splat file")
    p.add_argument("--out", type=Path, help="output folder (default: data/<name>)")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    make(a.source, a.out or Path("data") / a.source.stem, a.seed)
