"""Evaluate a profile on one frozen spot and print the rule that fired. No engine needed. Run: python examples/trace_one_decision.py"""
from pathlib import Path

from ppl_interpreter import LegalActions, SimpleState, default_table, load_profile

bot, report = load_profile(Path(__file__).resolve().parent.parent / "profiles" / "teaching_tight.txt")
print(f"{report['rules']} rules, {report['coverage_pct']}% of them use only implemented symbols")

# Flop, heads-up, hero holds 8-8 on 8-K-2 and faces a 6-chip bet into 12 (BB = 2 chips)
spot = SimpleState(holes=[["8h", "8d"], ["Ac", "Kd"]], board=["8c", "Kh", "2s"], street="flop", pot=12, bets=[0, 6])
legal = LegalActions(fold=True, check=False, call_amount=6, raise_min=12, raise_max=194)

bot.reset_hand()
kind, amount = bot.decide_ppl(spot, 0, legal, default_table(spot.n))
print("decision:", kind, amount)
print("trace:   ", bot.thoughts[-1]["reason"])
