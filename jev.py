"""Shared helpers for the examples. Import from here so every script starts the same way.

    from jev import client, show
"""

import os
import sys

from dotenv import load_dotenv
from typesafe_sdk import AsyncTypeSafeClient, SystemOneResponse, TypeSafeClient

load_dotenv()  # reads TYPESAFE_API_KEY from .env

MODEL = "jev-latest"  # list options with: TypeSafeClient().models.list()  (also: "jev-preview")


def _check_key() -> None:
    if not os.environ.get("TYPESAFE_API_KEY"):
        sys.exit(
            "TYPESAFE_API_KEY is not set.\n"
            "  1. Create a key at https://console.typesafe.ai/\n"
            "  2. Copy .env.example to .env and paste the key in."
        )


def client() -> TypeSafeClient:
    """A synchronous Jev client. Use it as `with client() as c: ...`."""
    _check_key()
    return TypeSafeClient(model=MODEL)


def async_client() -> AsyncTypeSafeClient:
    """An async Jev client, for firing many requests in parallel."""
    _check_key()
    return AsyncTypeSafeClient(model=MODEL)


def bar(p: float, width: int = 20) -> str:
    filled = round(p * width)
    return "#" * filled + "." * (width - filled)


def show(response: SystemOneResponse) -> None:
    """Pretty-print every answer in a response, so you can see what Jev returns."""
    for name, a in response.nouls.items():
        print(f"[noul]   {name}: P(yes) = {a.noul:.2f}  {bar(a.noul)}")
    for name, a in response.choices.items():
        print(f"[choice] {name}: {a.choice!r}  (confidence {a.confidence:.2f})")
        for option, p in sorted(a.probabilities.items(), key=lambda kv: -kv[1]):
            print(f"           {p:.2f} {bar(p)} {option}")
    for name, a in response.scores.items():
        top = len(a.legend) - 1
        print(f"[score]  {name}: {a.score:.2f} on a 0-{top} scale  (confidence {a.confidence:.2f})")
        for level, p in a.probabilities.items():
            print(f"           {p:.2f} {bar(p)} {level}: {a.legend[level]}")
    print()
