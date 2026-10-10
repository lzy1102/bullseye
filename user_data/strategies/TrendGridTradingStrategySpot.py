# pyarmor: no-spm-mode
# pyarmor: exclude-class IStrategy
# pyarmor: exclude-method populate_indicators buy_routine

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from datetime import datetime
import numpy as np
import talib as ta
from bullseye.strategy import (
    IStrategy,
    DecimalParameter,
    IntParameter,
    informative,
)
from pandas import DataFrame
from dateutil import parser

logger = logging.getLogger(__name__)


# 趋势网格现货版 — 核心思想：同 TrendGridTradingStrategyFutures，但只做多(can_short=False)
# 入场：1d趋势 + SMA固定%网格做多；出场：趋势反转/保本/trailing；无做空网格
class TrendGridTradingStrategySpot(IStrategy):
    # 定义策略的参数

    # ROI/trailing taken from the tuned TrendGridTradingStrategySpot.json,
    # then raised to the 10% target: only +10% exits (any duration).
    # Trend-only (grid leg removed): entries on 0->1 flips, exits on
    # -1 reversal. ROI / trailing off; stoploss kept as a safety net.
    minimal_roi: dict = {}

    stoploss: float = -0.08
    trailing_stop = False
    # process_only_new_candles = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.10
    trailing_only_offset_is_reached = True  # 只有达到 offset 才开始跟踪
    # use_custom_stoploss = True
    timeframe = '30m'

    # min_roi = 0.01  # 最小盈利
    # 定义震荡区间识别参数
    adx_length = 14
    adx_threshold = 20
    # 计算最大需求：30日均线 + ATR周期 + 安全余量
    startup_candle_count = 500  # 至少250根1小时K线（约10天）

    # Defaults aligned with the tuned TrendGridTradingStrategySpot.json
    sma_timeperiod = IntParameter(5, 20, default=9, space="buy", optimize=True)
    max_dca_count = IntParameter(1, 10, default=2, space="buy", optimize=True)  # Maximum number of DCA attempts
    grid_levels = IntParameter(5, 20, default=5, space="buy", optimize=True)
    # Grid rungs in ATR multiples (replaces fixed grid_long_size): rung i
    # sits at sma * (1 - i * mult * atr/close). Adaptive to volatility.
    grid_atr_mult = DecimalParameter(0.5, 4.0, default=1.0, space="buy", optimize=True)
    # DCA trigger in ATR multiples of drawdown from average cost.
    adjust_atr_mult = DecimalParameter(0.5, 4.0, default=1.0, space="buy", optimize=True)
    min_roi = DecimalParameter(0.01, 0.03, default=0.015, space="buy", optimize=True)
    # Stabilization rebound in ATR multiples (replaces fixed rebound_pct).
    rebound_atr_mult = DecimalParameter(0.1, 2.0, default=0.5, space="buy", optimize=True)
    lock_adjust_time = IntParameter(3, 60, default=36, space="buy", optimize=True)
    min_gap_ratio = DecimalParameter(0.001, 0.01, default=0.009, space="buy", optimize=True)
    # 几次追仓后触发回本平仓
    break_even_pct = IntParameter(2, 10, default=5, space="buy", optimize=True)
    # 触发回本平仓的盈利率
    break_even_roi = DecimalParameter(0.005, 0.03, default=0.005, space="buy", optimize=True)
    # 趋势反转最大亏损，小于这个值，可以平仓,负数
    max_loss_pct = DecimalParameter(-0.05, -0.005, default=-0.05, space="buy", optimize=True)
    can_short = False

    # Bollinger early-exit parameters (exit leg only, 30m frame).
    boll_period: int = 20
    boll_std: float = 2.0

    # custom_exit = True
    use_custom_stoploss = False


    def __init__(self, config: dict = None) -> None:
        # Bullseye instantiates strategies without args; keep a per-run
        # ledger of fills for DCA counting (engine has no order objects).
        self._fills: Dict[str, List[Dict[str, Any]]] = {}
        if config is not None:
            self.config = config
        logger.info(
            f"初始化，各个参数 最新盈利率{self.min_roi.value} "
            f"仓位{self.max_dca_count.value}"
        )

    @informative('1d')
    def populate_indicators_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Engine executes this on the 1d frame and merges the result back
        # lookahead-safe (columns land as trend_1d / ma_5d_1d / ...).
        # ========== 1. 基础MA计算 ==========
        for period in [5, 10, 20, 30]:
            dataframe[f'ma_{period}d'] = ta.SMA(dataframe['close'], timeperiod=period)

        gap = float(self.min_gap_ratio.value)
        # ========== 3. 多头排列 + 强度判断（ma5/10/20/30） ==========
        ma_aligned = (
            (dataframe['ma_5d'] > dataframe['ma_10d'] * (1 + gap))
            & (dataframe['ma_10d'] > dataframe['ma_20d'] * (1 + gap))
            & (dataframe['ma_20d'] > dataframe['ma_30d'] * (1 + gap))
        )
        dataframe['trend'] = 0
        dataframe.loc[ma_aligned, 'trend'] = 1
        # ========== 4. 空头排列 + 强度判断 ==========
        bear_aligned = (
            (dataframe['ma_5d'] < dataframe['ma_10d'] * (1 - gap))
            & (dataframe['ma_10d'] < dataframe['ma_20d'] * (1 - gap))
            & (dataframe['ma_20d'] < dataframe['ma_30d'] * (1 - gap))
        )
        dataframe.loc[bear_aligned, 'trend'] = -1
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        trend_now = dataframe['trend_1d'].iloc[-1] if 'trend_1d' in dataframe else 'n/a'
        logger.info(
            f"{metadata['pair']} 1天时间框架，当前趋势 {trend_now}")
        # 计算 ADX 指标
        dataframe['adx'] = ta.ADX(dataframe['high'], dataframe['low'], dataframe['close'], timeperiod=14)
        dataframe['plus_di'] = ta.PLUS_DI(dataframe['high'], dataframe['low'], dataframe['close'], timeperiod=14)
        dataframe['minus_di'] = ta.MINUS_DI(dataframe['high'], dataframe['low'], dataframe['close'], timeperiod=14)


        dataframe['sma'] = ta.SMA(dataframe['close'], timeperiod=self.sma_timeperiod.value)
        dataframe['sma_low'] = ta.SMA(dataframe['low'], timeperiod=self.sma_timeperiod.value)
        dataframe['sma_high'] = ta.SMA(dataframe['high'], timeperiod=self.sma_timeperiod.value)
        dataframe['sma_open'] = ta.SMA(dataframe['open'], timeperiod=self.sma_timeperiod.value)

        dataframe['atr'] = ta.ATR(
            dataframe['high'], dataframe['low'], dataframe['close'],
            timeperiod=14)

        bb_mid = dataframe['close'].rolling(self.boll_period).mean()
        bb_sd = dataframe['close'].rolling(self.boll_period).std()
        dataframe['bb_lower'] = bb_mid - self.boll_std * bb_sd

           # ========== 1. 基础MA计算 ==========
        for period in [5, 10,20]:
            dataframe[f'mam_{period}'] = ta.SMA(dataframe['close'], timeperiod=period)
            # ========== 2. 趋势强度参数 ==========
            # 核心：设置最小间距阈值（避免粘连）
        # 可根据市场调整：加密货币0.2%-0.5%，外汇0.05%-0.2%
        # ========== 3. 多头排列 + 强度判断（ma5/10/20） ==========
        ma_aligned = (
                (dataframe['mam_5'] > dataframe['mam_10'] * (1 + self.min_gap_ratio.value)) &
                (dataframe['mam_10'] > dataframe['mam_20'] * (1 + self.min_gap_ratio.value))
                # (dataframe['ma_20'] > dataframe['ma_30'] * (1 + self.min_gap_ratio.value))
        )
        dataframe['trend_current'] = 0
        dataframe.loc[ma_aligned, 'trend_current'] = 1
        # ========== 5. 空头趋势判断（对称逻辑） ==========
        # ========== 4. 空头排列 + 强度判断 ==========
        bear_aligned = (
                (dataframe['mam_5'] < dataframe['mam_10'] * (1 - self.min_gap_ratio.value)) &
                (dataframe['mam_10'] < dataframe['mam_20'] * (1 - self.min_gap_ratio.value))
                # (dataframe['ma_20'] < dataframe['ma_30'] * (1 - self.min_gap_ratio.value))
        )
        dataframe.loc[bear_aligned, 'trend_current'] = -1

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        sma = dataframe['sma']
        close = dataframe['close']
        # Without 1d data (e.g. in-memory runs) fall back to sideways: the
        # grid leg still works, only the daily filter is inert.
        trend_1d = (dataframe['trend_1d'] if 'trend_1d' in dataframe
                    else pd.Series(0, index=dataframe.index))
        prev_trend = trend_1d.shift(1)
        trend_long_trigger = (
                (trend_1d == 1) &  # 多头趋势
                (prev_trend == 0) &  # 上一个周期是震荡
                (dataframe['volume'] > 0)
        )
        logger.info(f"{metadata['pair']} 当前趋势是否做多 {trend_long_trigger.iloc[-1]}")
        trend_short_trigger = (
                (trend_1d == -1) &  # 空头趋势
                (prev_trend == 0) &  # 上一个周期是震荡
                (dataframe['volume'] > 0)
        )
        logger.info(f"{metadata['pair']} 当前趋势是否做空 {trend_short_trigger.iloc[-1]}")

        # ========== 应用信号：只做趋势转多（网格入场已移除） ==========
        dataframe.loc[
            trend_long_trigger &
            (dataframe['volume'] > 0),
            ['enter_long', 'enter_tag']
        ] = (1, 'trend_long')

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    # 开仓金额
    def custom_stake_amount(
            self,
            pair: str,
            current_time: datetime,
            current_rate: float,
            proposed_stake: float,
            min_stake: float | None,
            max_stake: float,
            leverage: float,
            entry_tag: str | None,
            side: str,
            **kwargs,
    ) -> float:
        # self.wallets.get_available_stake_amount()
        # 计算每次交易的金额为账户余额的 1 / (max_open_trades * 10)
        max_open = (self.config or {}).get("max_open_trades", 3)
        return self.wallets.get_total_stake_amount() / (max_open * self.max_dca_count.value)


    def custom_exit(
            self,
            pair: str,
            trade,
            current_time: datetime,
            current_rate: float,
            current_profit: float,
            **kwargs,
    ) -> str | bool | None:
        """
        固定百分比网格的止盈出场逻辑
        """
        # ========== 1. 获取当前数据 ==========
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

        # 当前值（必须加 .iloc[-1]）
        sma_current = dataframe['sma'].iloc[-1]
        trend_1d_current = (dataframe['trend_1d'].iloc[-1]
                            if 'trend_1d' in dataframe else 0)

        # 保护：检查NaN
        if pd.isna(sma_current) or pd.isna(trend_1d_current):
            return None

        # ========== 2. 趋势反转强制平仓（不看盈亏） ==========
        if trend_1d_current < 0:
            logger.info(f"{pair} {current_time} 趋势转空，强制平仓（{current_profit:.2%}）")
            return "trend_reversed_short"

        # ========== 3. 布林下轨提前离场（动量死亡，不等日线确认） ==========
        if ('bb_lower' in dataframe and 'close' in dataframe
                and dataframe['close'].iloc[-1] < dataframe['bb_lower'].iloc[-1]):
            logger.info(f"{pair} {current_time} 跌破布林下轨，提前离场（{current_profit:.2%}）")
            return "boll_dead"

        return None

    # ------------------------------------------------------------------
    # 工具方法：判断是否“企稳”并返回建议补仓数量
    #   做多：从开单以来最低价反弹 >= rebound_atr_mult 个 ATR 才允许补仓
    #   返回值：True 企稳可补，False 等待
    # ------------------------------------------------------------------
    def stake_if_stable(self,
                        trade,
                        dataframe: DataFrame,
                        current_rate: float,
                        ) -> bool:
        """
        仅在价格“企稳”后返回补仓 stake；否则返回 None。
        """
        # 1. 拉取开单后的 K 线
        df_after = dataframe[dataframe['date'] >= trade.open_date]
        if df_after.empty:
            return False

        atr_now = df_after['atr'].iloc[-1] if 'atr' in df_after.columns else np.nan
        if atr_now != atr_now or atr_now <= 0 or current_rate <= 0:  # NaN guard
            return False
        rebound_need = float(self.rebound_atr_mult.value) * atr_now
        extreme = df_after['low'].min()
        condition = (current_rate - extreme) >= rebound_need

        # 3. 满足企稳条件才返回补仓金额
        return True if condition else False

    def _fill_ledger(self, trade) -> List[Dict[str, Any]]:
        """Strategy-side fill ledger (Bullseye has no order objects).

        Seeded from the live trade on first sight; appended on every DCA
        return so count/last-price/last-time mirror the freqtrade version.
        """
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

            # 最大补仓次数
            if count_of_entries >= self.max_dca_count.value:
                return None

            last_entry = filled_entries[-1]
            timestamp_sec = int(pd.to_datetime(last_entry["time"]).timestamp())
            if int(pd.to_datetime(current_time).timestamp()) - timestamp_sec <= self.lock_adjust_time.value * 100:
                return None

            # ATR-scaled drawdown trigger: add only when underwater by
            # adjust_atr_mult ATRs from average cost.
            atr_now = dataframe['atr'].iloc[-1] if 'atr' in dataframe.columns else np.nan
            if atr_now != atr_now or atr_now <= 0 or current_rate <= 0:
                return None
            atr_pct = atr_now / current_rate
            if (current_profit / (trade.leverage or 1.0)) >= -float(self.adjust_atr_mult.value) * atr_pct:
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
