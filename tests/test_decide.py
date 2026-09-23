"""Decisions on frozen states: no engine, no network. Every case is a (profile, state, table, expected) tuple."""
from pathlib import Path

import pytest

from ppl_interpreter import LegalActions, SimpleState, default_table, load_profile, parse_profile

PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def la(call=0, rmin=None, rmax=None, fold=True):
    return LegalActions(fold=fold, check=call == 0, call_amount=call, raise_min=rmin, raise_max=rmax)


def decide(bot, state, seat, legal, table=None):
    bot.reset_hand()
    t = default_table(state.n)
    t.update(table or {})
    return bot.decide_ppl(state, seat, legal, t)


@pytest.fixture(scope="module")
def tight():
    bot, rep = load_profile(PROFILES / "teaching_tight.txt")
    assert rep["coverage_pct"] == 100.0, rep
    return bot


@pytest.fixture(scope="module")
def loose():
    bot, rep = load_profile(PROFILES / "teaching_loose.txt")
    assert rep["coverage_pct"] == 100.0, rep
    return bot


def test_aces_raise_preflop(tight):
    st = SimpleState(holes=[["2c", "7d"], ["3c", "8d"], ["Ah", "Ad"]] + [["2c", "7d"]] * 3, street="preflop", pot=3, bets=[1, 2, 0, 0, 0, 0])
    kind, amount = decide(tight, st, 2, la(call=2, rmin=4, rmax=200))
    assert kind == "raise" and amount == 2 + 4 * 2   # raise 4 = BY 4 big blinds over the level (2)
    assert "hand = aa" in tight.thoughts[-1]["reason"].lower()   # the trace names the rule that fired


def test_trash_folds_preflop(tight):
    st = SimpleState(holes=[["Ac", "Ad"], ["Kc", "Kd"], ["7h", "2d"]] + [["Ac", "Ad"]] * 3, street="preflop", pot=3, bets=[1, 2, 0, 0, 0, 0])
    assert decide(tight, st, 2, la(call=2, rmin=4, rmax=200))[0] == "fold"


def test_big_blind_checks_when_free(tight):
    st = SimpleState(holes=[["7h", "2d"]] * 6, street="preflop", pot=4, bets=[1, 2, 0, 0, 0, 0])
    assert decide(tight, st, 1, la(call=0, rmin=4, rmax=200))[0] == "cc"


def test_set_on_flop_raises_max(tight):
    st = SimpleState(holes=[["8h", "8d"], ["Ac", "Kd"]], board=["8c", "Kh", "2s"], street="flop", pot=12, bets=[0, 6])
    kind, amount = decide(tight, st, 0, la(call=6, rmin=12, rmax=194))
    assert kind == "raise" and amount == 194


def test_top_pair_bets_two_thirds(tight):
    st = SimpleState(holes=[["Ah", "Kd"], ["7c", "6d"]], board=["Kc", "9h", "2s"], street="flop", pot=12, bets=[0, 0])
    kind, amount = decide(tight, st, 0, la(call=0, rmin=2, rmax=200))
    assert kind == "raise" and amount == 8   # 66% of 12 = 8, level 0


def test_missed_flop_folds_to_bet(tight):
    st = SimpleState(holes=[["Ah", "Kd"], ["7c", "6d"]], board=["9c", "5h", "2s"], street="flop", pot=12, bets=[0, 8])
    assert decide(tight, st, 0, la(call=8, rmin=16, rmax=194))[0] == "fold"


def test_loose_calls_small_with_pair(loose):
    st = SimpleState(holes=[["9h", "8d"], ["Ac", "Kd"]], board=["9c", "Kh", "2s"], street="flop", pot=12, bets=[0, 5])
    assert decide(loose, st, 0, la(call=5, rmin=10, rmax=195))[0] == "cc"


def test_no_matching_rule_defaults_to_check_or_fold():
    bot = parse_profile("custom\nflop\nWhen haveset raisemax force\n", "min")
    from ppl_interpreter import PPLBot
    b = PPLBot(bot, "min")
    st = SimpleState(holes=[["Ah", "Kd"], ["7c", "6d"]], board=["9c", "5h", "2s"], street="flop", pot=12)
    assert decide(b, st, 0, la(call=0))[0] == "cc"
    assert decide(b, st, 0, la(call=8))[0] == "fold"


def test_unknown_symbol_counts_not_crashes():
    from ppl_interpreter import PPLBot
    b = PPLBot(parse_profile("custom\nflop\nWhen havemagicbeans raisemax force\nWhen others fold force\n", "u"), "u")
    st = SimpleState(holes=[["Ah", "Kd"], ["7c", "6d"]], board=["9c", "5h", "2s"], street="flop", pot=12)
    assert decide(b, st, 0, la(call=8))[0] == "fold"
    assert "havemagicbeans" in b.unknown_symbols


def _flop(bets):
    return SimpleState(holes=[["Ah", "Kd"], ["Qs", "Qc"]], street="flop", board=["Ac", "7d", "2s"],
                       pot=12, bets=bets, positions=["sb", "bb"])


def _bot(flop_rule: str, **kw):
    from ppl_interpreter import PPLBot
    return PPLBot(parse_profile(f"custom\npreflop\nflop\n{flop_rule}\n", "t"), "t", **kw)


def test_fold_checks_when_free():
    # PPL guide 3.2.3: "Fold - will check if available else fold"
    assert decide(_bot("When others fold force"), _flop([0, 0]), 0, la(rmin=2, rmax=100)) == ("cc", None)


def test_bet_calls_when_a_bet_is_in():
    # "Bet - will bet if available otherwise will Call"; raise still raises
    facing = la(call=6, rmin=12, rmax=100)
    assert decide(_bot("When others betpot force"), _flop([0, 6]), 0, facing) == ("cc", None)
    assert decide(_bot("When others raisepot force"), _flop([0, 6]), 0, facing)[0] == "raise"
    assert decide(_bot("When others betpot force"), _flop([0, 0]), 0, la(rmin=2, rmax=100))[0] == "raise"


def test_no_rule_uses_fallback_when_given():
    st, legal = _flop([0, 6]), la(call=6, rmin=12, rmax=100)
    plain = _bot("")
    assert decide(plain, st, 0, legal) == ("fold", None)
    assert plain.last_src == {"src": "default_fold"}
    fb = _bot("", fallback=lambda state, seat, la_: ("cc", None))
    assert decide(fb, st, 0, legal) == ("cc", None)
    assert fb.last_src == {"src": "fallback"}
