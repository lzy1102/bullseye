"""
WaveVolSpot - Elliott wave-3 breakout with volume confirmation (long only).

Structure (per bar t, all causal):
- Pivots: centered k=5 high/low; a pivot at bar j is only "known" at j+k.
- H(t): last confirmed pivot-high price (bar h <= t-k).
- L_prev(t): last confirmed pivot-low strictly before h.
- L2(t): lowest low between h+1 and t.
- Wave 1: (H - L_prev) / L_prev >= min_wave (default 8%).
- Wave 2: retrace = (H - L2) / (H - L_prev) in [0.3, 1.0)
  (< 1.0 = wave-1 low never violated, the Elliott hard rule).

Entry (tag 'wave3_pullback'): two-phase breakout-pullback.
- Phase 1 (breakout bar b): daily gate up, wave structure valid, fresh
  cross above H, volume > vol_mult * mean (放量突破, marks the level).
- Phase 2 (entry bar s, b+1..b+max_wait): close back near the FROZEN
  breakout level (bo_H*0.995 <= close <= bo_H*(1+pullback_tol)), gate
  still up, and the count not invalidated (close > bo_Lprev, the
  wave-1 low from bar b). The level is frozen at breakout time on
  purpose: a new higher pivot must not stale the level being retested.
  Buy the retest, not the break.

Exit:
- wave invalidation: retrace >= 1.0 (wave-2 region broken), or
- daily gate turns bear (SMA20 < SMA60).
No DCA, no ROI, no stoploss: the invalidation exit is the stop.
"""
import numpy as np
import pandas as pd
from bullseye.strategy import IStrategy
from pandas import DataFrame


class WaveVolSpot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 60
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = 0.0
    trailing_stop = False

    position_adjustment_enable = False

    # Pivot confirmation window (bars each side).
    pivot_k: int = 5
    # Minimum wave-1 amplitude.
    min_wave: float = 0.08
    # Wave-2 retracement band of wave 1.
    retrace_lo: float = 0.30
    # Volume multiple vs prior 20-day mean (excl. current bar) for the
    # breakout bar. 1.2, not 1.5: the volume spike often lands a bar or
    # two after the actual cross, so the marking bar must not demand it.
    vol_mult: float = 1.2
    vol_window: int = 20
    # Pullback entry band above H and max bars to wait after breakout.
    pullback_tol: float = 0.03
    max_wait: int = 15

    def _wave_frame(self, dataframe: DataFrame) -> DataFrame:
        k = int(self.pivot_k)
        n = len(dataframe)
        high = dataframe["high"].to_numpy()
        low = dataframe["low"].to_numpy()
        close = dataframe["close"].to_numpy()

        df = dataframe.copy()
        # Centered pivots (use future bars -> shift by k before use).
        win = 2 * k + 1
        roll_max = dataframe["high"].rolling(win, center=True).max().to_numpy()
        roll_min = dataframe["low"].rolling(win, center=True).min().to_numpy()
        is_ph = (high == roll_max) & ~np.isnan(roll_max)
        is_pl = (low == roll_min) & ~np.isnan(roll_min)

        H = np.full(n, np.nan)
        L_prev = np.full(n, np.nan)
        L2 = np.full(n, np.nan)
        wave1 = np.full(n, np.nan)
        retrace = np.full(n, np.nan)

        # Confirmed pivot streams (pivot at j visible from j+k on).
        ph_idx = np.where(is_ph)[0]
        pl_idx = np.where(is_pl)[0]
        pl_price = low
        # For each pivot-high, the preceding pivot-low (merge_asof style).
        j = 0
        prev_low_for_ph = {}
        pls = sorted(pl_idx.tolist())
        p = 0
        for h in sorted(ph_idx.tolist()):
            while p < len(pls) and pls[p] < h:
                p += 1
            if p > 0:
                prev_low_for_ph[h] = pls[p - 1]

        # Walk bars once; cur_h = last pivot-high with idx <= t - k.
        ph_sorted = sorted(ph_idx.tolist())
        pi = 0
        run_min = np.inf
        cur_h = -1
        for t in range(n):
            while pi < len(ph_sorted) and ph_sorted[pi] <= t - k:
                cur_h = ph_sorted[pi]
                pi += 1
                # Seed with the whole (h, t] window: bars h+1..t-1 were
                # already seen under the previous H regime.
                run_min = (
                    float(np.min(low[cur_h + 1:t + 1]))
                    if t > cur_h else np.inf
                )
            if cur_h < 0 or cur_h not in prev_low_for_ph:
                continue
            lp = prev_low_for_ph[cur_h]
            H[t] = high[cur_h]
            L_prev[t] = low[lp]
            # Lowest low strictly after h, up to and including bar t.
            if t > cur_h:
                if not np.isfinite(run_min):
                    run_min = float(low[t])
                else:
                    run_min = min(run_min, float(low[t]))
                L2[t] = run_min
            w1 = (H[t] - L_prev[t]) / L_prev[t] if L_prev[t] > 0 else np.nan
            wave1[t] = w1
            if np.isfinite(w1) and w1 > 0 and np.isfinite(L2[t]):
                retrace[t] = (H[t] - L2[t]) / (H[t] - L_prev[t])

        df["wave_H"] = H
        df["wave_Lprev"] = L_prev
        df["wave_L2"] = L2
        df["wave1"] = wave1
        df["retrace"] = retrace
        return df

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma60"] = close.rolling(60).mean()
        dataframe["vol_ma"] = (
            dataframe["volume"].rolling(self.vol_window).mean().shift(1)
        )
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["vol_ma"]
        df = self._wave_frame(dataframe)
        df["wave_ok"] = (
            df["wave_H"].notna()
            & df["wave_Lprev"].notna()
            & (df["wave1"] >= self.min_wave)
            & (df["retrace"] >= self.retrace_lo)
            & (df["retrace"] < 1.0)
        ).fillna(False)
        df["wave_dead"] = (
            df["wave_H"].notna()
            & df["wave_Lprev"].notna()
            & (df["wave1"] >= self.min_wave)
            & (df["retrace"] >= 1.0)
        ).fillna(False)
        # Phase-1 breakout event (marks the level; entry waits for the
        # pullback below).
        gate = (df["ma20"] > df["ma60"]).fillna(False)
        df["bo_event"] = (
            gate
            & df["wave_ok"]
            & (df["close"] > df["wave_H"])
            & (df["close"].shift(1) <= df["wave_H"].shift(1)).fillna(False)
            & (df["vol_ratio"] > self.vol_mult)
            & (df["close"] > df["open"])
            & (df["volume"] > 0)
        )
        # Carry the whole breakout setup forward, frozen at bar b: the
        # level (bo_H) and its wave-1 low (bo_Lprev). A new higher pivot
        # must NOT stale the level currently being retested.
        idx = np.arange(len(df))
        df["bo_H"] = df["wave_H"].where(df["bo_event"]).ffill()
        df["bo_Lprev"] = df["wave_Lprev"].where(df["bo_event"]).ffill()
        df["bo_idx"] = pd.Series(idx, index=df.index).where(
            df["bo_event"]).ffill()
        df["bo_age"] = idx - df["bo_idx"]
        return df

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        gate = (dataframe["ma20"] > dataframe["ma60"]).fillna(False)
        # Phase-2 pullback: back near the FROZEN breakout level within
        # max_wait bars, gate still up, wave-1 low intact.
        in_band = (
            (dataframe["close"] >= dataframe["bo_H"] * 0.995)
            & (dataframe["close"] <= dataframe["bo_H"] * (1 + self.pullback_tol))
        )
        not_invalid = dataframe["close"] > dataframe["bo_Lprev"]
        dataframe.loc[
            (
                gate
                & (dataframe["bo_age"] >= 1)
                & (dataframe["bo_age"] <= self.max_wait)
                & in_band.fillna(False)
                & not_invalid.fillna(False)
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "wave3_pullback")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dead = dataframe["wave_dead"] | (dataframe["ma20"] < dataframe["ma60"])
        dataframe.loc[
            dead.fillna(False) & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "wave_exit")
        return dataframe
