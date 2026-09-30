"""Symbol evaluator for Shanky PPL against our engine state.

Semantics follow the Shanky PPL guide with OpenPPL (Inhuman's library) as the
reference for edge cases. Amount symbols are in BIG BLINDS. Unknown symbols
raise UnknownSymbol — the rule evaluates False and the miss is counted, so a
profile can never crash a table (coverage is reported instead).
"""

from __future__ import annotations

import random
from itertools import combinations

from phevaluator import evaluate_cards

from .state import BB, GameState as Hand

RANK_ORDER = "23456789TJQKA"


class UnknownSymbol(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(name)


def rv(card: str) -> int:
    return RANK_ORDER.index(card[0])


# phevaluator rank boundaries (lower = stronger)
def _category(rank: int) -> str:
    if rank <= 10: return "straight_flush"
    if rank <= 166: return "quads"
    if rank <= 322: return "full_house"
    if rank <= 1599: return "flush"
    if rank <= 1609: return "straight"
    if rank <= 2467: return "trips"
    if rank <= 3325: return "two_pair"
    if rank <= 6185: return "pair"
    return "high"


def _has_straight(vals: set[int]) -> bool:
    ext = set(vals) | ({-1} if RANK_ORDER.index("A") in vals else set())
    return any(all(v + i in ext for i in range(5)) for v in range(-1, 9))


class PPLContext:
    """One hero decision point for a PPL profile."""

    def __init__(self, hand: Hand, seat: int, la, table: dict):
        self.h = hand
        self.seat = seat
        self.la = la
        self.t = table                      # tallies & history from the table actor
        self.hole = hand.hole(seat)
        self.board = hand.board
        self.user_vars: dict = table.get("user_vars", {})
        self._random = random.randint(1, 100)
        self._eval_cache: dict = {}

    # -- card helpers -------------------------------------------------------

    @property
    def bvals(self) -> list[int]:
        return sorted((rv(c) for c in self.board), reverse=True)

    @property
    def hvals(self) -> list[int]:
        return sorted((rv(c) for c in self.hole), reverse=True)

    def _pheval(self, cards: list[str]) -> int:
        key = tuple(cards)
        if key not in self._eval_cache:
            self._eval_cache[key] = evaluate_cards(*cards)
        return self._eval_cache[key]

    @property
    def made(self) -> str:
        if len(self.board) < 3:
            return "high"
        return _category(self._pheval(self.hole + self.board))

    def board_pair_count(self) -> int:
        from collections import Counter
        c = Counter(self.bvals)
        return sum(1 for v in c.values() if v >= 2)

    def pocket_pair(self) -> int | None:
        return self.hvals[0] if self.hvals[0] == self.hvals[1] else None

    def hole_pairs_board(self) -> list[int]:
        """Board ranks matched by a hole card (top-pair detection)."""
        bs = set(self.bvals)
        return sorted({v for v in self.hvals if v in bs}, reverse=True)

    def flush_suit(self, n: int) -> str | None:
        """Suit with >= n cards among hole+board using >=1 hole card."""
        for suit in "shdc":
            total = sum(1 for c in self.hole + self.board if c[1] == suit)
            mine = sum(1 for c in self.hole if c[1] == suit)
            if total >= n and mine >= 1:
                return suit
        return None

    def straight_draw_outs(self) -> int:
        """Ranks that complete a straight using >=1 hole card."""
        outs = 0
        have = self.hvals + self.bvals
        for v in range(13):
            if v in have:
                continue
            vals = set(have) | {v}
            if _has_straight(vals) and not _has_straight(set(self.bvals) | {v}):
                # must actually use a hole card
                if not _has_straight(set(self.bvals + [v])):
                    outs += 1
        return outs

    # -- symbol table -------------------------------------------------------

    def value(self, name: str):
        fn = SYMBOLS.get(name)
        if fn is None:
            if name.startswith("user"):
                return bool(self.user_vars.get(name))
            raise UnknownSymbol(name)
        return fn(self)


def _pos_index(ctx: PPLContext) -> tuple[int, int]:
    """(index among live seats in this street's acting order, live count)."""
    h, seat = ctx.h, ctx.seat
    n = h.n
    order = list(range(n)) if len(ctx.board) >= 3 else \
        [(i + 2) % n for i in range(n)]      # preflop starts UTG (seat 2)
    live = [s for s in order if h.alive(s)]
    return (live.index(seat) if seat in live else 0), len(live)


def _lastpos_scale(ctx: PPLContext, seat: int | None) -> int:
    """Map a seat to Shanky's rough 1..10 full-ring position scale."""
    if seat is None:
        return 0
    scale = {0: 1, 1: 3, 2: 5, 3: 6, 4: 8, 5: 10}
    return scale.get(seat, 5)


SYMBOLS = {
    # amounts (in big blinds)
    "amounttocall": lambda c: c.la.call_amount / BB,
    "potsize": lambda c: c.h.pot / BB,
    "stacksize": lambda c: c.h.stack(c.seat) / BB,
    "betsize": lambda c: (c.h.bet(c.seat) + c.la.call_amount) / BB,
    "totalinvested": lambda c: c.t.get("invested_bb", 0),
    "opponentsattable": lambda c: c.t.get("opponents_at_table", c.h.n - 1),
    "random": lambda c: c._random,

    # street counters (from table tally)
    "raises": lambda c: c.t.get("raises", 0),
    "bets": lambda c: c.t.get("bets", 0),
    "calls": lambda c: c.t.get("calls", 0),
    "checks": lambda c: c.t.get("checks", 0),
    "folds": lambda c: c.t.get("folds", 0),
    "raisesbeforeflop": lambda c: c.t.get("hist", {}).get("preflop", {}).get("raises", 0),
    "raisesonflop": lambda c: c.t.get("hist", {}).get("flop", {}).get("raises", 0),
    "raisesonturn": lambda c: c.t.get("hist", {}).get("turn", {}).get("raises", 0),
    "calledonflop": lambda c: c.t.get("hist", {}).get("flop", {}).get("bot_called", False),
    "calledonturn": lambda c: c.t.get("hist", {}).get("turn", {}).get("bot_called", False),
    "nobettingonflop": lambda c: c.t.get("hist", {}).get("flop", {}).get("bets", 0) == 0
        and c.t.get("hist", {}).get("flop", {}).get("raises", 0) == 0,
    "nobettingonturn": lambda c: c.t.get("hist", {}).get("turn", {}).get("bets", 0) == 0
        and c.t.get("hist", {}).get("turn", {}).get("raises", 0) == 0,
    "botsactionsonthisround": lambda c: c.t.get("bot_actions_this_round", 0),
    "botsactionspreflop": lambda c: c.t.get("hist", {}).get("preflop", {}).get("bot_actions", 0),
    "botslastaction": lambda c: c.t.get("bot_last_action", "none"),
    "botslastpreflopaction": lambda c: c.t.get("hist", {}).get("preflop", {}).get("bot_last", "none"),
    "botraisedbeforeflop": lambda c: c.t.get("hist", {}).get("preflop", {}).get("bot_raised", False),
    "botcalledbeforeflop": lambda c: c.t.get("hist", {}).get("preflop", {}).get("bot_called", False),
    "botraisedonflop": lambda c: c.t.get("hist", {}).get("flop", {}).get("bot_raised", False),
    "botislastraiser": lambda c: c.t.get("last_raiser_seat") == c.seat,
    "opponentisallin": lambda c: any(c.h.stack(s) == 0 and c.h.alive(s)
                                     for s in range(c.h.n) if s != c.seat),
    "opponents": lambda c: _pos_index(c)[1] - 1,
    "opponentsonflop": lambda c: c.t.get("hist", {}).get("flop", {}).get("opponents",
                                                                        _pos_index(c)[1] - 1),
    "callssincelastraise": lambda c: c.t.get("calls_since_raise", 0),

    # positions
    "position": lambda c: ("first" if _pos_index(c)[0] == 0 else
                           "last" if _pos_index(c)[0] == _pos_index(c)[1] - 1 else "middle"),
    "stilltoact": lambda c: c.t.get("still_to_act", 0),
    "inbigblind": lambda c: c.h.position(c.seat) == "BB",
    "insmallblind": lambda c: c.h.position(c.seat) == "SB",
    "onbutton": lambda c: c.h.position(c.seat) == "BTN",
    "lastraiserposition": lambda c: _lastpos_scale(c, c.t.get("last_raiser_seat")),
    "firstcallerposition": lambda c: _lastpos_scale(c, c.t.get("first_caller_seat")),

    # board texture
    "paironboard": lambda c: c.board_pair_count() >= 1,
    "twopaironboard": lambda c: c.board_pair_count() >= 2,
    "tripsonboard": lambda c: any(c.bvals.count(v) >= 3 for v in set(c.bvals)),
    "quadsonboard": lambda c: any(c.bvals.count(v) >= 4 for v in set(c.bvals)),
    "straightonboard": lambda c: len(c.board) >= 5 and _has_straight(set(c.bvals)),
    "threecardstraightonboard": lambda c: any(          # ace also plays low (A-2-3)
        all(v + i in _low_ace(c.bvals) for i in range(3)) for v in range(-1, 11)),
    "suitsonboard": lambda c: len({x[1] for x in c.board}) if c.board else 4,
    "suitsonflop": lambda c: len({x[1] for x in c.board[:3]}) if len(c.board) >= 3 else 4,
    "suitsinhand": lambda c: len({x[1] for x in c.hole}),
    "flushpossible": lambda c: any(sum(1 for x in c.board if x[1] == s) >= 3 for s in "shdc"),
    "flushpossibleonflop": lambda c: len({x[1] for x in c.board[:3]}) == 1 if len(c.board) >= 3 else False,
    "flushpossibleonturn": lambda c: any(sum(1 for x in c.board[:4] if x[1] == s) >= 3 for s in "shdc"),
    "onecardflushpossible": lambda c: any(sum(1 for x in c.board if x[1] == s) >= 4 for s in "shdc"),
    "twoofonesuitpresentonflop": lambda c: any(
        sum(1 for x in c.board[:3] if x[1] == s) >= 2 for s in "shdc"),
    "straightpossible": lambda c: any(
        _has_straight(set(c.bvals) | set(p)) for p in combinations(range(13), 2)),
    "onecardstraightpossible": lambda c: any(
        _has_straight(set(c.bvals) | {v}) for v in range(13)),
    "straightpossibleonflop": lambda c: len(c.board) >= 3 and any(
        _has_straight(set(c.bvals[:3] if False else [rv(x) for x in c.board[:3]]) | set(p))
        for p in combinations(range(13), 2)),
    "morethanonestraightpossibleonflop": lambda c: sum(
        1 for p in combinations(range(13), 2)
        if _has_straight({rv(x) for x in c.board[:3]} | set(p))) > 1,
    "morethanonestraightpossibleonturn": lambda c: len(c.board) >= 4
        and _n_straights([rv(x) for x in c.board[:4]]) > 1,
    "onlyonestraightpossible": lambda c: _n_straights(c.bvals) == 1,
    "onecardstraightpossibleonturn": lambda c: any(
        _has_straight({rv(x) for x in c.board[:4]} | {v}) for v in range(13)),
    "straightflushpossible": lambda c: _sf_possible(c.board, ()),
    "straightflushpossiblebyothers": lambda c: _sf_possible(c.board, c.hole),
    "uncoordinatedflop": lambda c: len({x[1] for x in c.board[:3]}) == 3
        and not SYMBOLS["threecardstraightonboard"](c) and c.board_pair_count() == 0,
    "acepresentonflop": lambda c: any(x[0] == "A" for x in c.board[:3]),
    "kingpresentonflop": lambda c: any(x[0] == "K" for x in c.board[:3]),
    "queenpresentonflop": lambda c: any(x[0] == "Q" for x in c.board[:3]),
    "overcardsonboard": lambda c: sum(1 for v in c.bvals if v > c.hvals[0]),

    # hole/made hands
    "pairinhand": lambda c: c.pocket_pair() is not None,
    "overcards": lambda c: sum(1 for v in c.hvals if c.bvals and v > c.bvals[0]),
    "havepair": lambda c: c.pocket_pair() is not None or bool(c.hole_pairs_board()),
    "havetoppair": lambda c: bool(c.bvals) and bool(c.hole_pairs_board())
        and c.hole_pairs_board()[0] == c.bvals[0],
    "have2ndtoppair": lambda c: len(set(c.bvals)) >= 2 and bool(c.hole_pairs_board())
        and c.hole_pairs_board()[0] == sorted(set(c.bvals), reverse=True)[1],
    "have3rdtoppair": lambda c: len(set(c.bvals)) >= 3 and bool(c.hole_pairs_board())
        and c.hole_pairs_board()[0] == sorted(set(c.bvals), reverse=True)[2],
    "have4thtoppair": lambda c: len(set(c.bvals)) >= 4 and bool(c.hole_pairs_board())
        and c.hole_pairs_board()[0] == sorted(set(c.bvals), reverse=True)[3],
    "havebottompair": lambda c: bool(c.bvals) and min(c.bvals) in c.hvals,
    "haveoverpair": lambda c: c.pocket_pair() is not None and bool(c.bvals)
        and c.pocket_pair() > c.bvals[0],
    "have2ndoverpair": lambda c: _nth_overpair(c, 2),
    "have3rdoverpair": lambda c: _nth_overpair(c, 3),
    "have4thoverpair": lambda c: _nth_overpair(c, 4),
    "have5thoverpair": lambda c: _nth_overpair(c, 5),
    "haveunderpair": lambda c: c.pocket_pair() is not None and bool(c.bvals)
        and c.pocket_pair() < min(c.bvals),
    "havetwopair": lambda c: c.pocket_pair() is None and all(v in c.bvals for v in c.hvals)
        and not any(c.bvals.count(v) >= 2 and v > c.hvals[1] for v in set(c.bvals)),
    "havetoptwopair": lambda c: c.pocket_pair() is None and len(set(c.bvals)) >= 2
        and set(sorted(set(c.bvals), reverse=True)[:2]) <= set(c.hvals),
    "havetrips": lambda c: c.pocket_pair() is None
        and any(c.bvals.count(v) == 2 for v in c.hvals),
    "haveset": lambda c: c.made in ("trips", "full_house", "quads")
        and c.pocket_pair() is not None and c.pocket_pair() in c.bvals,
    "havetopset": lambda c: SYMBOLS["haveset"](c) and bool(c.bvals)
        and c.pocket_pair() == c.bvals[0],
    "havestraight": lambda c: c.made in ("straight", "straight_flush")
        or (len(c.board) >= 3 and _has_straight(set(c.hvals) | set(c.bvals))),
    "havenutstraight": lambda c: c.made == "straight" and _nut_straight_rank(c) == 1,
    "have2ndnutstraight": lambda c: c.made == "straight" and _nut_straight_rank(c) == 2,
    "haveunderstraight": lambda c: _under_straight(c),
    "haveflush": lambda c: c.made in ("flush", "straight_flush"),
    "havenutflush": lambda c: c.made == "flush" and _nut_flush_rank(c) == 1,
    "have2ndnutflush": lambda c: c.made == "flush" and _nut_flush_rank(c) == 2,
    "havefullhouse": lambda c: c.made == "full_house",
    "havequads": lambda c: c.made == "quads",
    "havestraightflush": lambda c: c.made == "straight_flush",
    "nutfullhouseorfourofakind": lambda c: c.made in ("full_house", "quads")
        and (c.pocket_pair() is None or c.pocket_pair() == (c.bvals[0] if c.bvals else -1)
             or c.made == "quads"),
    "havenuts": lambda c: _have_nuts(c),
    "havenothing": lambda c: len(c.board) >= 3 and not (
        SYMBOLS["havepair"](c) or SYMBOLS["havestraight"](c) or SYMBOLS["haveflush"](c)
        or SYMBOLS["haveinsidestraightdraw"](c) or SYMBOLS["haveflushdraw"](c)
        or SYMBOLS["havebackdoorflushdraw"](c) or SYMBOLS["overcards"](c) == 2),
    "havebestkicker": lambda c: _kicker_rank(c) == 1,
    "have2ndbestkicker": lambda c: _kicker_rank(c) == 2,
    "have3rdbestkicker": lambda c: _kicker_rank(c) == 3,
    "havetopnonboardpairedpair": lambda c: any(c.bvals.count(v) == 1 for v in c.bvals)
        and max(v for v in c.bvals if c.bvals.count(v) == 1) in c.hvals,
    "hadtoppaironflop": lambda c: len(c.board) >= 3 and bool(
        set(c.hvals) & {max(rv(x) for x in c.board[:3])}),

    # draws
    "haveflushdraw": lambda c: c.flush_suit(4) is not None,      # made flush counts
    "havebackdoorflushdraw": lambda c: len(c.board) == 3 and c.flush_suit(3) is not None,
    "havenutflushdraw": lambda c: _nut_flushdraw_rank(c) == 1,
    "have2ndnutflushdraw": lambda c: _nut_flushdraw_rank(c) == 2,
    "have3rdnutflushdraw": lambda c: _nut_flushdraw_rank(c) == 3,
    "have4thnutflushdraw": lambda c: _nut_flushdraw_rank(c) == 4,
    "have5thnutflushdraw": lambda c: _nut_flushdraw_rank(c) == 5,
    # Guide: "made straight or >= 7 outs" / ">= 4 outs"; nut variants count outs
    # to the nut straight (NutStraightDraw drops flush-making outs if no flush yet).
    "havestraightdraw": lambda c: _my_straight(c.hole, c.board) > 0
        or _straight_outs(c) >= 7,
    "haveinsidestraightdraw": lambda c: _my_straight(c.hole, c.board) > 0
        or _straight_outs(c) >= 4,
    "havenutstraightdraw": lambda c: _is_nut_straight(c.hole, c.board)
        or _nut_straight_outs(c, discount_flush=True) >= 7,
    "haveinsidenutstraightdraw": lambda c: _is_nut_straight(c.hole, c.board)
        or _nut_straight_outs(c, discount_flush=False) >= 4,

    "paironflop": lambda c: len(c.board) >= 3 and len({rv(x) for x in c.board[:3]}) < 3,
    "paironturn": lambda c: len(c.board) >= 4 and len({rv(x) for x in c.board[:4]}) < 4,
    "hadoverpaironflop": lambda c: len(c.board) >= 3 and c.pocket_pair() is not None
        and c.pocket_pair() > max(rv(x) for x in c.board[:3]),
    "havebackdoornutflushdraw": lambda c: len(c.board) == 3 and (lambda suit: suit is not None
        and any(x[1] == suit and rv(x) == max(
            (v for v in range(13) if v not in {rv(b) for b in c.board if b[1] == suit}),
            default=12) for x in c.hole))(c.flush_suit(3)),
    # "or better" = any better hand of the bot's own (a pair counts; board-only
    # trips/two pair do not, board straight/flush/full house do, as in HaveX)
    "havebestkickerorbetter": lambda c: _kicker_rank(c) == 1 or SYMBOLS["havepair"](c)
        or c.made in ("straight", "flush", "full_house", "quads", "straight_flush"),
    "lastcallerposition": lambda c: _lastpos_scale(c, c.t.get("last_caller_seat")),

    "bigblindsize": lambda c: 2,           # cash table: BB is 2 chips
    "flushonboard": lambda c: len(c.board) >= 5 and len({x[1] for x in c.board}) == 1,
    "fullhouseonboard": lambda c: len(c.board) >= 5 and sorted(
        __import__("collections").Counter(c.bvals).values()) == [2, 3],
    "havebottomset": lambda c: SYMBOLS["haveset"](c) and bool(c.bvals)
        and c.pocket_pair() == min(c.bvals),
    "have3rdnutflush": lambda c: c.made == "flush" and _nut_flush_rank(c) == 3,
    "havenutstraightflush": lambda c: c.made == "straight_flush",
    "have2ndbestkickerorbetter": lambda c: 1 <= _kicker_rank(c) <= 2
        or SYMBOLS["havebestkickerorbetter"](c),
    "have3rdbestkickerorbetter": lambda c: 1 <= _kicker_rank(c) <= 3
        or SYMBOLS["havebestkickerorbetter"](c),
    "straightpossibleonturn": lambda c: len(c.board) >= 4 and any(
        _has_straight({rv(x) for x in c.board[:4]} | set(pr))
        for pr in combinations(range(13), 2)),
    "botraisedonturn": lambda c: c.t.get("hist", {}).get("turn", {}).get("bot_raised", False),
    "botsactionsonflop": lambda c: c.t.get("hist", {}).get("flop", {}).get("bot_actions", 0),
    "firstraiserposition": lambda c: _lastpos_scale(c, c.t.get("first_raiser_seat")),
    "inbutton": lambda c: c.h.position(c.seat) == "BTN",
    "rivercardisovercardtoboard": lambda c: len(c.board) >= 5
        and rv(c.board[4]) > max(rv(x) for x in c.board[:4]),
    "opponentcalledonturn": lambda c: c.t.get("hist", {}).get("turn", {}).get("calls", 0) > 0,
    "topflopcardpairedonturn": lambda c: len(c.board) >= 4
        and rv(c.board[3]) == max(rv(x) for x in c.board[:3]),
    "maxopponentstacksize": lambda c: max((c.h.stack(s2) for s2 in range(c.h.n)
                                           if s2 != c.seat and c.h.alive(s2)), default=0) / BB,

    # misc
    "others": lambda c: True,
    "true": lambda c: True,
}


def _nth_overpair(ctx: PPLContext, n: int) -> bool:
    pp = ctx.pocket_pair()
    if pp is None or not ctx.bvals:
        return False
    higher_board = sorted({v for v in set(ctx.bvals) if v > pp}, reverse=True)
    return len(higher_board) == n - 1


def _kicker_rank(ctx: PPLContext) -> int:
    """1 = our non-pair hole card is the best possible kicker."""
    pairs = ctx.hole_pairs_board()
    if not pairs:
        return 0
    kickers = [v for v in ctx.hvals if v != pairs[0]]
    if not kickers:
        return 0
    dead = set(ctx.bvals) | {pairs[0]}
    better = [v for v in range(12, -1, -1) if v not in dead and v > kickers[0]]
    return len(better) + 1


def _nut_flush_rank(ctx: PPLContext) -> int:
    suit = next((s for s in "shdc"
                 if sum(1 for x in ctx.hole + ctx.board if x[1] == s) >= 5
                 and any(x[1] == s for x in ctx.hole)), None)
    if suit is None:
        return 0
    mine = max(rv(x) for x in ctx.hole if x[1] == suit)
    on_board = {rv(x) for x in ctx.board if x[1] == suit}
    better = [v for v in range(12, mine, -1) if v not in on_board]
    return len(better) + 1


def _nut_flushdraw_rank(ctx: PPLContext) -> int:
    suit = ctx.flush_suit(4)                  # made flush counts ("made nut flush or ...")
    if suit is None:
        return 0
    mine = max((rv(x) for x in ctx.hole if x[1] == suit), default=-1)
    if mine < 0:
        return 0
    on_board = {rv(x) for x in ctx.board if x[1] == suit}
    better = [v for v in range(12, mine, -1) if v not in on_board]
    return len(better) + 1


def _nut_straight_rank(ctx: PPLContext) -> int:
    """1 = nut straight given this board."""
    best_own = _best_straight_high(set(ctx.hvals) | set(ctx.bvals))
    best_any = 0
    for p in combinations(range(13), 2):
        h = _best_straight_high(set(ctx.bvals) | set(p))
        best_any = max(best_any, h)
    if best_own == 0:
        return 0
    return 1 if best_own >= best_any else 2 if best_own == best_any - 1 else 3


def _best_straight_high(vals: set[int]) -> int:
    ext = set(vals) | ({-1} if RANK_ORDER.index("A") in vals else set())
    best = 0
    for v in range(-1, 9):
        if all(v + i in ext for i in range(5)):
            best = max(best, v + 4)
    return best


def _draw_is_nut(ctx: PPLContext) -> bool:
    """Our straight draw is to the nut straight (approximation)."""
    for v in range(13):
        vals = set(ctx.hvals) | set(ctx.bvals) | {v}
        if _has_straight(vals):
            own = _best_straight_high(vals)
            board_after = set(ctx.bvals) | {v}
            best_any = max((_best_straight_high(board_after | set(p))
                            for p in combinations(range(13), 2)), default=0)
            if own >= best_any:
                return True
    return False


# -- helpers for the Shanky-guide fixes --------------------------------------

_DECK = [r + s for r in RANK_ORDER for s in "shdc"]


def _low_ace(vals) -> set[int]:
    vals = set(vals)
    return vals | ({-1} if RANK_ORDER.index("A") in vals else set())


def _n_straights(bvals) -> int:
    """Distinct straights the board allows with two hole cards (OpenPPL's window
    rule: >= 3 board ranks in the window and the next rank up not on board).
    Guide: AKQ -> 1 (JT), KQJ -> 2 (AT, T9)."""
    s = _low_ace(bvals)
    return sum(1 for lo in range(-1, 9)
               if len(s & set(range(lo, lo + 5))) >= 3 and (lo + 5) not in s)


def _sf_possible(board, excluded) -> bool:
    """A straight flush can be made with the board (>= 3 suited board cards in a
    5-rank window, ace also low); `excluded` cards (the bot's hole cards) cannot
    be used by anyone else -> StraightFlushPossibleByOthers."""
    for suit in "shdc":
        have = _low_ace(rv(x) for x in board if x[1] == suit)
        for lo in range(-1, 9):
            win = set(range(lo, lo + 5))
            if len(win & have) < 3:
                continue
            need = {12 if v == -1 else v for v in win - have}
            if not any(RANK_ORDER[v] + suit in excluded for v in need):
                return True
    return False


def _my_straight(hole, board) -> int:
    """High card of our straight, 0 if we have none beyond the board's own."""
    own = _best_straight_high({rv(x) for x in hole + board})
    return own if own > _best_straight_high({rv(x) for x in board}) else 0


def _is_nut_straight(hole, board) -> bool:
    mine = _my_straight(hole, board)
    bv = {rv(x) for x in board}
    best = max(_best_straight_high(bv | set(p)) for p in combinations(range(13), 2))
    return mine > 0 and mine >= best


def _unseen(ctx):
    return [x for x in _DECK if x not in ctx.hole and x not in ctx.board]


def _straight_outs(ctx) -> int:
    return sum(1 for x in _unseen(ctx) if _my_straight(ctx.hole, ctx.board + [x]))


def _nut_straight_outs(ctx, discount_flush: bool) -> int:
    fp = SYMBOLS["flushpossible"](ctx)
    n = 0
    for x in _unseen(ctx):
        b2 = ctx.board + [x]
        if not _is_nut_straight(ctx.hole, b2):
            continue
        if discount_flush and not fp and sum(1 for y in b2 if y[1] == x[1]) >= 3:
            continue
        n += 1
    return n


def _under_straight(ctx) -> bool:
    """Guide: all hand cards used in the straight are lower than every board
    card used in it."""
    hi = _my_straight(ctx.hole, ctx.board)
    if not hi:
        return False
    win = {12 if v == -1 else v for v in range(hi - 4, hi + 1)}
    low = (lambda v: -1 if v == 12 and hi == 3 else v)       # wheel: ace is low
    bv = {rv(x) for x in ctx.board}
    used_h = {v for v in ctx.hvals if v in win} - bv
    used_b = bv & win
    return bool(used_h) and max(map(low, used_h)) < min(map(low, used_b))


def _have_nuts(ctx) -> bool:
    if len(ctx.board) < 3:
        return False
    me = ctx._pheval(ctx.hole + ctx.board)
    return all(evaluate_cards(a, b, *ctx.board) >= me
               for a, b in combinations(_unseen(ctx), 2))
