#!/usr/bin/env python3
"""A-share intraday signal scan (30m/1h/15m/5m).

Usage: python3 intraday_signals.py [30m|1h|15m|5m] [start] [end]

Conventions
- Signal is known at bar close; forward returns start at that close (house convention).
- x4/x8 = signal return minus the same time-of-day baseline (removes intraday drift).
- eod = signal close -> session close (the part a T+1 account could actually capture).
- trad = next bar open -> session close (executable, fees not included).
- mdd = worst excursion from signal close to session close (low for long, high for short).
- No lookahead: am_ret / pm_sofar are only used on afternoon bars, gap/first_ret only
  on bars at or after the anchor bar.
"""
import sys

import numpy as np
import pandas as pd

DATA = "/opt/bullseye/user_data/data"
START, END = "2023-01-01", "2026-10-10"
PAIRS = [
    "000001.SZ", "000063.SZ", "000333.SZ", "000651.SZ", "002475.SZ",
    "002594.SZ", "300750.SZ", "300760.SZ", "600016.SH", "600030.SH",
    "600036.SH", "600276.SH", "600309.SH", "600887.SH", "600900.SH",
    "600941.SH", "601088.SH", "601288.SH", "601318.SH", "601398.SH",
    "601899.SH", "601939.SH", "601988.SH", "603259.SH", "688981.SH",
]


def load(pair, tf):
    df = pd.read_parquet(f"{DATA}/{pair}-{tf}.parquet")
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= START) & (df["date"] <= END)].reset_index(drop=True)
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)].reset_index(drop=True)
    df["pair"] = pair
    df["tod"] = df["date"].dt.strftime("%H:%M")
    df["day"] = df["date"].dt.date
    g = df.groupby("day", sort=False)
    df["day_open"] = g["open"].transform("first")
    df["day_high"] = g["high"].cummax()
    df["day_low"] = g["low"].cummin()
    df["day_close"] = g["close"].transform("last")
    df["cum_vol"] = g["volume"].cumsum()
    df["pv"] = df["close"] * df["volume"]
    df["cum_pv"] = df.groupby("day", sort=False)["pv"].cumsum()
    df["vwap"] = df["cum_pv"] / df["cum_vol"].replace(0, np.nan)
    df["ret1"] = df["close"] / df["close"].shift(1) - 1
    df["mom2"] = df["close"] / df["close"].shift(2) - 1
    df["mom4"] = df["close"] / df["close"].shift(4) - 1
    df["vol_ratio"] = df["volume"] / df["volume"].rolling(20).mean().shift(1)
    df["dev_vwap"] = df["close"] / df["vwap"] - 1
    rng = (df["day_high"] - df["day_low"]).replace(0, np.nan)
    df["range_pos"] = (df["close"] - df["day_low"]) / rng
    for k in (1, 2, 4, 8):
        df[f"f{k}"] = df["close"].shift(-k) / df["close"] - 1
    df["eod"] = df["day_close"] / df["close"] - 1
    df["next_open"] = df["open"].shift(-1)
    df["trad"] = df["day_close"] / df["next_open"] - 1
    df.loc[df["tod"] == df["tod"].max(), "trad"] = np.nan
    df["mdd_eod"] = df.groupby("day")["low"].transform(
        lambda s: s[::-1].cummin()[::-1]
    ) / df["close"] - 1
    df["mup_eod"] = df.groupby("day")["high"].transform(
        lambda s: s[::-1].cummax()[::-1]
    ) / df["close"] - 1
    return df


def bucket_table(dly, col, target, edges, labels, title):
    print(f"\n{title}")
    b = pd.cut(dly[col], edges, labels=labels)
    g = dly.groupby(b, observed=True)[target]
    tab = pd.DataFrame({
        "n": g.count(),
        "mean%": g.mean() * 100,
        "win%": g.apply(lambda s: (s > 0).mean()) * 100,
    })
    print(tab.round(2).to_string())
    print(f"  全体: n={dly[target].notna().sum()} mean={dly[target].mean() * 100:.3f}% "
          f"win={(dly[target] > 0).mean() * 100:.1f}%")


def main():
    global START, END
    tf = sys.argv[1] if len(sys.argv) > 1 else "30m"
    if len(sys.argv) > 3:
        START, END = sys.argv[2], sys.argv[3]
    big = pd.concat([load(p, tf) for p in PAIRS], ignore_index=True)
    big = big.sort_values(["pair", "date"]).reset_index(drop=True)
    tods = sorted(big["tod"].unique())
    first_tod = tods[0]
    am_tod = "11:30" if "11:30" in tods else max(t for t in tods if t <= "11:30")
    last_tod = tods[-1]
    aft_tods = [t for t in tods if t >= "13:00"]

    # daily table (per pair-day)
    day_open = big.groupby(["pair", "day"])["open"].first().rename("day_open_s")
    close_eod = big.groupby(["pair", "day"])["close"].last().rename("close_eod")
    am_close = (big[big["tod"] == am_tod].set_index(["pair", "day"])["close"]
                .rename("am_close"))
    first_close = (big[big["tod"] == first_tod].set_index(["pair", "day"])["close"]
                   .rename("first_close"))
    prev_close = close_eod.groupby(level=0).shift(1).rename("prev_close")
    dly = pd.concat([day_open, close_eod, am_close, first_close, prev_close], axis=1)
    dly = dly.dropna(subset=["day_open_s", "close_eod"])
    dly["am_ret"] = dly["am_close"] / dly["day_open_s"] - 1
    dly["pm_ret"] = dly["close_eod"] / dly["am_close"] - 1
    dly["first_ret"] = dly["first_close"] / dly["day_open_s"] - 1
    dly["rest_of_day"] = dly["close_eod"] / dly["first_close"] - 1
    dly["gap"] = dly["day_open_s"] / dly["prev_close"] - 1
    dly["day_ret"] = dly["close_eod"] / dly["day_open_s"] - 1

    dly = dly.reset_index()
    big = big.merge(
        dly[["pair", "day", "am_ret", "pm_ret", "gap", "first_ret"]],
        on=["pair", "day"], how="left",
    )
    big["pm_sofar"] = big["close"] / big["am_close"] if "am_close" in big else np.nan
    # am_close was not merged; derive pm_sofar via merge
    big = big.drop(columns=["pm_sofar"]).merge(
        dly[["pair", "day", "am_close"]], on=["pair", "day"], how="left",
    )
    big["pm_sofar"] = big["close"] / big["am_close"] - 1

    # baselines
    tod_base = big.groupby("tod")[["f2", "f4", "f8"]].mean()
    big["ex4"] = big["f4"] - big["tod"].map(tod_base["f4"])
    big["ex8"] = big["f8"] - big["tod"].map(tod_base["f8"])

    n_bars = len(big)
    print(f"=== {tf} | {START}~{END} | {len(PAIRS)} pairs | bars={n_bars:,} ===")
    print(f"基准 f4={big['f4'].mean() * 100:.3f}% win={(big['f4'] > 0).mean() * 100:.1f}% "
          f"per-bar vol={big['ret1'].std() * 100:.3f}%")

    print("\nA. 时段基准 (signal close -> next 4 bars)")
    t = tod_base.assign(
        ret1=big.groupby("tod")["ret1"].mean() * 100,
        win4=(big["f4"] > 0).groupby(big["tod"]).mean() * 100,
    )
    t = t.rename(columns={"f2": "f2%", "f4": "f4%", "f8": "f8%"})
    for c in ("f2%", "f4%", "f8%"):
        t[c] = t[c] * 100
    print(t.round(3).to_string())

    bucket_table(dly, "am_ret", "pm_ret", [-9, -.02, -.01, 0, .01, .02, 9],
                 ["<-2%", "-2~-1%", "-1~0", "0~1%", "1~2%", ">2%"],
                 "B. 上午收益 -> 下午收益 (11:30 close -> 15:00 close)")
    bucket_table(dly, "first_ret", "rest_of_day", [-9, -.01, -.005, 0, .005, .01, 9],
                 ["<-1%", "-1~-0.5%", "-0.5~0", "0~0.5%", "0.5~1%", ">1%"],
                 f"C. 首根 bar 收益 -> 余下时段 ({first_tod} close -> 15:00 close)")
    bucket_table(dly, "gap", "day_ret", [-9, -.01, -.005, 0, .005, .01, 9],
                 ["<-1%", "-1~-0.5%", "-0.5~0", "0~0.5%", "0.5~1%", ">1%"],
                 "D. 隔夜跳空 -> 当日开->收")

    rows = []

    def add(name, mask, side=1):
        sub = big[mask]
        n = int(sub["f4"].notna().sum())
        if n < 30:
            rows.append((name, n, *[np.nan] * 7))
            return
        s = side
        mdd = sub["mdd_eod"] if side == 1 else -sub["mup_eod"]
        rows.append((
            name, n,
            s * sub["f4"].mean() * 100,
            s * sub["ex4"].mean() * 100,
            (s * sub["f4"] > 0).mean() * 100,
            s * sub["f8"].mean() * 100,
            s * sub["ex8"].mean() * 100,
            mdd.mean() * 100,
            (s * sub["eod"]).mean() * 100,
            (s * sub["trad"]).mean() * 100,
        ))

    # momentum
    add("mom2_up", big["mom2"] > 0.005)
    add("mom2_dn", big["mom2"] < -0.005, -1)
    add("mom4_up", big["mom4"] > 0.01)
    add("mom4_dn", big["mom4"] < -0.01, -1)
    add("volspike_up", (big["vol_ratio"] > 2) & (big["ret1"] > 0.005))
    add("volspike_dn", (big["vol_ratio"] > 2) & (big["ret1"] < -0.005), -1)

    # morning -> afternoon
    is_a0 = big["tod"] == aft_tods[0]
    add("am_up_1", is_a0 & (big["am_ret"] > 0.01))
    add("am_up_2", is_a0 & (big["am_ret"] > 0.02))
    add("am_dn_1_cont", is_a0 & (big["am_ret"] < -0.01), -1)
    add("am_dn_1_fade", is_a0 & (big["am_ret"] < -0.01))
    add("am_dn_2_fade", is_a0 & (big["am_ret"] < -0.02))

    # first bar / gap
    is_second = big["tod"] == tods[1]
    add("first_up", is_second & (big["first_ret"] > 0.005))
    add("first_dn", is_second & (big["first_ret"] < -0.005), -1)
    add("gap_up", is_second & (big["gap"] > 0.005))
    add("gap_dn", is_second & (big["gap"] < -0.005), -1)

    # vwap
    is_aft = big["tod"].isin(aft_tods)
    add("below_vwap_05_fade", is_aft & (big["dev_vwap"] < -0.005))
    add("below_vwap_10_fade", is_aft & (big["dev_vwap"] < -0.01))
    add("above_vwap_05_fade", is_aft & (big["dev_vwap"] > 0.005), -1)
    add("above_vwap_10_fade", is_aft & (big["dev_vwap"] > 0.01), -1)
    add("above_vwap_10_mom", is_aft & (big["dev_vwap"] > 0.01))
    add("below_vwap_10_mom", is_aft & (big["dev_vwap"] < -0.01), -1)

    # day range position
    wide = (big["day_high"] - big["day_low"]) / big["day_open"] > 0.01
    add("near_day_low_fade", is_aft & wide & (big["range_pos"] < 0.15))
    add("near_day_high_fade", is_aft & wide & (big["range_pos"] > 0.85), -1)
    add("near_day_high_mom", is_aft & wide & (big["range_pos"] > 0.85))
    add("near_day_low_mom", is_aft & wide & (big["range_pos"] < 0.15), -1)

    # afternoon reversal / continuation
    is_late = big["tod"] >= tods[-2]
    add("am_dn_pm_up", is_late & (big["am_ret"] < -0.01) & (big["pm_sofar"] > 0.003))
    add("am_up_pm_dn", is_late & (big["am_ret"] > 0.01) & (big["pm_sofar"] < -0.003), -1)
    add("am_dn_pm_dn", is_late & (big["am_ret"] < -0.01) & (big["pm_sofar"] < -0.01))
    add("am_up_pm_up", is_late & (big["am_ret"] > 0.01) & (big["pm_sofar"] > 0.01))

    # last bar -> overnight
    is_last = big["tod"] == last_tod
    add("eod_up", is_last & (big["ret1"] > 0.005))
    add("eod_dn", is_last & (big["ret1"] < -0.005), -1)

    cols = ["signal", "n", "f4%", "x4%", "win4%", "f8%", "x8%", "mdd%", "eod%", "trad%"]
    res = pd.DataFrame(rows, columns=cols)
    print("\nE. 信号前瞻统计 (side 已按方向调整; eod/trad 为日内可兑现口径)")
    print(res.round(2).to_string(index=False))

    valid = res.dropna(subset=["x4%"]).sort_values("x4%", ascending=False)
    print("\nF. 按超额 x4 排序")
    print(valid[["signal", "n", "x4%", "win4%", "eod%", "trad%"]].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
