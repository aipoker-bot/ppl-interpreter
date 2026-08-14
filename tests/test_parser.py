from ppl_interpreter import parse_profile


def test_basic_rules_and_actions():
    prof = parse_profile("""custom
preflop
When hand = AA and raises = 0 raise 3 force
When others fold force
flop
When haveset raisemax force
When bets = 0 bet 66% force
""", "t")
    pre = prof.sections["preflop"]
    assert len(pre) == 2
    assert pre[0].action == ("raise", 3, "bb")
    assert pre[1].action == ("fold", None, None)
    assert prof.sections["flop"][0].action == ("raise", None, "max")
    assert prof.sections["flop"][1].action[1:] == (66, "pct")   # bet/raise are one family in Shanky: BY over the current level


def test_bare_when_is_a_guard():
    prof = parse_profile("""custom
flop
When raises = 0
When haveset raisemax force
When havepair bet 50% force
turn
When haveset raisemax force
""", "g")
    flop = prof.sections["flop"]
    assert len(flop) == 2
    assert all(r.cond[0] == "and" for r in flop), "guard must be ANDed into the rules that follow it"
    assert prof.sections["turn"][0].cond[0] != "and" or "raises" not in str(prof.sections["turn"][0].cond)


def test_comments_and_blank_lines_ignored():
    prof = parse_profile("custom\n\n// nothing\npreflop\nWhen others fold force // trailing\n", "c")
    assert len(prof.sections["preflop"]) == 1
    assert prof.sections["preflop"][0].text.lower().startswith("when others")


def test_unknown_symbol_survives_parsing():
    prof = parse_profile("custom\nflop\nWhen havemagicbeans raisemax force\n", "u")
    assert prof.sections["flop"][0].cond == ("sym", "havemagicbeans")
