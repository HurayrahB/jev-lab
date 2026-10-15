"""Offline tests for the helpers in jev.py. These don't need an API key:  python -m pytest"""

import pytest
from typesafe_sdk import ChoiceAnswer, NoulAnswer, ScoreAnswer, SystemOneResponse

import jev


def test_bar_scales_to_width():
    assert jev.bar(0.0, 10) == ".........."
    assert jev.bar(1.0, 10) == "##########"
    assert jev.bar(0.5, 10) == "#####....."


def test_missing_key_exits_with_help(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="console.typesafe.ai"):
        jev.client()


def test_show_prints_every_answer_type(capsys):
    response = SystemOneResponse.model_construct(
        answers={
            "billing": NoulAnswer(type="noul", noul=0.9),
            "tone": ChoiceAnswer(type="choice", choice="angry", confidence=0.8, probabilities={"angry": 0.9, "calm": 0.1}),
            "urgency": ScoreAnswer(
                type="score", score=1.5, confidence=0.6,
                legend={0: "low", 1: "mid", 2: "high"}, probabilities={0: 0.0, 1: 0.5, 2: 0.5},
            ),
        }
    )
    jev.show(response)
    out = capsys.readouterr().out
    assert "billing: P(yes) = 0.90" in out
    assert "tone: 'angry'" in out
    assert "urgency: 1.50 on a 0-2 scale" in out
