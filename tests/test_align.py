"""Offline tests for splat registration: no API key, no browser."""

import numpy as np
from scipy.spatial.transform import Rotation

from splat_diff.align import Cloud, align, apply


def lumpy_object(rng, n=6000):
    """An asymmetric object surface (box + offset ball + stub), so only one orientation fits.
    Surfaces, not volumes: splats sit on an object's skin, which is what makes scale identifiable."""
    half = np.array([1, 0.5, 0.3])
    box = rng.uniform(-half, half, (n // 2, 3))
    face = rng.integers(0, 3, n // 2)
    box[np.arange(n // 2), face] = half[face] * rng.choice([-1, 1], n // 2)
    ball = rng.normal(size=(n // 4, 3))
    ball = ball / np.linalg.norm(ball, axis=1, keepdims=True) * 0.4 + [0.8, 0.6, 0.0]
    stub = rng.uniform([-1.0, -0.2, 0.3], [-0.6, 0.2, 0.9], (n // 4, 3))
    return np.vstack([box, ball, stub])


def recapture(rng, points, scale, rotation, shift, dropout=0.1, noise=0.01, floaters=300):
    """Simulate a separate capture: new frame, some splats lost, jitter, and background floaters."""
    kept = points[rng.random(len(points)) > dropout]
    kept = kept + rng.normal(0, noise, kept.shape)
    junk = rng.uniform(-8, 8, (floaters, 3))
    pts = np.vstack([kept, junk])
    opacity = np.concatenate([rng.uniform(0.5, 1, len(kept)), rng.uniform(0, 0.25, floaters)])
    return Cloud(points=scale * pts @ rotation.T + shift, opacity=opacity), kept


def test_recovers_a_random_similarity_transform():
    rng = np.random.default_rng(1)
    obj = lumpy_object(rng)
    a, _ = recapture(rng, obj, 1.0, np.eye(3), np.zeros(3))
    rot = Rotation.random(random_state=7).as_matrix()
    b, b_obj = recapture(rng, obj, 3.7, rot, np.array([5.0, -2.0, 10.0]))

    result = align(a, b)

    # Points of the object in B, mapped back, should land where they started.
    b_obj_in_file = 3.7 * b_obj @ rot.T + [5.0, -2.0, 10.0]
    err = np.linalg.norm(apply(result["matrix"], b_obj_in_file) - b_obj, axis=1)
    assert np.median(err) < 0.05
    assert abs(result["scale"] - 1 / 3.7) < 0.03
    assert result["metrics"]["a_covered"] > 0.8
    assert result["metrics"]["ambiguity"] < 0.9  # the asymmetric object has one clear orientation


def test_scale_survives_a_missing_chunk():
    """Cutting off one end shrinks B's spread; the scale must come from matching, not spread."""
    rng = np.random.default_rng(3)
    obj = lumpy_object(rng)
    a, _ = recapture(rng, obj, 1.0, np.eye(3), np.zeros(3))
    cut = obj[obj[:, 0] < 0.6]  # lose the +x end (incl. most of the ball)
    rot = Rotation.random(random_state=11).as_matrix()
    b, _ = recapture(rng, cut, 1.47, rot, np.array([1.0, 2.0, 3.0]))

    result = align(a, b)

    assert abs(result["scale"] - 1 / 1.47) / (1 / 1.47) < 0.05
    m = np.asarray(result["matrix"])[:3, :3] * 1.47
    assert np.allclose(m @ rot, np.eye(3), atol=0.08)


def test_crop_sphere_ignores_background_floaters():
    rng = np.random.default_rng(2)
    a, _ = recapture(rng, lumpy_object(rng), 1.0, np.eye(3), np.zeros(3), floaters=2000)
    result = align(a, a)
    assert result["crop"]["radius"] < 2.0  # the object spans ~1.3, the floaters spread to ~14
    assert np.allclose(result["matrix"], np.eye(4), atol=0.05)
