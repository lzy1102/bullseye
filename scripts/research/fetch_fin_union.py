"""Top up fundamentals for every name that ever appears in a point-in-time pool.

The point-in-time universe changes every month, so the names worth having
fundamentals for are the union of all monthly members, not a fixed index list.

    python3 scripts/research/fetch_fin_union.py \
        --pit user_data/data_all/pit_top300.parquet \
        --fin-dir user_data/data_all_fin --workers 8
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from fetch_fundamentals_fast import fetch_fin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pit", default="user_data/data_all/pit_top300.parquet")
    ap.add_argument("--fin-dir", default="user_data/data_all_fin")
    ap.add_argument("--fin-start", default="2014")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    pit = pd.read_parquet(args.pit)
    syms = sorted(pit["symbol"].unique())
    os.makedirs(args.fin_dir, exist_ok=True)
    missing = [s for s in syms
               if not os.path.exists(os.path.join(args.fin_dir, f"{s}.parquet"))]
    print(f"pit names {len(syms)}, missing fundamentals {len(missing)}", flush=True)
    if not missing:
        return 0

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_fin, s, args.fin_dir, args.fin_start): s
                for s in missing}
        for i, fut in enumerate(as_completed(futs), 1):
            sym, st = fut.result()
            ok += st == "ok"
            fail += st.startswith("fail")
            if i % 50 == 0:
                print(f"  {i}/{len(missing)} ok={ok} fail={fail}", flush=True)
    print(f"done: {len(os.listdir(args.fin_dir))} files (+{ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
