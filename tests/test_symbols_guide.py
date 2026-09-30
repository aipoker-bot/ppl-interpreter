"""Card symbols vs the Shanky PPL Guide, Appendix 1 (line = PPLGuide.txt line)."""
import pytest

from ppl_interpreter.symbols import SYMBOLS, PPLContext


class _Hand:
    n = 6

    def __init__(self, hole, board):
        self._hole, self.board = hole.split(), board.split()

    def hole(self, seat):
        return self._hole


CASES = [
    # symbol, hole, board, expected, guide line
    ("overcardsonboard", "Jc 2h", "4s Qs Ad 3s", 2, 3535),
    ("overcardsonboard", "9c 8d", "Kh Ks 2c", 2, 3535),          # paired board card counts twice
    ("havetwopair", "8d 7s", "As Ah 8s", False, 2875),
    ("havetwopair", "Kd 9d", "Kc 4d 9c", True, 3962),
    ("havetrips", "6c Tc", "5h Ts Jc 6s 6d", True, 3959),         # full house still "has trips"
    ("havetrips", "2h 3h", "Qd Jd 6h 6d 6c", False, 3959),        # trips on board do not count
    ("havebottompair", "4s Kc", "4c Tc Kd", True, 3833),
    ("havetopnonboardpairedpair", "8d 7c", "6d 6s 5c 6c 8s", True, 3946),
    ("havetopnonboardpairedpair", "8d 7s", "As Ah 8s", True, 3946),
    ("havebackdoorflushdraw", "Jh Ks", "7h 9h Jd 7d Qs", False, 3808),   # flop only
    ("havebackdoorflushdraw", "Th 7d", "5h 8d 2h", True, 3808),
    ("havebackdoornutflushdraw", "Ts Ad", "Qd 6d 4h Th", False, 3812),  # flop only
    ("haveflushdraw", "Ac 7c", "Kc 4s 6c 9c", True, 3845),          # made flush counts
    ("havenutflushdraw", "Ac 7c", "Kc 4s 6c 9c", True, 3873),
    ("straightflushpossible", "Jc 2h", "4s Qs Ad 3s", False, 4079),
    ("straightflushpossible", "3d Qs", "9d 5s 4s As 2d", True, 4079),  # A-4-5 spades: wheel SF
    ("straightflushpossiblebyothers", "Tc 4c", "Ac Kc Qc", False, 4081),  # guide's own example
    ("straightflushpossiblebyothers", "Kc Ac", "Qd 7c Td Ad 3c", True, 4081),
    ("threecardstraightonboard", "8s Qd", "As 2s 3h", True, 4100),
    ("onlyonestraightpossible", "2c 3d", "As Kd Qh", True, 4024),   # guide: AKQ -> only JT
    ("onlyonestraightpossible", "2c 3d", "Ks Qd Jh", False, 4024),  # guide: KQJ -> AT or T9
    ("onlyonestraightpossible", "Td 2s", "As Js Qc Ks", True, 4024),
    ("morethanonestraightpossibleonturn", "Td 2s", "As Js Qc Ks", False, 3996),
    ("havestraightdraw", "Ad 8s", "Qc 2c Td 2d Jd", True, 3940),    # K or 9: 8 outs
    ("havestraightdraw", "6d Qh", "2h 9h Td 7s Js", True, 3940),    # 8 still an out (Q-high > board 7-J)
    ("haveinsidestraightdraw", "Ts Jh", "Qd 5h 9s", True, 3854),    # also true with a straight draw
    ("haveinsidestraightdraw", "7c 6c", "Td 7h 9s", True, 3854),    # 8 = 4 outs
    ("havenutstraightdraw", "Ad 8s", "Qc 2c Td 2d Jd", False, 3913),  # only K (4 outs) makes the nuts
    ("havenutstraightdraw", "Ts Jh", "Qd 5h 9s", True, 3913),
    ("haveinsidenutstraightdraw", "Ts Jh", "Qd 5h 9s", True, 3850),
    ("haveunderstraight", "6h 2s", "9c 5s 8c Qc 7c", False, 3968),  # 6 is not below the 5
    ("haveunderstraight", "4h 3c", "5d 6s 7c Kd", True, 3968),
    ("havestraight", "4h 6c", "Qd 7h Th 8h 5h", True, 3938),        # straight + flush
    ("havenothing", "9d 4c", "7d 2c 7s", True, 3861),               # board pair is not "a pair"
    ("havenothing", "Qc Kd", "3c 7h 8c Js", False, 3861),           # overcards = 2
    ("havebestkickerorbetter", "Qh 6d", "7c 2c 6s", True, 3825),    # a pair is "better"
    ("havenuts", "Kd 9d", "Kc 4d Ks 9c 6s", True, 3907),
    ("havenuts", "3h Ah", "9c 5h 4h 8h", False, 3907),              # 6h7h straight flush
    ("havenuts", "Ks Kh", "7s Jh Kc", True, 3907),
]


@pytest.mark.parametrize("sym,hole,board,want,line", CASES)
def test_card_symbol_follows_guide(sym, hole, board, want, line):
    ctx = PPLContext(_Hand(hole, board), 0, None, {})
    got = SYMBOLS[sym](ctx)
    assert (got if sym == "overcardsonboard" else bool(got)) == want, f"guide line {line}"
