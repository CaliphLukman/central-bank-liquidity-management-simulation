#!/usr/bin/env python3
"""Liquidity Tranche Simulation — CLI version.
Run with:  python liquidity_game.py --prices sample_bond_prices.csv
"""
import argparse, json, random
import pandas as pd
from game_core import (
    init_portfolios, derive_security_specs, generate_withdrawal, apply_withdrawal,
    execute_repo, execute_sale, max_repo_cash, process_maturities,
)

BASE_REPO_RATE_PA = 0.045   # 4.5 % p.a.


def simulate(price_file: str, seed: int = 1234, rounds: int = 4, out: str = "game_output"):
    random.seed(seed)
    if price_file.endswith(".xlsx"):
        df = pd.read_excel(price_file)
    else:
        df = pd.read_csv(price_file)
    assert "date" in df.columns, "File must have a 'date' column"
    tickers = [c for c in df.columns if c != "date"]
    assert len(tickers) >= 2, "Need at least 2 bond columns"

    specs      = derive_security_specs({t: df[t].dropna().tolist() for t in tickers})
    prices0    = {t: float(df.loc[0, t]) for t in tickers}
    portfolios = init_portfolios(tickers, specs, prices0, num_groups=2, seed=seed)
    logs       = {p.name: [] for p in portfolios}

    for r in range(rounds):
        ix     = min(r, len(df) - 1)
        prices = {t: float(df.loc[ix, t]) for t in tickers}
        print(f"\n{'='*60}\nRound {r+1}  |  {df.loc[ix,'date']}")

        for p in portfolios:
            process_maturities(p, r, prices)
            rng_w = random.Random(seed + hash(p.name) + r)
            w = generate_withdrawal(r, p.market_value(prices), rng_w)
            print(f"\n--- {p.name}  |  Need: ${w:,.2f}  |  Cash: ${p.current_account:,.2f} ---")
            print("  Commands: repo BOND AMT | sell BOND QTY | status | done")

            while p.current_account < w:
                raw = input("  > ").strip().split()
                if not raw:
                    continue
                op = raw[0].lower()
                if op == "status":
                    repo_cap = {k: "${:,.0f}".format(v) for k, v in max_repo_cash(p, prices).items()}
                    print("    Cash ${:,.2f}  |  Max repo: {}".format(p.current_account, repo_cap))
                elif op == "repo" and len(raw) == 3:
                    got, _ = execute_repo(p, raw[1].upper(), float(raw[2]),
                                          prices.get(raw[1].upper(), 0), r, BASE_REPO_RATE_PA)
                    if got > 0:
                        print("    Borrowed ${:,.2f}".format(got))
                    else:
                        print("    Repo failed.")
                elif op == "sell" and len(raw) == 3:
                    res = execute_sale(p, raw[1].upper(), float(raw[2]),
                                       prices.get(raw[1].upper(), 0))
                    if res["proceeds"] > 0:
                        print("    Proceeds ${:,.2f}".format(res["proceeds"]))
                    else:
                        print("    Sale failed.")
                elif op == "done":
                    break

            result = apply_withdrawal(p, w)
            if result["covered"]:
                print("  Withdrawal: Covered")
            else:
                print("  Withdrawal: Shortfall ${:,.2f}  penalty ${:,.2f}".format(
                    result["shortfall"], result["penalty"]))
            logs[p.name].append({"round": r + 1, "withdrawal": w, "result": result})

    print("\n=== FINAL SCORES ===")
    last_prices = {t: float(df.loc[min(rounds - 1, len(df) - 1), t]) for t in tickers}
    rows = []
    for p in portfolios:
        s = p.summary(last_prices)
        print("  {}: Net Score ${:,.2f}  |  Penalties ${:,.2f}".format(
            p.name, s["net_score"], s["penalty_total"]))
        rows.append({"group": p.name, **s})
    pd.DataFrame(rows).to_csv("{}_scoreboard.csv".format(out), index=False)
    with open("{}_logs.json".format(out), "w") as f:
        json.dump(logs, f, indent=2)
    print("Saved: {0}_scoreboard.csv  {0}_logs.json".format(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Liquidity Simulation CLI")
    ap.add_argument("--prices",  required=True, help=".csv or .xlsx price file")
    ap.add_argument("--seed",    type=int, default=1234)
    ap.add_argument("--rounds",  type=int, default=4)
    ap.add_argument("--out",     default="game_output")
    args = ap.parse_args()
    simulate(args.prices, args.seed, args.rounds, args.out)
