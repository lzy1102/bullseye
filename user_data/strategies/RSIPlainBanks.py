"""RSIPlainBanks - bank-universe variant of RSIPlain.

Identical logic; separate file so auto-discovery pairs it with its
own params file (RSIPlainBanks.json, 10/39/82 tuned on banks) while
RSIPlain.json keeps the leaders-tuned 16/35/80. Discovery is per-FILE.
"""
try:
    # Production: engine puts user_data/ on sys.path before import.
    from strategies.RSIPlain import RSIPlain
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.RSIPlain import RSIPlain


class RSIPlainBanks(RSIPlain):
    """Bank RSI variant; all behavior inherited from RSIPlain."""
