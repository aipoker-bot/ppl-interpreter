"""ppl-interpreter: run Shanky-style PPL poker profiles against any engine, with a trace of the rule that fired."""
from .parser import Profile, Rule, parse_profile
from .state import BB, GameState, LegalActions, SimpleState, default_table
from .symbols import PPLContext, UnknownSymbol, SYMBOLS
from .bot import PPLBot, eval_cond, load_profile

__all__ = ["Profile", "Rule", "parse_profile", "BB", "GameState", "LegalActions", "SimpleState", "default_table",
           "PPLContext", "UnknownSymbol", "SYMBOLS", "PPLBot", "eval_cond", "load_profile"]
__version__ = "0.1.0"
