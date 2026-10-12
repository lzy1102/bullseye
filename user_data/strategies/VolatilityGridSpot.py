# VolatilityGridSpot - A-share spot port of VolatilityGridStrategyV3.
#
# Port notes (crypto-futures -> A-share spot):
# - LONG ONLY: can_short=False; all short grid/exit/adjust branches removed.
# - Leverage fixed at 1.0 (leverage_value removed). All thresholds below
#   are therefore TRUE percentages (V3's were implicitly /3):
#   adjust_profit 0.04 = real -4% drawdown trigger (was -12% at 3x).
# - minimal_roi ladder rescaled 0.20->0.08 top (spot daily scale).
# - Trailing 0.004/0.03 (crypto-minute scale, whipsaws daily stocks) ->
#   0.03/0.05 with offset gate (GridBank10-verified). Static stoploss 0
#   with a -0.08 disaster net (V3 had -1 = effectively none).
# - Wall-clock hours rescaled for 4h trading days: stale_hours 48->240,
#   gap_threshold_h 48->240 (a weekend alone is 48+ wall hours in A-shares;
#   old values misfired every Monday). lock_adjust_time unchanged (1 wall
#   hour either way).
# - min_atr_ratio default 0.006->0.002 (bank 30m ATR ratios run ~0.2-0.4%;
#   verify against data, tune later). min_gap_ratio default 0.009->0.0
#   (our benchmark: gap filters cost more than they save).
# - max_dca_count default 7->5 (A-share lots: 100k/(7 slots x 7 adds) slices
#   fall below 1 lot on mid-price names and silently never fill).
# - rsi_overbought removed (short-only param). max_loss_pct removed (dead
#   in V3: defined but never referenced). min_roi_reached removed (our
#   engine never calls it; ROI lives in minimal_roi).
# - Framework compat (mirrors the TrendGrid spot port):
#   bullseye imports; __init__(config=None); self.config set when given;
#   self.max_open_trades -> config dict lookup; trade.open_date (no _utc);
#   per-run fill ledger (engine has no order objects); closed-trade ledger
#   fed by order_filled (sell side) for loss_throttle/gap_guard — V3 used
#   freqtrade's Trade.get_trades_proxy, which does not exist here.

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import talib as ta
from bullseye.strategy import (
    IStrategy,
    BooleanParameter,
    DecimalParameter,
    IntParameter,
    informative,
)
from pandas import DataFrame

logger = logging.getLogger(__name__)


# 波动率网格现货版 — 只做多(can_short=False)
# 入场：1d趋势(>=0, 含震荡) + ATR动态网格 + RSI超卖；出场：趋势反转/stale/保本/trailing
class VolatilityGridSpot(IStrategy):
    # ROI ladder / stoploss / trailing are tuned via same-named
    # descriptors below (spaces roi/stoploss/trailing) and synced into
    # these plain engine-facing attributes every run. The json mirrors
    # the values in its roi/stoploss/trailing sections for readability;
    # the buy section carries the descriptor values (the only section
    # apply_params_file reads for descriptors).
    minimal_roi = {
        "0": 0.08,
        "60": 0.04,
        "180": 0.02,
    }

    stoploss: float = -0.08
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True

    roi_0 = DecimalParameter(0.03, 0.15, default=0.08, space="roi",
                             optimize=True)
    roi_60 = DecimalParameter(0.01, 0.08, default=0.04, space="roi",
                              optimize=True)
    roi_180 = DecimalParameter(0.005, 0.05, default=0.02, space="roi",
                               optimize=True)
    sl_level = DecimalParameter(-0.15, -0.03, default=-0.08,
                                space="stoploss", optimize=True)
    trail_pos = DecimalParameter(0.01, 0.06, default=0.03,
                                 space="trailing", optimize=True)
    trail_offset = DecimalParameter(0.03, 0.10, default=0.05,
                                    space="trailing", optimize=True)
    use_custom_stoploss = False
    timeframe = '30m'
    can_short = False
    startup_candle_count = 500

    grid_levels = IntParameter(3, 10, default=5, space="buy", optimize=True)
    grid_atr_multiplier = DecimalParameter(0.3, 2.0, default=0.8, space="buy", optimize=True)
    max_dca_count = IntParameter(2, 8, default=5, space="buy", optimize=True)
    min_atr_ratio = DecimalParameter(0.001, 0.01, default=0.002, space="buy", optimize=True)
    rsi_period = IntParameter(7, 21, default=14, space="buy", optimize=True)
    rsi_oversold = IntParameter(20, 45, default=35, space="buy", optimize=True)
    atr_period = IntParameter(7, 28, default=14, space="buy", optimize=True)
    sma_timeperiod = IntParameter(5, 20, default=9, space="buy", optimize=True)
    min_gap_ratio = DecimalParameter(0.0, 0.02, default=0.0, space="buy", optimize=True)
    adjust_profit = DecimalParameter(0.02, 0.10, default=0.04, space="buy", optimize=True)
    rebound_pct = DecimalParameter(0.001, 0.02, default=0.005, space="buy", optimize=True)
    lock_adjust_time = IntParameter(10, 60, default=36, space="buy", optimize=True)
    min_roi_param = DecimalParameter(0.02, 0.08, default=0.045, space="buy", optimize=True)
    break_even_pct = IntParameter(2, 10, default=5, space="buy", optimize=True)
    break_even_roi = DecimalParameter(0.005, 0.03, default=0.015, space="buy", optimize=True)

    # 老单止盈（暴露到 json 便于调参）
    use_stale_exit = BooleanParameter(default=True, space="buy", optimize=True)
    stale_hours = IntParameter(24, 720, default=240, space="buy", optimize=True)
    stale_roi = DecimalParameter(0.0, 0.05, default=0.015, space="buy", optimize=True)
    stale_min_entries = IntParameter(0, 7, default=2, space="buy", optimize=True)

    # 空窗降仓（暴露到 json）
    use_gap_guard = BooleanParameter(default=True, space="buy", optimize=True)
    gap_threshold_h = IntParameter(24, 720, default=240, space="buy", optimize=True)
    gap_stake_factor = DecimalParameter(0.2, 1.0, default=0.4, space="buy", optimize=True)

    # 深网格减仓：偏离SMA>=deep_grid_levels格时首仓打折
    use_risk_size = BooleanParameter(default=True, space="buy", optimize=False)
    risk_stake_factor = DecimalParameter(0.2, 1.0, default=0.5, space="buy", optimize=True)
    deep_grid_levels = IntParameter(2, 5, default=3, space="buy", optimize=True)

    # 亏损周期调仓：距上次亏损>=loss_throttle_start笔首仓打折
    use_loss_throttle = BooleanParameter(default=True, space="buy", optimize=False)
    loss_throttle_start = IntParameter(8, 30, default=18, space="buy", optimize=True)
    throttle_factor = DecimalParameter(0.2, 1.0, default=0.5, space="buy", optimize=True)

    def __init__(self, config: dict = None) -> None:
        # Per-run ledgers (engine has no order objects / trade history):
        # _fills mirrors DCA fills for counting, _closed records closes
        # (fed by order_filled) for loss_throttle/gap_guard.
        self._fills: Dict[str, List[Dict[str, Any]]] = {}
        self._closed: List[Dict[str, Any]] = []
        if config is not None:
            self.config = config
        logger.info("VolatilityGridSpot (A-share spot port, long only)")

    @informative('1d')
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for period in [5, 10, 20, 30]:
            dataframe[f'ma_{period}d'] = ta.SMA(dataframe['close'], timeperiod=period)
        gap = float(self.min_gap_ratio.value)
        ma_aligned = (
            (dataframe['ma_5d'] > dataframe['ma_10d'] * (1 + gap)) &
            (dataframe['ma_10d'] > dataframe['ma_20d'] * (1 + gap)) &
            (dataframe['ma_20d'] > dataframe['ma_30d'] * (1 + gap))
        )
        dataframe['trend'] = 0
        dataframe.loc[ma_aligned, 'trend'] = 1
        bear_aligned = (
            (dataframe['ma_5d'] < dataframe['ma_10d'] * (1 - gap)) &
            (dataframe['ma_10d'] < dataframe['ma_20d'] * (1 - gap)) &
            (dataframe['ma_20d'] < dataframe['ma_30d'] * (1 - gap))
        )
        dataframe.loc[bear_aligned, 'trend'] = -1
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Sync hyperopt-tuned knobs into the plain attributes the engine
        # reads directly (a Parameter object would break its arithmetic).
        self.minimal_roi = {
            "0": float(self.roi_0.value),
            "60": float(self.roi_60.value),
            "180": float(self.roi_180.value),
        }
        self.stoploss = float(self.sl_level.value)
        self.trailing_stop_positive = float(self.trail_pos.value)
        self.trailing_stop_positive_offset = float(self.trail_offset.value)
        dataframe['sma'] = ta.SMA(dataframe['close'], timeperiod=self.sma_timeperiod.value)
        dataframe['atr'] = ta.ATR(dataframe['high'], dataframe['low'], dataframe['close'], timeperiod=self.atr_period.value)
        dataframe['atr_ratio'] = dataframe['atr'] / dataframe['close']
        dataframe['rsi'] = ta.RSI(dataframe['close'], timeperiod=self.rsi_period.value)
        for period in [5, 10, 20]:
            dataframe[f'mam_{period}'] = ta.SMA(dataframe['close'], timeperiod=period)
        gap = float(self.min_gap_ratio.value)
        ma_aligned = (
            (dataframe['mam_5'] > dataframe['mam_10'] * (1 + gap)) &
            (dataframe['mam_10'] > dataframe['mam_20'] * (1 + gap))
        )
        dataframe['trend_current'] = 0
        dataframe.loc[ma_aligned, 'trend_current'] = 1
        bear_aligned = (
            (dataframe['mam_5'] < dataframe['mam_10'] * (1 - gap)) &
            (dataframe['mam_10'] < dataframe['mam_20'] * (1 - gap))
        )
        dataframe.loc[bear_aligned, 'trend_current'] = -1
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        sma = dataframe['sma']
        close = dataframe['close']
        trend_1d = (dataframe['trend_1d'] if 'trend_1d' in dataframe
                    else pd.Series(0, index=dataframe.index))
        atr_ratio = dataframe['atr_ratio']
        rsi = dataframe['rsi']
        dynamic_grid_size = atr_ratio * self.grid_atr_multiplier.value
        volatile_enough = atr_ratio >= self.min_atr_ratio.value
        # Spot long-only: trend up OR sideways (no shorts to cover the
        # downside, so sideways chop is tradable grid territory).
        grid_long_trigger = (
            (trend_1d >= 0) &
            volatile_enough &
            (rsi <= self.rsi_oversold.value) &
            pd.concat([close <= sma * (1 - i * dynamic_grid_size) for i in range(1, self.grid_levels.value + 1)], axis=1).any(axis=1)
        )
        dataframe.loc[
            grid_long_trigger & (dataframe['volume'] > 0),
            ['enter_long', 'enter_tag']
        ] = (1, 'grid_long')
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def leverage(self, pair: str, current_time: datetime, current_rate: float, proposed_leverage: float, max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        # A-share spot: no leverage.
        return 1.0

    def _closed_trades(self) -> List[Dict[str, Any]]:
        """Own closed-trade ledger (engine exposes no trade history)."""
        return sorted(self._closed, key=lambda c: c["date"])

    def order_filled(self, pair: str, trade, order, current_time, **kwargs) -> None:
        # Feed the closed-trade ledger for loss_throttle/gap_guard.
        try:
            if getattr(order, "ft_order_side", "") == "sell":
                profit = None
                try:
                    if getattr(trade, "close_rate", None):
                        profit = trade.calc_profit(trade.close_rate)
                    else:
                        profit = trade.calc_profit(float(order.price))
                except Exception:
                    profit = None
                self._closed.append({"date": current_time, "profit": profit})
                self._closed = self._closed[-500:]
        except Exception:
            pass

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float, proposed_stake: float, min_stake: float | None, max_stake: float, leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        max_open = (self.config or {}).get("max_open_trades", 3) if isinstance(getattr(self, "config", None), dict) else 3
        stake = self.wallets.get_total_stake_amount() / (max_open * self.max_dca_count.value)
        # 亏损周期调仓：距上次亏损>=N笔说明进入高亏损窗口
        if self.use_loss_throttle.value:
            try:
                since_loss = 0
                for ct in reversed(self._closed_trades()):
                    if ct.get("profit") is None:
                        break
                    if ct["profit"] <= 0:
                        break
                    since_loss += 1
                if since_loss >= self.loss_throttle_start.value:
                    logger.info(f"{pair} {current_time} 距上次亏损{since_loss}笔>={self.loss_throttle_start.value}，首仓x{self.throttle_factor.value}")
                    stake *= self.throttle_factor.value
            except Exception as e:
                logger.error(f"throttle {pair} error: {e}")
        # 深网格减仓：入场偏离>=N格属于高DCA率组
        if self.use_risk_size.value:
            try:
                df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
                last = df.iloc[-1]
                sma = float(last['sma'])
                close = float(last['close'])
                atr = float(last['atr_ratio'])
                dynamic_grid = atr * self.grid_atr_multiplier.value
                depth = abs(close - sma) / sma / dynamic_grid if dynamic_grid > 0 else 0
                if depth >= self.deep_grid_levels.value:
                    logger.info(f"{pair} {current_time} 深网格入场 depth={depth:.1f}格>={self.deep_grid_levels.value}，首仓x{self.risk_stake_factor.value}")
                    stake *= self.risk_stake_factor.value
            except Exception as e:
                logger.error(f"risk_size {pair} error: {e}")
        if self.use_gap_guard.value:
            try:
                closed = self._closed_trades()
                if closed:
                    last_close = max(ct["date"] for ct in closed)
                    gap_h = (pd.to_datetime(current_time) - pd.to_datetime(last_close)).total_seconds() / 3600
                    if gap_h >= self.gap_threshold_h.value:
                        logger.info(f"{pair} {current_time} 空窗{gap_h:.1f}h>={self.gap_threshold_h.value}h, 首单降仓x{self.gap_stake_factor.value}")
                        stake *= self.gap_stake_factor.value
            except Exception as e:
                logger.error(f"gap_guard {pair} error: {e}")
        return stake

    def custom_exit(self, pair: str, trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> str | bool | None:
        """
        固定百分比网格的止盈出场逻辑（现货只做多）
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        sma_current = dataframe['sma'].iloc[-1]
        trend_1d_current = (dataframe['trend_1d'].iloc[-1]
                            if 'trend_1d' in dataframe else 0)
        if pd.isna(sma_current) or pd.isna(trend_1d_current):
            return None
        if trend_1d_current < 0:
            logger.info(f"{pair} {current_time} 趋势转空，强制平仓（{current_profit:.2%}）")
            return "trend_reversed_short"
        # 老单转正即离场（仅针对补仓过的老单）
        if self.use_stale_exit.value:
            try:
                held_h = (pd.to_datetime(current_time) - pd.to_datetime(trade.open_date)).total_seconds() / 3600
            except Exception:
                return None
            if held_h >= self.stale_hours.value and trade.nr_of_successful_entries >= self.stale_min_entries.value and current_profit >= self.stale_roi.value:
                logger.info(f"{pair} {current_time} {current_profit:.2%} 持仓{held_h:.1f}h>={self.stale_hours.value}h且转正({trade.nr_of_successful_entries}次补仓)，老单止盈离场")
                return "stale_profit"
        if self.break_even_pct.value > 0 and trade.nr_of_successful_entries >= self.break_even_pct.value:
            if current_profit >= self.break_even_roi.value:
                logger.info(f"{pair} 补仓{trade.nr_of_successful_entries}次，保本平仓")
                return "break_even_profit"
        if current_profit < self.min_roi_param.value:
            return None
        if trade.nr_of_successful_entries >= 2:
            logger.info(f"{pair} 补仓{trade.nr_of_successful_entries}次，盈利平仓")
            return "max_dca_reached"
        return None

    def stake_if_stable(self, trade, dataframe: DataFrame, current_rate: float) -> bool:
        """
        仅在价格"企稳"后允许补仓：从开单以来最低价反弹>=rebound个 ATR。
        """
        df_after = dataframe[dataframe['date'] >= pd.to_datetime(trade.open_date)]
        if df_after.empty:
            return False
        atr_now = df_after['atr'].iloc[-1] if 'atr' in df_after.columns else np.nan
        if atr_now != atr_now or atr_now <= 0 or current_rate <= 0:
            return False
        rebound_need = float(self.rebound_pct.value) * atr_now
        extreme = df_after['low'].min()
        return bool((current_rate - extreme) >= rebound_need)

    def _fill_ledger(self, trade) -> List[Dict[str, Any]]:
        key = f"{trade.pair}:{trade.id}"
        entries = self._fills.get(key)
        if entries is None:
            entries = [{
                "price": trade.open_rate,
                "stake": trade.stake_amount,
                "time": trade.open_date,
            }]
            self._fills[key] = entries
        return entries

    def adjust_trade_position(self, trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: float | None, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_entry_profit: float, current_exit_profit: float,
                              **kwargs) -> float | None | tuple[float | None, str | None]:
        try:
            if getattr(trade, "open_orders", None):
                return None
            filled_entries = self._fill_ledger(trade)
            if len(filled_entries) == 0:
                return None
            stake_amount = filled_entries[0]["stake"]
            count_of_entries = trade.nr_of_successful_entries
            dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
            if dataframe is None or dataframe.empty:
                return None
            if not self.stake_if_stable(trade=trade, dataframe=dataframe,
                                        current_rate=current_rate):
                return None
            if count_of_entries >= self.max_dca_count.value:
                return None
            last_entry = filled_entries[-1]
            timestamp_sec = int(pd.to_datetime(last_entry["time"]).timestamp())
            if int(pd.to_datetime(current_time).timestamp()) - timestamp_sec <= self.lock_adjust_time.value * 100:
                return None
            atr_now = dataframe['atr'].iloc[-1] if 'atr' in dataframe.columns else np.nan
            if atr_now != atr_now or atr_now <= 0 or current_rate <= 0:
                return None
            atr_pct = atr_now / current_rate
            if (current_profit / (trade.leverage or 1.0)) >= -float(self.adjust_profit.value) * atr_pct:
                return None
            filled_entries.append({
                "price": current_rate,
                "stake": stake_amount,
                "time": current_time,
            })
            return stake_amount, "{0}补仓".format(str(count_of_entries))
        except Exception as e:
            logger.error(f"adjust_trade_position {trade.pair} 补仓逻辑报错,错误信息 {e}")
            return None
