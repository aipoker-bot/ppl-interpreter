# ppl-interpreter

An interpreter for PPL, the rule language most commercial online poker bots ran on between roughly 2005 and 2015 (the Shanky Technologies dialect: `When <condition> <action> force`). Give it a profile and a decision point from any poker engine; it returns the action and the exact rule that fired.

I wrote it to keep those profiles playable at [aipoker.bot](https://aipoker.bot/bots), where sixteen of them sit at the tables and show their rule after every action. This package is the interpreter alone, with two small teaching profiles. It does not ship any commercial profiles; see the note at the end.

```
pip install git+https://github.com/aipoker-bot/ppl-interpreter
```

## Use

```python
from ppl_interpreter import LegalActions, SimpleState, default_table, load_profile

bot, report = load_profile("profiles/teaching_tight.txt")
report            # {'rules': 28, 'coverage_pct': 100.0, ...}

spot = SimpleState(holes=[["8h", "8d"], ["Ac", "Kd"]], board=["8c", "Kh", "2s"],
                   street="flop", pot=12, bets=[0, 6])
legal = LegalActions(fold=True, check=False, call_amount=6, raise_min=12, raise_max=194)

bot.reset_hand()
bot.decide_ppl(spot, seat=0, la=legal, table=default_table(spot.n))
# ('raise', 194)
bot.thoughts[-1]["reason"]
# 'rule L15: haveset or havetoptwopair raisemax force'
```

`examples/trace_one_decision.py` is this, runnable.

### Plugging in your engine

`decide_ppl` takes anything that satisfies `GameState` (see `ppl_interpreter/state.py`): `n`, `street`, `board`, `pot`, and `hole / stack / bet / position / alive` per seat, with amounts in chips and `BB = 2`. `LegalActions` says what the engine allows right now; raise amounts are total "to" sizes on the current street. The `table` dict carries tallies the language expects but a hand state doesn't have (raises this street, the bot's own last action, who raised first); `default_table(n)` gives you the zeros, your table loop keeps them current. `SimpleState` is a frozen dataclass for tests and one-off evaluation.

Actions come back as `("fold", None)`, `("cc", None)` (check or call, whichever is legal) or `("raise", total_to)`. Sizes are BY an amount over the current level, in big blinds (`raise 3`), percent of pot (`bet 66%`), `raisemin`, `raisemax`. Action semantics follow the PPL guide: `fold` checks when checking is free, and the `bet` family calls when a bet is already in (bet is never available preflop), while `raise` raises.

When no rule matches, the bot checks if it can and folds otherwise. The original bot fell through to Shanky's default profile at that point, which ships encrypted, so profiles written as tweaks on top of it leave many spots uncovered. Pass `fallback=fn` to `load_profile` or `PPLBot`, with `fn(state, seat, legal) -> action` to play those spots with your own logic; `bot.last_src` says whether the last action came from a rule (with its line), the fallback, or the default. Option-menu settings saved above `custom` (`DefaultBetSizeFlop = 80` and so on) are parsed into `profile.options` for your fallback to use; the interpreter itself doesn't execute them, since most are menu item numbers for Shanky's closed default engine.

## What is implemented

- **Parser**: `custom` header, street sections, `When ... force` rules, `others`, bare `When <cond>` lines as guards (ANDed into the rules below them, Shanky-style), rules wrapped across lines, `//` comments, user variables (`When <cond> UserFoo`), `hand = AK suited`, `board = A K`.
- **Symbols**: 139, following the Shanky PPL guide with OpenPPL as the tiebreaker for edge cases: betting (`amounttocall`, `potsize`, `raises`, `botslastaction`...), position (`position`, `inbigblind`, `stilltoact`...), board texture (`paironboard`, `flushpossible`, `straightpossibleonturn`, `uncoordinatedflop`...), made hands (`havetoppair`, `haveoverpair`, `haveset`, `havenutflush`, `havenuts`...), draws and kickers. The full list is `SYMBOLS` in `ppl_interpreter/symbols.py`. Amount symbols are in big blinds. Hand evaluation uses `phevaluator`.
- **Unknown symbols never crash a table**: the rule evaluates false, the name is counted in `bot.unknown_symbols`, and `load_profile` reports coverage before you sit the bot down.

Not implemented: MTT/SNG-specific symbols (`stacksize`-relative tournament logic, `nbetsize` variants), limit-hold'em profiles, and a handful of exotic OpenPPL additions. Coverage on the sixteen commercial cash profiles used at aipoker.bot is 100%; on tournament profiles it isn't, and the report will tell you.

## Tests

```
pip install -e ".[test]"
pytest
```

Parser tests, decision tests on frozen spots, and symbol tests built from the worked examples in the PPL guide, each citing the guide line it checks (no engine, no network). If you have profiles of your own, `load_profile` on each is the quickest conformance check.

## On commercial profiles

The Shanky profiles of that era were sold, not published, and I don't redistribute them. The two profiles in `profiles/` were written for this repository and are MIT like the code. If you own commercial profiles, they should load; if a symbol is missing, the coverage report names it and an issue with the symbol name is welcome.

MIT.
