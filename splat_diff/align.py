"""Register two separately captured splats: find the similarity transform that maps B onto A.

Works on splat centers only (sampled in the browser), so it doesn't care about the file format.
Steps: drop faint/huge splats -> isolate the object core -> normalise position and scale
-> try 24 coarse rotations around the PCA axes -> trimmed ICP -> keep the best fit.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

MIN_OPACITY = 0.3
FIT_EPS = 0.05  # "has a neighbour" distance for the overlap metric, in units of the object's radius


@dataclass
class Cloud:
    points: np.ndarray  # (N, 3) splat centers, original file coordinates
    opacity: np.ndarray | None = None  # (N,) 0..1
    scale: np.ndarray | None = None  # (N,) largest axis of each splat


def denoise(cloud: Cloud) -> np.ndarray:
    """Return the centers that are likely real surface: not faint floaters, not huge blobs."""
    keep = np.ones(len(cloud.points), bool)
    if cloud.opacity is not None:
        keep &= cloud.opacity >= MIN_OPACITY
        if keep.sum() < 0.2 * len(keep):  # unusual opacity distribution: keep the most opaque 70%
            keep = cloud.opacity >= np.percentile(cloud.opacity, 30)
    if cloud.scale is not None:
        keep &= cloud.scale <= np.percentile(cloud.scale, 95)
    return cloud.points[keep]


def isolate(points: np.ndarray, iterations: int = 4) -> tuple[np.ndarray, np.ndarray, float]:
    """Shrink towards the dense core so leftover background doesn't drive the alignment.

    Returns (object points, center, radius). The radius is used as the render crop sphere.
    """
    kept = points
    for _ in range(iterations):
        center = np.median(kept, axis=0)
        d = np.linalg.norm(points - center, axis=1)
        radius = 2.0 * np.percentile(d[d <= np.percentile(d, 90)], 75)
        kept = points[d <= radius]
    center = np.median(kept, axis=0)
    radius = float(np.percentile(np.linalg.norm(kept - center, axis=1), 98))
    return kept, center, radius


def _normalise(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    center = points.mean(axis=0)
    scale = float(np.median(np.linalg.norm(points - center, axis=1)))
    return (points - center) / scale, center, scale


def _pca_axes(points: np.ndarray) -> np.ndarray:
    _, vecs = np.linalg.eigh(np.cov(points.T))
    vecs = vecs[:, ::-1]  # largest variance first
    if np.linalg.det(vecs) < 0:
        vecs[:, 2] *= -1
    return vecs


def _cube_rotations() -> list[np.ndarray]:
    """The 24 proper rotations that map coordinate axes onto coordinate axes."""
    rots = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = np.zeros((3, 3))
            m[range(3), perm] = signs
            if np.isclose(np.linalg.det(m), 1):
                rots.append(m)
    return rots


def _umeyama(src: np.ndarray, dst: np.ndarray, with_scale: bool) -> tuple[np.ndarray, np.ndarray]:
    """Best (sR, t) with dst ≈ src @ (sR).T + t; s = 1 unless with_scale (Kabsch vs Umeyama)."""
    sc, dc = src.mean(axis=0), dst.mean(axis=0)
    u, sv, vt = np.linalg.svd((src - sc).T @ (dst - dc))
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1, 1, d]) @ u.T
    if with_scale:
        r *= (sv[0] + sv[1] + d * sv[2]) / np.sum((src - sc) ** 2)
    return r, dc - sc @ r.T


def _icp(a_tree: cKDTree, a: np.ndarray, b: np.ndarray, r: np.ndarray, t: np.ndarray, iters: int,
         trim: float = 0.8, with_scale: bool = False):
    """Trimmed ICP. `r` may carry a uniform scale once with_scale is on."""
    for _ in range(iters):
        moved = b @ r.T + t
        dist, idx = a_tree.query(moved)
        keep = dist <= np.quantile(dist, trim)
        r, t = _umeyama(b[keep], a[idx[keep]], with_scale)
    return r, t, _symmetric_error(a_tree, a, b @ r.T + t, trim)


def _partial_error(a_tree: cKDTree, a: np.ndarray, moved_b: np.ndarray, trim: float = 0.9) -> float:
    """How well the smaller scan sits on the bigger one: the better of the two one-sided fits.
    If B lost a chunk, B->A is still tight; if B gained one, A->B is."""
    d_ba, _ = a_tree.query(moved_b)
    d_ab, _ = cKDTree(moved_b).query(a)
    one_sided = lambda d: float(np.sqrt(np.mean(np.sort(d)[: int(trim * len(d))] ** 2)))  # noqa: E731
    return min(one_sided(d_ba), one_sided(d_ab))


def _scale_search(a_tree: cKDTree, a: np.ndarray, b: np.ndarray, r: np.ndarray, t: np.ndarray):
    """Rigid ICP at a range of scales for B; keep the scale whose best rigid fit is tightest."""
    best = None
    for grid in (np.geomspace(0.7, 1.4, 13), None):
        if grid is None:  # refine around the coarse winner
            grid = best[2] * np.geomspace(0.95, 1.05, 9)
        for k in grid:
            rk, tk, _ = _icp(a_tree, a, k * b, r, t, iters=12)
            e = _partial_error(a_tree, a, (k * b) @ rk.T + tk)
            if best is None or e < best[3]:
                best = (rk, tk, float(k), e)
    return best[:3]


def _symmetric_error(a_tree: cKDTree, a: np.ndarray, moved_b: np.ndarray, trim: float = 0.8) -> float:
    d_ba, _ = a_tree.query(moved_b)
    d_ab, _ = cKDTree(moved_b).query(a)
    return float(np.sqrt((np.mean(np.sort(d_ba)[: int(trim * len(d_ba))] ** 2) + np.mean(np.sort(d_ab)[: int(trim * len(d_ab))] ** 2)) / 2))


def _angle_deg(r1: np.ndarray, r2: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(r1.T @ r2) - 1) / 2, -1, 1))))


def _subsample(points: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    return points if len(points) <= n else points[rng.choice(len(points), n, replace=False)]


def align(a: Cloud, b: Cloud, max_points: int = 3000, seed: int = 0) -> dict:
    """Find the 4x4 similarity matrix taking B's file coordinates into A's, plus fit metrics."""
    rng = np.random.default_rng(seed)
    a_obj, a_center, a_radius = isolate(denoise(a))
    b_obj, _, b_radius = isolate(denoise(b))

    an, a_mean, a_scale = _normalise(_subsample(a_obj, max_points, rng))
    bn, b_mean, b_scale = _normalise(_subsample(b_obj, max_points, rng))
    a_tree = cKDTree(an)

    # Coarse: every axis-to-axis mapping between the two PCA frames, a few ICP steps each.
    va, vb = _pca_axes(an), _pca_axes(bn)
    starts = [(va @ q @ vb.T, np.zeros(3)) for q in _cube_rotations()]
    coarse = sorted((_icp(a_tree, an, bn, r, t, iters=8) for r, t in starts), key=lambda x: x[2])
    # Fine: polish the 3 best candidates and keep the winner.
    r, t, err = min((_icp(a_tree, an, bn, r, t, iters=30) for r, t, _ in coarse[:3]), key=lambda x: x[2])
    # Median-radius normalisation is fooled when one scan is missing a chunk, so search the scale too.
    r, t, k = _scale_search(a_tree, an, bn, r, t)
    err = _symmetric_error(a_tree, an, bn @ (k * r).T + t)
    r = k * r
    # Symmetric objects can fit about as well in a genuinely different orientation; flag that.
    others = [e for rc, _, e in coarse if _angle_deg(rc, r / k) > 30]
    runner_up = min(others, default=float("inf"))

    # Compose: a = a_scale * (kR (b - b_mean) / b_scale + t) + a_mean    (r already holds k)
    s = a_scale / b_scale
    matrix = np.eye(4)
    matrix[:3, :3] = s * r
    matrix[:3, 3] = a_scale * t - s * (r @ b_mean) + a_mean
    s *= k

    moved = bn @ r.T + t
    d_ba, _ = a_tree.query(moved)
    d_ab, _ = cKDTree(moved).query(an)
    return {
        "matrix": matrix.tolist(),  # row-major 4x4, B file coords -> A file coords
        "scale": s,
        "crop": {"center": a_center.tolist(), "radius": max(a_radius, b_radius * s)},
        "metrics": {
            "rmse": err,  # trimmed, in units of the object's median radius
            "a_covered": float(np.mean(d_ab < FIT_EPS)),  # share of A with a B splat nearby
            "b_covered": float(np.mean(d_ba < FIT_EPS)),  # share of B with an A splat nearby
            "ambiguity": float(err / runner_up) if runner_up > 0 else 1.0,  # near 1 = another orientation fits as well
            "points_used": [len(an), len(bn)],
        },
    }


def apply(matrix: np.ndarray | list, points: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix)
    return points @ m[:3, :3].T + m[:3, 3]
