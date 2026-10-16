"""Offline tests for the splat verdict logic in splat_diff/judge.py."""

from splat_diff.judge import aggregate


def view(name, viewpoint=0.95, shape=0.05, part=0.05, color=0.05, any_=0.05):
    return {"view": name, "viewpoint_match": viewpoint, "shape_diff": shape,
            "part_diff": part, "color_diff": color, "any_diff": any_}


def test_all_quiet_views_say_same():
    assert aggregate([view(f"v{i}") for i in range(12)])["verdict"] == "same"


def test_difference_seen_in_two_views_is_different():
    views = [view(f"v{i}") for i in range(10)] + [view("left", part=0.9, any_=0.9), view("front-left", part=0.85, any_=0.8)]
    result = aggregate(views)
    assert result["verdict"] == "different"
    assert result["categories"]["part_diff"]["views"] == ["left", "front-left"]
    assert "part_diff" in result["reason"] and "any_diff" not in result["reason"]


def test_one_noisy_view_cannot_flip_the_verdict():
    views = [view(f"v{i}") for i in range(11)] + [view("back", color=0.95)]
    assert aggregate(views)["verdict"] == "same"
    assert aggregate(views, {"support": 1})["verdict"] == "different"


def test_middling_evidence_is_uncertain():
    views = [view(f"v{i}", shape=0.4) for i in range(12)]
    assert aggregate(views)["verdict"] == "uncertain"


def test_misaligned_views_are_dropped_and_too_few_fails():
    views = [view(f"v{i}", viewpoint=0.1, any_=0.99) for i in range(8)] + [view(f"ok{i}") for i in range(4)]
    result = aggregate(views)
    assert result["verdict"] == "alignment_failed"
    assert result["usable_views"] == 4
