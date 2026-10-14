"""
TopRotFactor - TopRot + 风险因子过滤 (低波动/低换手).

因子检验(34只池, 23-26, 20d前瞻)结果: 低波动(vol20 IC-0.051, 高-低组
+2.3%/20d)、低换手(turn20 IC-0.047, +1.7%)、低beta(-0.067)方向一致;
非流动性 +4%/20d 但与小市值混淆, 暂不采用.
本版在 TopRot 的排名过滤前, 先把高波动/高换手的票踢出候选池:
- filter=factor name: vol20 (波动率) / turn20 (换手) / none.
- 剔除阈值: 池内该因子的 top (1-filter_pct) 分位.
其余逻辑与 TopRot 完全一致 (10日动量前2, 回踩进, 30天/-10%/MA20出).
"""
import pandas as pd
from pandas import DataFrame

try:
    from strategies.TopRot import TopRot
except ImportError:  # pragma: no cover - local/dev context
    from user_data.strategies.TopRot import TopRot


class TopRotFactor(TopRot):
    INTERFACE_VERSION = 3

    filter_factor: str = "turn20"  # vol20 | turn20 | none
    filter_pct: float = 0.66       # 硬过滤: 剔除最高34%
    mode: str = "score"            # "filter" 硬踢 | "score" 排名加分
    factor_weight: float = 0.5     # score: 动量分 + w * 低风险分

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["vol20"] = (
            dataframe["close"].pct_change().rolling(20).std()
        )
        dataframe["turn20"] = (
            dataframe["turn"].rolling(20).mean()
            if "turn" in dataframe else pd.NA
        )
        return dataframe

    def _factor_values(self) -> dict:
        vals = {}
        for p in self.pool:
            try:
                df, _ = self.dp.get_analyzed_dataframe(p, self.timeframe)
            except Exception:
                continue
            if df is None or df.empty or self.filter_factor not in df:
                continue
            v = df[self.filter_factor].iloc[-1]
            if pd.notna(v):
                vals[p] = float(v)
        return vals

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time, entry_tag, side: str, **kwargs,
    ) -> bool:
        if entry_tag != "top_rot":
            return True
        if pair == "000300.SH":
            return False
        # 大盘门禁 (同TopRot).
        try:
            idx_df, _ = self.dp.get_analyzed_dataframe("000300.SH", self.timeframe)
            if idx_df is not None and not idx_df.empty and "ma60" in idx_df:
                if idx_df["close"].iloc[-1] < idx_df["ma60"].iloc[-1]:
                    return False
        except Exception:
            pass
        # 风险因子: 硬过滤(踢高波动/高换手) 或 排名加分(动量分+低风险分).
        strengths = self._pool_strengths()
        if not strengths:
            return True
        if strengths.get(pair, 0) < self.mom_floor:
            return False
        if self.filter_factor != "none" and strengths:
            fvals = self._factor_values()
            if len(fvals) >= 8:
                fser = pd.Series(fvals)
                cutoff = fser.quantile(self.filter_pct)
                if self.mode == "filter":
                    if fvals.get(pair, 0.0) > cutoff:
                        return False
                else:  # score: 低风险加分, 不硬踢
                    mom_rank = pd.Series(strengths).rank(pct=True)
                    low_risk = (-fser).rank(pct=True)
                    score = mom_rank + self.factor_weight * low_risk
                    top = score.nlargest(max(1, int(self.top_n))).index
                    return pair in set(top)
        ranked = sorted(strengths, key=strengths.get, reverse=True)
        return pair in ranked[: max(1, int(self.top_n))]
