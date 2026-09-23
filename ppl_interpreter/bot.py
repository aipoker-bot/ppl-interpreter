"""PPLBot: runs a parsed Shanky profile as a table opponent, with rule traces.

Evaluation: top-down within the street section; user-var rules set variables,
the first matching action rule fires. No match → the `fallback` callable if
one is given, else check/fold. (Real Shanky falls through to its own default
profile, which ships encrypted; plug in whatever default logic you have.)
Every decision records WHICH rule fired — that trace becomes the bot's
"table talk" (the educational payoff of running real profiles).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Callable

from .parser import Profile, Rule, parse_profile
from .symbols import RANK_ORDER, PPLContext, UnknownSymbol, rv
from .state import BB, GameState as Hand


def eval_cond(node: tuple, ctx: PPLContext) -> bool:
    op = node[0]
    if op == "true":
        return True
    if op == "and":
        return all(eval_cond(x, ctx) for x in node[1])
    if op == "or":
        return any(eval_cond(x, ctx) for x in node[1])
    if op == "not":
        return not eval_cond(node[1], ctx)
    if op == "sym":
        return bool(ctx.value(node[1]))
    if op == "cmp":
        return _cmp(node, ctx)
    if op == "hand":
        return _match_hand(node, ctx)
    if op == "board":
        return _match_board(node, ctx)
    raise UnknownSymbol(str(op))


def _cmp(node: tuple, ctx: PPLContext) -> bool:
    _, name, op, target = node
    val = ctx.value(name)
    if isinstance(target, tuple):
        if target[0] == "pct":          # bare N% — treat as percent of pot
            target_v = target[1] / 100 * ctx.value("potsize")
        else:                            # ('pctof', n, symbol)
            target_v = target[1] / 100 * ctx.value(target[2])
    elif isinstance(target, str):
        sval = str(val).lower()
        return sval == target if op == "=" else sval != target
    else:
        target_v = target
    if isinstance(val, bool):
        val = int(val)
    if op == "=":
        return val == target_v
    if op == "!=":
        return val != target_v
    if op == "<":
        return val < target_v
    if op == "<=":
        return val <= target_v
    if op == ">":
        return val > target_v
    if op == ">=":
        return val >= target_v
    raise UnknownSymbol(f"op {op}")


def _match_hand(node: tuple, ctx: PPLContext) -> bool:
    _, ranks, suited = node
    hole = sorted((c[0].lower() for c in ctx.hole), key=RANK_ORDER.lower().index)
    want = sorted(ranks, key=RANK_ORDER.lower().index)
    if suited and len({c[1] for c in ctx.hole}) != 1:
        return False
    if len(want) == 1:   # `hand = A` / `hand = A suited`: one hole card of that rank
        return want[0] in hole
    return hole == want


def _match_board(node: tuple, ctx: PPLContext) -> bool:
    _, ranks, suited = node
    board = Counter(c[0].lower() for c in ctx.board)
    want = Counter(ranks)
    if suited and len({c[1] for c in ctx.board}) > 1:
        return False
    return all(board[r] >= n for r, n in want.items())


class PPLBot:
    def __init__(self, profile: Profile, display_name: str,
                 fallback: Callable | None = None):
        """`fallback(hand, seat, la) -> (kind, amount)` plays spots no rule
        covers; without it the bot checks if free, otherwise folds."""
        self.profile = profile
        self.name = display_name
        self.fallback = fallback
        self.thoughts: list[dict] = []
        self.user_vars: dict = {}
        self.unknown_symbols: Counter = Counter()
        # where the last decision came from: {"src": "rule", "line": N},
        # {"src": "fallback"} or {"src": "default_fold"}
        self.last_src: dict = {}

    def reset_hand(self) -> None:
        self.thoughts = []
        self.user_vars = {}

    def decide_ppl(self, hand: Hand, seat: int, la, table: dict):
        self.last_src = {}
        table = {**table, "user_vars": self.user_vars}
        ctx = PPLContext(hand, seat, la, table)
        street = hand.street
        rules = self.profile.sections.get(street, [])
        for rule in rules:
            try:
                hit = eval_cond(rule.cond, ctx)
            except UnknownSymbol as e:
                self.unknown_symbols[e.name] += 1
                continue
            except Exception:
                continue
            if not hit:
                continue
            if rule.user_var:
                self.user_vars[rule.user_var] = True
                continue
            kind, amount = self._to_engine_action(rule.action, ctx)
            self._trace(street, kind, rule)
            self.last_src = {"src": "rule", "line": rule.line_no}
            return kind, amount
        if self.fallback is not None:
            kind, amount = self.fallback(hand, seat, la)
            self.last_src = {"src": "fallback"}
            self.thoughts.append({"street": street,
                                  "action": {"cc": "call/check", "fold": "fold",
                                             "raise": "raise"}[kind],
                                  "reason": "No profile rule matched — fallback."})
            return kind, amount
        kind = "cc" if la.check else "fold"
        self.last_src = {"src": "default_fold"}
        self.thoughts.append({"street": street, "action": "check" if la.check else "fold",
                              "reason": "No profile rule matched — default check/fold."})
        return kind, None

    def _to_engine_action(self, action: tuple, ctx: PPLContext):
        verb, amt, unit = action
        la = ctx.la
        # PPL Guide 3.2.3: "Fold - will check if available else fold",
        # "Bet - will bet if available otherwise will Call" (never preflop)
        if verb == "fold":
            return (("cc", None) if la.check or not la.fold else ("fold", None))
        if verb in ("check", "call"):
            return ("cc", None)
        if verb == "bet" and (la.call_amount > 0 or ctx.h.street == "preflop"):
            return ("cc", None)
        # raise family; amounts are BY over the current level
        if la.raise_min is None:
            return ("cc", None)
        level = ctx.h.bet(ctx.seat) + la.call_amount
        if unit == "max":
            return ("raise", la.raise_max)
        if unit == "min":
            return ("raise", la.raise_min)
        if unit == "pct":
            by = int(round(ctx.h.pot * (amt / 100)))
        else:                      # bb
            by = int(round(amt * BB))
        return ("raise", max(la.raise_min, min(la.raise_max, level + by)))

    def _trace(self, street: str, kind: str, rule: Rule) -> None:
        cond_text = re.sub(r"\s+", " ", rule.text)
        cond_text = re.sub(r"^when\s+", "", cond_text, flags=re.I)
        if len(cond_text) > 150:
            cond_text = cond_text[:147] + "…"
        self.thoughts.append({
            "street": street,
            "action": {"cc": "call/check", "fold": "fold", "raise": "raise"}[kind],
            "reason": f"rule L{rule.line_no}: {cond_text}",
        })


def load_profile(path: str | Path, display_name: str | None = None,
                 fallback: Callable | None = None) -> tuple[PPLBot, dict]:
    """Load + coverage report: % of rules whose symbols are all implemented."""
    from .symbols import SYMBOLS
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    prof = parse_profile(text, Path(path).stem)
    known = set(SYMBOLS)

    def syms_of(node) -> set:
        if not isinstance(node, tuple):
            return set()
        op = node[0]
        if op in ("sym",):
            return {node[1]}
        if op == "cmp":
            out = {node[1]}
            if isinstance(node[3], tuple) and node[3][0] == "pctof":
                out.add(node[3][2])
            return out
        if op in ("and", "or"):
            return set().union(*(syms_of(x) for x in node[1]))
        if op == "not":
            return syms_of(node[1])
        return set()

    total = evaluable = 0
    missing: Counter = Counter()
    for rules in prof.sections.values():
        for r in rules:
            total += 1
            syms = syms_of(r.cond)
            unknown = {s for s in syms if s not in known and not s.startswith("user")}
            if unknown:
                missing.update(unknown)
            else:
                evaluable += 1
    report = {
        "profile": prof.name,
        "rules": total,
        "evaluable": evaluable,
        "coverage_pct": round(evaluable / total * 100, 1) if total else 0.0,
        "parse_errors": len(prof.parse_errors),
        "missing_symbols": missing.most_common(15),
    }
    return PPLBot(prof, display_name or prof.name, fallback), report
