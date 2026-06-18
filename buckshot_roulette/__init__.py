"""Buckshot Roulette package."""

__all__ = [
    "ActionResult",
    "ActionType",
    "GameEngine",
    "GameState",
    "ItemType",
    "MatchConfig",
    "MatchState",
    "Player",
    "RoundStartResult",
    "ShellType",
]


def __getattr__(name: str):
    if name == "GameEngine":
        from .engine import GameEngine

        return GameEngine
    if name in {
        "ActionResult",
        "ActionType",
        "GameState",
        "ItemType",
        "MatchConfig",
        "MatchState",
        "Player",
        "RoundStartResult",
        "ShellType",
    }:
        from . import models

        return getattr(models, name)
    raise AttributeError(f"module 'buckshot_roulette' has no attribute {name!r}")
