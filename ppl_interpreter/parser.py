"""Parser for classic Shanky PPL profiles (the `custom / preflop / When ... force` dialect).

Produces per-street rule lists with condition ASTs. Unknown symbols survive
parsing (they become ('sym', name) nodes); the evaluator counts them toward
the profile's coverage report instead of failing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

STREETS = ("preflop", "flop", "turn", "river")

_TOKEN_RX = re.compile(r"\(|\)|[a-zA-Z][a-zA-Z0-9_$]*|-?\d+%?|[<>=!]+|%")


@dataclass
class Rule:
    line_no: int
    text: str
    cond: tuple
    action: tuple | None          # ('fold'|'call'|'check'|'raise'|'bet', amount, unit)
    user_var: str | None = None   # `When <cond> UserXyz` sets a variable


@dataclass
class Profile:
    name: str
    sections: dict = field(default_factory=dict)   # street -> [Rule]
    symbols_used: set = field(default_factory=set)
    parse_errors: list = field(default_factory=list)


class ParseError(Exception):
    pass


def tokenize(line: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RX.findall(line)]


class _CondParser:
    """Recursive-descent for: expr := term (or term)* ; term := factor (and factor)*
    factor := [not] atom ; atom := (expr) | hand/board spec | comparison | symbol."""

    RANKS = set("a k q j t 9 8 7 6 5 4 3 2".split())
    ACTION_WORDS = {"raise", "call", "bet", "check", "fold", "none", "beep"}

    def __init__(self, tokens: list[str], symbols_used: set):
        self.t = tokens
        self.i = 0
        self.symbols_used = symbols_used

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self) -> str:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def parse(self) -> tuple:
        node = self.expr()
        return node

    def expr(self) -> tuple:
        parts = [self.term()]
        while self.peek() == "or":
            self.next()
            parts.append(self.term())
        return parts[0] if len(parts) == 1 else ("or", parts)

    def term(self) -> tuple:
        parts = [self.factor()]
        while self.peek() == "and":
            self.next()
            parts.append(self.factor())
        return parts[0] if len(parts) == 1 else ("and", parts)

    def factor(self) -> tuple:
        if self.peek() == "not":
            self.next()
            return ("not", self.factor())
        return self.atom()

    def atom(self) -> tuple:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of condition")
        if tok == "(":
            self.next()
            node = self.expr()
            if self.peek() != ")":
                raise ParseError("missing )")
            self.next()
            return node
        if tok in ("hand", "board"):
            return self.hand_or_board()
        if tok == "others":
            self.next()
            return ("true",)
        if tok == "in":     # `in smallblind` / `in bigblind` / `in button`
            self.next()
            where = self.next() if self.peek() else ""
            name = {"smallblind": "insmallblind", "bigblind": "inbigblind",
                    "button": "onbutton"}.get(where, "in_" + where)
            self.symbols_used.add(name)
            return ("sym", name)
        name = self.next()
        # comparison?
        if self.peek() in ("=", "<", ">", "<=", ">=", "!="):
            op = self.next()
            val_tok = self.next()
            if val_tok.endswith("%"):
                nxt = self.peek()
                if nxt is not None and nxt not in ("and", "or", ")", "(") \
                        and re.fullmatch(r"[a-z][a-z0-9_$]*", nxt):
                    self.symbols_used.add(nxt)
                    val: object = ("pctof", int(val_tok[:-1]), self.next())
                else:
                    val = ("pct", int(val_tok[:-1]))
            elif re.fullmatch(r"-?\d+", val_tok):
                val = int(val_tok)
            else:
                val = val_tok  # enumerated: botslastaction = raise, position = last...
            self.symbols_used.add(name)
            return ("cmp", name, op, val)
        self.symbols_used.add(name)
        return ("sym", name)

    def hand_or_board(self) -> tuple:
        kind = self.next()               # 'hand' | 'board'
        if self.peek() != "=":
            self.symbols_used.add(kind)
            return ("sym", kind)
        self.next()
        ranks: list[str] = []
        suited = False
        while True:
            tok = self.peek()
            if tok is not None and tok != "suited" and all(c in self.RANKS for c in tok):
                ranks.extend(self.next())
            elif tok is not None and len(tok) == 2 and tok[0] in self.RANKS \
                    and tok[1] in "shdc":
                ranks.append(self.next()[0])   # 7s 5s → ranks 7,5; exact suits ≈ suited
                suited = True
            elif tok == "suited":
                self.next()
                suited = True
            else:
                break
        if not ranks:
            raise ParseError(f"{kind} = <empty>")
        return (kind, tuple(ranks), suited)


_ACTION_RX = re.compile(
    r"^(?P<verb>raisemax|raisemin|raisepot|raisehalfpot|betpot|bethalfpot|betmax|raise|bet|call|check|fold|sitout|beep|play)"
    r"\s*(?P<amt>\d+%?)?\s*force$")


def parse_action(text: str) -> tuple | None:
    m = _ACTION_RX.match(text.strip().lower())
    if not m:
        return None
    verb, amt = m.group("verb"), m.group("amt")
    if verb in ("sitout", "beep", "check"):
        return ("check", None, None)
    if verb == "fold":
        return ("fold", None, None)
    if verb in ("call", "play"):
        return ("call", None, None)
    if verb in ("raisemax", "betmax"):
        return ("raise", None, "max")
    if verb == "raisemin":
        return ("raise", None, "min")
    if verb in ("raisepot", "betpot"):
        return ("raise", 100, "pct")
    if verb in ("raisehalfpot", "bethalfpot"):
        return ("raise", 50, "pct")
    # raise / bet with optional amount
    if amt is None:
        return ("raise", None, "min")
    if amt.endswith("%"):
        return ("raise", int(amt[:-1]), "pct")
    return ("raise", int(amt), "bb")


def _balanced(text: str) -> bool:
    return text.count("(") == text.count(")")


def _terminated(low: str) -> bool:
    if low.endswith("force"):
        return True
    m = re.search(r"\buser[a-z0-9_]+$", low)
    if m is None:
        return False
    before = low[:m.start()].rstrip()
    return not before.endswith((" and", " or", " not", "(", "when"))


def parse_profile(text: str, name: str = "profile") -> Profile:
    """Shanky idioms handled:
    - bare `when <cond>` line (no action) = GUARD: ANDed into following rules
      until the next guard or street header;
    - old profiles occasionally wrap one rule across lines (unbalanced parens
      or missing action) — continuation lines are appended until terminated.
    """
    prof = Profile(name=name)
    for st in STREETS:
        prof.sections[st] = []
    street = None
    guard_text: str | None = None
    pending: str | None = None

    def close(pending_text: str, idx: int) -> None:
        rule = _finish_rule(pending_text, idx, prof, guard_text)
        if rule is not None and street is not None:
            prof.sections[street].append(rule)

    for idx, raw in enumerate(text.splitlines(), 1):
        line = raw.split("//")[0].strip()
        if not line:
            continue
        low = line.lower()
        if low == "custom":
            continue
        if low in STREETS:
            street = low
            guard_text = None
            pending = None
            continue
        if street is None:
            continue
        if pending is not None:
            pending += " " + line
            low_p = pending.lower()
            if _terminated(low_p) and _balanced(pending):
                close(pending, idx)
                pending = None
            continue
        if not low.startswith("when"):
            continue
        if _terminated(low) and _balanced(line):
            close(line, idx)
        elif _balanced(line) and not _terminated(low):
            guard_text = line[4:].strip()      # bare when = guard
        else:
            pending = line                     # wrapped rule, keep accumulating
    if pending is not None:
        prof.parse_errors.append((0, "unterminated rule at EOF"))
    return prof


def _finish_rule(text: str, line_no: int, prof: Profile,
                 guard_text: str | None = None) -> Rule | None:
    low = text.lower()
    body = low[4:].strip()  # drop 'when'
    user_var = None
    action = None

    m = re.search(r"\buser([a-z0-9_]+)$", body)
    if m and not body.endswith("force") \
            and not body[:m.start()].rstrip().endswith((" and", " or", " not", "(")):
        user_var = "user" + m.group(1)
        cond_text = body[:m.start()].strip()
    else:
        # action = last 1..3 tokens ending in force
        am = re.search(
            r"\b(raisemax|raisemin|raisepot|raisehalfpot|betpot|bethalfpot|betmax|raise|bet|call|check|fold|sitout|beep|play)"
            r"(\s+\d+%?)?\s+force$", body)
        if not am:
            prof.parse_errors.append((line_no, f"no action: {text[:60]}"))
            return None
        action = parse_action(body[am.start():])
        cond_text = body[:am.start()].strip()
    try:
        tokens = tokenize(cond_text)
        cond = _CondParser(tokens, prof.symbols_used).parse() if tokens else ("true",)
        if guard_text:
            gtokens = tokenize(guard_text)
            if gtokens:
                gcond = _CondParser(gtokens, prof.symbols_used).parse()
                cond = ("and", [gcond, cond])
    except ParseError as e:
        prof.parse_errors.append((line_no, f"{e}: {cond_text[:60]}"))
        return None
    return Rule(line_no=line_no, text=text.strip(), cond=cond,
                action=action, user_var=user_var)
