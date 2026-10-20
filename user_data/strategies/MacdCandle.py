"""
MacdCandle - K线形态 + 指标(均线/MACD/KDJ/BOLL/量) 的通用底顶策略, 1d.

思路 (用户需求): A股K线战法. 底部形态买、顶部形态卖, 再结合均线/MACD/KDJ/BOLL
判断这次形态在底部还是顶部. 形态与指标状态库见 candle_patterns.py.

- buy_setups: (形态, 指标状态|None) 列表, 任一命中即买. 指标状态名见
  candle_patterns.indicator_states() (ma_* / macd_* / kdj_* / boll_* / vol_*).
- sell_setups: 顶部预警套装, use_top_exit=True 时作为机械卖出 (默认关, 见下).
- 出场: 吊灯移动止盈 (浮盈>trail_activate 后跌破 持仓期最高收盘-trail_atr_mult*ATR20)
  + stoploss 硬止损 + time_stop 时间止损; 300指数<MA60 只挡新单.

形态x指标 前瞻筛选 (34只大中市值, 2023-01~2026-10, 基准 f20 +2.17%/胜率52%):
    hammer + vol_dry              n= 91  f20 +4.64% 胜率63% (摸+8% 57%, 破-6% 25%)
    hammer + ma_bull_align        n=117  f20 +4.22% 胜率60%
    bull_three_soldiers+vol_spike n=270  f20 +5.30% 胜率54%
    bull_three_soldiers+ma_below_ma250 n=138 f20 +5.16% 胜率59%
    inverted_hammer+macd_top_div  n= 95  f20 +4.48% 胜率42% (摸+8% 61%)
    dragonfly + kdj_oversold      n= 76  f20 +4.32% f40 +8.61%
    hammer + boll_widen           n=237  f20 +3.82% 摸+8% 61%
    bull_engulfing+kdj_gold_low   n= 43  f20 +3.40% f40 +9.46%
    顶部: hanging_man+macd_top_div n=55 f20 -3.28% 胜率35%
          hanging_man+boll_squeeze n=123 f20 -0.69% 胜率39%
          hanging_man+ma20_rising  n=291 f20 +0.16% 胜率49%
          bear_engulfing+macd_death n=69 f20 +0.78% f40 +1.19%
    无效组合: inverted_hammer+macd_bot_div (f20 +0.39%),
              piercing+ma_bull_align (mdd40 -6.7%), bull_engulfing+kdj_gold_low 实盘 +8%.

关键结论 (实盘回测, 不是前瞻统计):
  * 单个套装基本只能到 +25~58%; **8个套装合并 = +233%, DD 8.8%, PF 3.49** ——
    弱edge靠分散叠加成强结果, 这正是"形态+指标"真正的价值.
  * 顶部形态卖出: 单套装时是灾难 (锤子 +185% -> +59%), **分散化之后变成加分项**
    (+241% -> +305% @t40, +412% -> +438% @t60) —— 早期"顶部形态不能卖"的结论
    只在单形态下成立.
  * 持仓时间: 40->60->80天单调更好, 但剔除两只outlier后增益迅速衰减
    (111%->131%->135% vs 全样本 241%->412%->664%), 边际收益集中在少数大单,
    故默认取 60 天而不是 80.

回测 (10万, 2023-01-01~2026-10-10, 3.78年, 费后0.001, T+1, 300指数<MA60挡新单):
    默认 (t60+顶部卖出+3槽): +233.4% (CAGR 37.5%), DD 8.80%, PF 3.49, 胜率51.5%,
        103笔; 剔除两只outlier票 +60.4% (DD 10.0%); 银行7只 +28.2%.
        样本外 2023-2024 +185.5% (DD 6.9%); 2025-2026 +27.1% (DD 8.4%).
    激进 (同但2槽): +437.6% (CAGR 56%), DD 11.9%, PF 3.92.
    ⚠️ 173只宽池上亏钱 (-4.4%, DD 36%): 形态策略依赖精选池的个股质量, 和
      TopRot 一样; 且34只池本身是事后选出的强势股, 有幸存者偏差.
    ⚠️ 8套装是从同一段样本里筛出来的, 参数(时间止损/槽位)也在同一段样本上选过,
      上面的分段一致性检验(每个参数在5个窗口同向)是唯一的防线.
"""
import pandas as pd
from pandas import DataFrame

from bullseye.strategy import IStrategy

try:
    from strategies.candle_patterns import detect, indicator_states, macd_state
    from strategies.chan_structure import chan_states
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.candle_patterns import detect, indicator_states, macd_state
    from user_data.strategies.chan_structure import chan_states


class MacdCandle(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    startup_candle_count = 280
    can_short = False

    minimal_roi: dict = {}
    stoploss: float = -0.06
    trailing_stop = False

    position_adjustment_enable = False

    # ---- 买入套装: (形态, 指标状态) ----
    buy_setups: tuple = (("hammer", None), ("hammer", "vol_dry"), ("hammer", "ma_bull_align"), ("bull_three_soldiers", "vol_spike"), ("bull_three_soldiers", "ma_below_ma250"), ("inverted_hammer", "macd_top_div"), ("dragonfly", "kdj_oversold"), ("bull_engulfing", "kdj_gold_low"))
    # ---- 顶部套装 (预警 + 机械卖出) ----
    sell_setups: tuple = (("hanging_man", "boll_squeeze"), ("hanging_man", "macd_top_div"), ("hanging_man", "ma20_rising"), ("bear_engulfing", "macd_death"))
    use_top_exit: bool = True        # 分散化后顶部卖出是加分项 (单套装时是灾难)
    require_top_macd: bool = True    # 卖出额外要求 MACD顶部
    require_above_ma60: bool = True  # 卖出额外要求 收盘>MA60

    # ---- 缠论结构状态 (分型/笔/中枢/背驰, 见 chan_structure.py) ----
    # 实测结论 (2026-10-18): 缠论机械化对现有形态+指标体系**没有增量**, 因此默认关闭。
    #   ALL8 233.4% -> +bi_pullback 85.1% -> +bi_macd 269.0%(DD 10.4%) 全部劣化或持平;
    #   三买/三卖/底背驰/顶背驰/笔方向的前瞻收益都贴着基准(见 docs/strategies.md)。
    #   想复现实验就置 use_chan=True 并在 buy_setups 里加 (None, "bi_pullback") 之类。
    use_chan: bool = False
    chan_min_gap: int = 5            # 笔的最小间隔 (测试里做成参数做敏感性分析)

    # ---- 出场/风控 ----
    take_profit: float = 99.0        # 99 = 不设固定止盈, 只用吊灯
    time_stop: int = 60
    use_trail: bool = True
    trail_activate: float = 0.03
    trail_atr_mult: float = 2.0
    max_slots: int = 3
    index_pair: str = "000300.SH"
    market_gate: bool = True

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        for name, series in detect(dataframe).items():
            dataframe[name] = series
        for name, series in indicator_states(dataframe).items():
            if isinstance(series, pd.Series) and series.dtype == bool:
                dataframe[f"st_{name}"] = series
        m = macd_state(dataframe)
        dataframe["dif"] = m["dif"]
        dataframe["dea"] = m["dea"]
        dataframe["hist"] = m["hist"]
        dataframe["macd_top"] = m["macd_top"]
        dataframe["ma60"] = close.rolling(60).mean()
        dataframe["ma10"] = close.rolling(10).mean()
        dataframe["ma20"] = close.rolling(20).mean()
        dataframe["ma250"] = close.rolling(250).mean()
        if self.use_chan:
            cs = chan_states(dataframe, min_gap=self.chan_min_gap)
            for name in ("bi_up", "in_pivot", "above_pivot", "third_buy",
                         "third_sell", "div_bottom", "div_top"):
                dataframe[f"st_{name}"] = cs[name]
            # 上升笔中的回踩: 结构向上 + 跌破MA10但守住MA20 (缠论版的强势股回踩)
            dataframe["st_bi_pullback"] = (
                cs["bi_up"]
                & (close < dataframe["ma10"])
                & (close > dataframe["ma20"])
            )
            # 上升笔 + MACD柱收敛 (动能未破)
            dataframe["st_bi_macd"] = (
                cs["bi_up"] & dataframe["st_macd_bottom"]
            )
            # 上升笔 + 缩量 (回踩不放量)
            dataframe["st_bi_voldry"] = cs["bi_up"] & dataframe["st_vol_dry"]
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
        return dataframe

    def _setup_signal(self, dataframe: DataFrame, pattern, indicator):
        """套装信号: pattern 可为 None (纯指标/结构状态), indicator 可为 None (裸形态)."""
        if pattern is None:
            return dataframe[f"st_{indicator}"]
        sig = dataframe[pattern]
        if indicator:
            sig = sig & dataframe[f"st_{indicator}"]
        return sig

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        entry = pd.Series(False, index=dataframe.index)
        for pattern, indicator in self.buy_setups:
            entry = entry | self._setup_signal(dataframe, pattern, indicator)
        entry = (entry & (dataframe["volume"] > 0)).fillna(False)
        dataframe.loc[entry, ["enter_long", "enter_tag"]] = (1, "candle_bottom")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if not self.use_top_exit:
            dataframe["exit_long"] = 0
            return dataframe
        exit_ = pd.Series(False, index=dataframe.index)
        for pattern, indicator in self.sell_setups:
            exit_ = exit_ | self._setup_signal(dataframe, pattern, indicator)
        if self.require_top_macd:
            exit_ = exit_ & dataframe["macd_top"]
        if self.require_above_ma60:
            exit_ = exit_ & (dataframe["close"] > dataframe["ma60"])
        exit_ = (exit_ & (dataframe["volume"] > 0)).fillna(False)
        dataframe.loc[exit_, ["exit_long", "exit_tag"]] = (1, "candle_top")
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
        if entry_tag != "candle_bottom":
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
        if max_stake and stake > max_stake:
            stake = max_stake
        return stake

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs,
    ):
        if current_profit >= self.take_profit:
            return "take_profit"
        try:
            held_days = (
                pd.to_datetime(current_time) - pd.to_datetime(trade.open_date)
            ).days
        except (TypeError, ValueError, AttributeError):
            held_days = 0
        if held_days >= self.time_stop:
            return "time_stop"
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            return None
        if df is None or df.empty or "low" not in df:
            return None
        held = df[pd.to_datetime(df["date"]) >= pd.to_datetime(trade.open_date)]
        if held.empty:
            return None
        if self.use_trail and current_profit >= self.trail_activate:
            if "atr" not in held or pd.isna(held["atr"].iloc[-1]):
                return None
            peak = held["close"].max()
            if held["close"].iloc[-1] < peak - self.trail_atr_mult * held["atr"].iloc[-1]:
                return "trail"
        return None