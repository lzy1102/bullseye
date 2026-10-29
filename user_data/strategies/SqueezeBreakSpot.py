"""
SqueezeBreakSpot - 布林带挤压突破（A股日线，只做多）, 1d.

移植来源: docs/SqueezeBreakout_实验归档.md（crypto 15m, 已证伪并关线）。
那条线死因是"事件幅度/成本比"不达标（15m 上毛信息量 ±0.02~0.05% < 0.1%
往返费），不是信号方向错。A股日线往返费 0.2%、单日波幅大得多，所以按
文档自己的方法论先做**事件级前向收益尸检**，再决定是否落策略。

尸检 (scripts/research/freqtrade_port_events.py, 规则池=时点流通市值前50,
同根收盘, 冷却期避免重叠样本):
    2023-2026 基准 f20 +1.71% / 中位 +0.27% / 胜率 51.2%
        挤压突破 f20 +2.83% / 中位 +1.14% / 胜率 55.7% / t=4.14 (n=343)
    2016-2022 基准 f20 +1.10% / 中位  0.00% / 胜率 49.7%
        挤压突破 f20 +2.21% / 中位 +0.93% / 胜率 53.7% / t=4.88 (n=698)
    => 两个窗口、全池与规则池同向，是唯一通过成本线的移植项。

同批被否决的移植项（见 docs/Freqtrade成果移植A股_实验归档.md）:
  * 唐奇安突破 + 放量1.5x: 规则池 2023-2026 有超额，但 2016-2022 反向
    （放量过滤把好突破滤掉）→ 池依赖，不落。
  * 底部压缩: 事件太少（n≈70~170），两个窗口都不显著。
  * 突破回踩: A股同样存在逆向选择（f20 贴基准），否决。
  * 资金费套利: A股无永续资金费，不可移植。

设计（对齐尸检，不额外加戏）:
  * 入场: 近 squeeze_lookback 根内出现挤压 (带宽100根分位≤20%) + 收盘突破
    上轨 + 带宽扩张 + 有成交。
  * 出场: 时间止损 time_stop=20 根（前瞻收益在 f20 达峰后衰减）+ 硬止损 8%
    + 可选吊灯（默认关：crypto 复盘显示跟踪止盈会削掉赢单）。
  * 可选 300 指数 MA60 挡新单（A股 beta 重，默认开）。
  * 仓位 max_slots=3，等权（与 MacdCandle 可比）。

回测口径: 10万, 2023-01-01~2026-10-10, 费 0.001/边, T+1, 同根收盘, 复利。
"""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy


class SqueezeBreakSpot(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 260
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = -0.08
    trailing_stop = False
    position_adjustment_enable = False

    # ---- 挤压与突破 ----
    bb_period: int = 20
    bb_std: float = 2.0
    bw_lookback: int = 100        # 带宽分位回看根数
    squeeze_pct: float = 0.20     # 带宽处于该分位以下视为挤压
    squeeze_lookback: int = 3     # 近 N 根内出现过挤压即可
    require_expand: bool = True   # 突破当根带宽必须扩张

    # ---- 出场/风控 ----
    time_stop: int = 20           # 持仓根数上限（前瞻收益 f20 达峰）
    use_trail: bool = False
    trail_activate: float = 0.05
    trail_atr_mult: float = 2.5

    # ---- 波动率定仓 (FreqAI 移植: 预测波动 -> 仓位缩放) ----
    # 尸检: 日线波动可预测 (walk-forward OOS IC 0.71, 十分位 91->382bp 单调),
    # 方向仍不可预测 (高波动组前向收益 +48bp, 低波动组 ~0, 非单调)。
    # ml = 读 user_data/data/volpred.parquet (scripts/research/vol_forecast.py 生成,
    #      walk-forward 岭回归, 无前视); atr = 只用当日 ATR 自校准, 无需数据文件。
    vol_sizing: str = "off"        # off | atr | ml
    vol_target_mode: str = "self"  # self = 该股自身250日波动中位; global = vol_target
    vol_target: float = 0.018      # global 模式的日波动目标
    vol_scale_lo: float = 0.3
    vol_scale_hi: float = 1.5
    vol_sidecar: str = "volpred.parquet"
    _volpred_cache = None

    # ---- 组合 ----
    max_slots: int = 3
    index_pair: str = "000300.SH"
    market_gate: bool = True      # 300 指数 < MA60 时挡新单
    require_above_ma250: bool = False  # 可选：只在年线上方做突破

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        ma = close.rolling(self.bb_period).mean()
        sd = close.rolling(self.bb_period).std()
        dataframe["bb_up"] = ma + self.bb_std * sd
        dataframe["bb_dn"] = ma - self.bb_std * sd
        dataframe["bw"] = (dataframe["bb_up"] - dataframe["bb_dn"]) / ma
        dataframe["bw_pct"] = dataframe["bw"].rolling(self.bw_lookback).rank(pct=True)
        dataframe["ma20"] = ma
        dataframe["ma60"] = close.rolling(60).mean()
        dataframe["ma250"] = close.rolling(250).mean()
        prev = close.shift(1)
        tr = pd.concat(
            [
                dataframe["high"] - dataframe["low"],
                (dataframe["high"] - prev).abs(),
                (dataframe["low"] - prev).abs(),
            ],
            axis=1,
        ).max(axis=1)
        dataframe["atr"] = tr.rolling(20).mean().fillna(0.0)

        # ---- 波动率定仓：est 越低，仓位越大（相对该股自身常态或全局目标）----
        if self.vol_sizing != "off":
            if self.vol_sizing == "ml":
                est = self._vol_estimate(dataframe, metadata.get("pair", ""))
            else:
                est = dataframe["atr"]
            if self.vol_target_mode == "self":
                base = est.rolling(250).median().shift(1)
            else:
                base = self.vol_target
            scale = (base / est.replace(0, np.nan)).clip(
                self.vol_scale_lo, self.vol_scale_hi
            )
            dataframe["vol_scale"] = scale.fillna(1.0)
        else:
            dataframe["vol_scale"] = 1.0
        return dataframe

    def _volpred(self) -> pd.DataFrame:
        cached = SqueezeBreakSpot._volpred_cache
        if cached is not None:
            return cached
        datadir = (self.config or {}).get("datadir", "user_data/data")
        path = Path(datadir) / self.vol_sidecar
        if path.exists():
            d = pd.read_parquet(path)
            d["date"] = pd.to_datetime(d["date"])
        else:
            d = pd.DataFrame(columns=["symbol", "date", "pred_vol"])
        SqueezeBreakSpot._volpred_cache = d
        return d

    def _vol_estimate(self, dataframe: DataFrame, pair: str) -> pd.Series:
        """Walk-forward predicted daily vol for `pair` (NaN when unavailable)."""
        side = self._volpred()
        if side.empty or not pair:
            return pd.Series(np.nan, index=dataframe.index)
        sub = side[side["symbol"] == pair][["date", "pred_vol"]]
        if sub.empty:
            return pd.Series(np.nan, index=dataframe.index)
        dates = pd.to_datetime(dataframe["date"])
        merged = pd.DataFrame({"date": dates}).merge(sub, on="date", how="left")
        return pd.Series(merged["pred_vol"].to_numpy(), index=dataframe.index)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        squeeze = (
            (dataframe["bw_pct"] <= self.squeeze_pct)
            .rolling(self.squeeze_lookback)
            .max()
            .fillna(0)
            .astype(bool)
        )
        breakout = dataframe["close"] > dataframe["bb_up"]
        entry = squeeze & breakout
        if self.require_expand:
            entry = entry & (dataframe["bw"] > dataframe["bw"].shift(1))
        if self.require_above_ma250:
            entry = entry & (dataframe["close"] > dataframe["ma250"])
        entry = (entry & (dataframe["volume"] > 0)).fillna(False)
        dataframe.loc[entry, ["enter_long", "enter_tag"]] = (1, "squeeze_break")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 出场只走 custom_exit（时间止损/止损/可选吊灯），不用信号出场
        dataframe["exit_long"] = 0
        return dataframe

    def _index_bull(self) -> bool:
        try:
            idx, _ = self.dp.get_analyzed_dataframe(self.index_pair, self.timeframe)
        except Exception:
            return True
        if idx is None or idx.empty or "ma60" not in idx:
            return True
        last = idx.iloc[-1]
        if pd.isna(last["ma60"]):
            return True
        return bool(last["close"] >= last["ma60"])

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if entry_tag != "squeeze_break":
            return True
        if pair == self.index_pair:
            return False
        if self.market_gate:
            return self._index_bull()
        return True

    def custom_stake_amount(
        self, pair: str, current_time, current_rate: float,
        proposed_stake: float, min_stake, max_stake: float,
        leverage: float, entry_tag, side: str, **kwargs,
    ):
        try:
            total = self.wallets.get_total_stake_amount()
        except Exception:
            return None
        if not total or total <= 0:
            return None
        stake = total / max(1, int(self.max_slots))
        if self.vol_sizing != "off":
            try:
                df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
                if df is not None and not df.empty and "vol_scale" in df.columns:
                    scale = float(df["vol_scale"].iloc[-1])
                    if np.isfinite(scale) and scale > 0:
                        stake *= scale
            except Exception:
                pass
        if max_stake and stake > max_stake:
            stake = max_stake
        return stake

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            return None
        if df is None or df.empty or "date" not in df:
            return None
        held = df[pd.to_datetime(df["date"]) >= pd.to_datetime(trade.open_date)]
        if held.empty:
            return None
        # 时间止损按持仓根数（事件研究用的是 h 根，不是日历天）
        if len(held) >= self.time_stop:
            return "time_stop"
        if self.use_trail and current_profit >= self.trail_activate:
            if "atr" not in held or pd.isna(held["atr"].iloc[-1]):
                return None
            peak = held["close"].max()
            if held["close"].iloc[-1] < peak - self.trail_atr_mult * held["atr"].iloc[-1]:
                return "trail"
        return None
