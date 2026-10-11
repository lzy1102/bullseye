"""BaseSpotBanks - bank-universe variant of BaseSpot.

Identical logic (imported); separate file so auto-discovery pairs it
with its own params file (BaseSpotBanks.json, gate 25/110 tuned on
banks 2020-2023) while BaseSpot.json keeps the leaders-tuned 8/58
gate. Discovery is per-FILE: a subclass defined inside BaseSpot.py
would silently reuse BaseSpot.json.
"""
try:
    # Production: engine puts user_data/ on sys.path before import.
    from strategies.BaseSpot import BaseSpot
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.BaseSpot import BaseSpot


class BaseSpotBanks(BaseSpot):
    """Bank gate variant; all behavior inherited from BaseSpot."""
