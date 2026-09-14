"""What the interpreter needs from a poker engine. Implement GameState for your engine, or use SimpleState for tests.

Amounts are in chips; BB is the big blind in chips (PPL amount symbols are converted to big blinds with it).
Seats are 0..n-1. `position(seat)` returns one of "SB", "BB", "UTG", "MP", "CO", "BTN" (heads-up: "SB" is the button).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

BB = 2


@dataclass
class LegalActions:
    fold: bool
    check: bool                 # nothing to call
    call_amount: int            # 0 when check
    raise_min: int | None       # total "to" amount on this street; None if raise unavailable
    raise_max: int | None


class GameState(Protocol):
    n: int

    @property
    def street(self) -> str: ...          # "preflop" | "flop" | "turn" | "river"
    @property
    def board(self) -> list[str]: ...     # e.g. ["Ah", "Td", "7c"]
    @property
    def pot(self) -> int: ...
    def hole(self, seat: int) -> list[str]: ...
    def stack(self, seat: int) -> int: ...
    def bet(self, seat: int) -> int: ...  # chips committed on the current street
    def position(self, seat: int) -> str: ...
    def alive(self, seat: int) -> bool: ...


POSITIONS = {2: ["SB", "BB"], 6: ["SB", "BB", "UTG", "MP", "CO", "BTN"]}


@dataclass
class SimpleState:
    """A frozen decision point. Enough to evaluate a profile without a real engine."""
    holes: list[list[str]]
    board: list[str] = field(default_factory=list)
    stacks: list[int] = field(default_factory=list)
    bets: list[int] = field(default_factory=list)
    pot: int = 0
    street: str = "preflop"
    folded: set = field(default_factory=set)
    positions: list[str] | None = None

    def __post_init__(self):
        self.n = len(self.holes)
        self.stacks = self.stacks or [200] * self.n
        self.bets = self.bets or [0] * self.n
        self.positions = self.positions or POSITIONS[self.n]

    def hole(self, seat: int) -> list[str]: return list(self.holes[seat])
    def stack(self, seat: int) -> int: return self.stacks[seat]
    def bet(self, seat: int) -> int: return self.bets[seat]
    def position(self, seat: int) -> str: return self.positions[seat]
    def alive(self, seat: int) -> bool: return seat not in self.folded


def default_table(n: int) -> dict:
    """Tallies the symbol evaluator reads (raises/calls this street, bot's own history, positions). Keep them updated from your engine."""
    return {"raises": 0, "bets": 0, "calls": 0, "checks": 0, "folds": 0, "hist": {},
            "bot_actions_this_round": 0, "bot_last_action": "none", "still_to_act": n - 1,
            "opponents_at_table": n - 1, "invested_bb": 0, "last_raiser_seat": None,
            "first_raiser_seat": None, "first_caller_seat": None, "last_caller_seat": None, "calls_since_raise": 0, "user_vars": {}}
