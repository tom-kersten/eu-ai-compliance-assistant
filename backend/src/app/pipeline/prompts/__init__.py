from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent


def load_prompt(name: str) -> str:
    path = HERE / f"{name}.txt"
    return path.read_text(encoding="utf-8")
