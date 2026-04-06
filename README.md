# Liquidity Tranche Simulation — v3

A multiplayer Streamlit game teaching liquidity management under stress.
Central bankers learn to balance repos, bond sales, term deposits, and cash
across rounds with escalating withdrawal demands.

## Quick Start

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Upload `sample_bond_prices.csv` (or any `.csv`/`.xlsx` with a `date` column
and one column per bond) then click **Start/Reset**.

A **Download template** button is available in the sidebar if you need a
starting point.

## CLI version

```bash
python liquidity_game.py --prices sample_bond_prices.csv --rounds 4
```

---

## Design principles (v3)

### Input file — just prices, nothing else
The file only needs what a facilitator naturally has: a date column and one
price column per bond.  Everything else is auto-derived:

| Property | How derived |
|---|---|
| Face value | First observed price, rounded to nearest integer |
| Liquidity score | Price coefficient of variation: CV < 2% → High (score 1), CV < 5% → Medium (score 2), CV ≥ 5% → Low (score 3) |
| Bid-ask spread | High = 10 bps, Medium = 25 bps, Low = 50 bps |

Players can inspect all derived values in the **Security Details** expander.

### Rates — annualised, monthly application
All rates are expressed and displayed as **p.a.** figures.
Each round = 1 calendar month, so effective per-round rate = annual rate / 12.

| Rate | Default |
|---|---|
| Repo | 4.5% p.a. ± 0.5% |
| Term Deposit | 5.0% p.a. ± 0.5% |
| Early TD penalty | 0.5% of principal |
| Shortfall penalty | 2% of uncovered amount |

### Withdrawal — auto-debit, no "use cash" step
Each group's withdrawal is announced at round start.
Players raise cash (repo / sell / redeem TD) and must have sufficient
`current_account` balance **before** the Host clicks Next Round.
The Host advances; the system auto-debits each group's withdrawal.
If a group is short, the penalty is applied and the round still advances —
players learn from the consequence.

Withdrawals are **per-group**, scaled to each group's own starting portfolio,
so different compositions face genuinely different pressures.

### Scoring
**Net Score = Total Reserve − Cumulative Penalties**
Groups that cover every withdrawal without penalty and preserve portfolio value win.

### Repo solvency
If a group cannot repay a maturing repo from cash alone, the system
auto-liquidates the pledged collateral at bid price.  Any residual shortfall
incurs a penalty.  This models the real consequence of over-leveraging.
