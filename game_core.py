"""
game_core.py  —  Liquidity Tranche Simulation (v3)

Key design decisions
--------------------
* Rates are ANNUALISED.  Each game round = 1 calendar month.
  Effective per-round rate = annual_rate / 12.
* Security metadata (face value, bid-ask spread, liquidity score) is
  AUTO-DERIVED from the price series — no second spreadsheet needed.
* Withdrawals are PER-GROUP, scaled to each group's own starting reserve,
  so groups with different portfolio compositions face different pressures.
* Withdrawal is AUTO-DEBITED when the host advances the round.
  If a group is short, a shortfall penalty is applied and the round advances
  anyway — there is no blocking.  Players learn from failure.
* Repo solvency: if current_account cannot cover repo repayment at maturity,
  collateral is auto-liquidated (sold at bid) to make up the difference.
"""

from dataclasses import dataclass, field
import random
import uuid
from typing import Dict, List, Tuple


# ── Constants ───────────────────────────────────────────────────────────────

ROUNDS_PER_YEAR   = 12          # each game round ≈ 1 month
SHORTFALL_PENALTY = 0.02        # 2 % of uncovered withdrawal charged as penalty
TD_PENALTY_RATE   = 0.005       # 0.5 % of principal for early TD redemption


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class SecuritySpec:
    ticker:         str
    face_price:     float = 100.0   # par / reference price
    bid_ask_bps:    float = 20.0    # total spread in basis points
    liquidity_score: int  = 2       # 1 = most liquid, 3 = least liquid

    @property
    def half_spread(self) -> float:
        return self.bid_ask_bps / 2.0 / 10_000.0

    def bid(self, mid: float) -> float:
        """Price received when selling."""
        return mid * (1 - self.half_spread)

    def ask(self, mid: float) -> float:
        """Price paid when buying."""
        return mid * (1 + self.half_spread)

    @property
    def liquidity_label(self) -> str:
        return {1: "High", 2: "Medium", 3: "Low"}.get(self.liquidity_score, "Medium")


@dataclass
class Portfolio:
    name:              str
    current_account:   float             = 0.0
    securities:        Dict[str, SecuritySpec] = field(default_factory=dict)
    pos_qty:           Dict[str, float]  = field(default_factory=dict)
    repo_liabilities:  List[Dict]        = field(default_factory=list)
    td_assets:         List[Dict]        = field(default_factory=list)
    pnl_realized:      float             = 0.0
    shortfall_total:   float             = 0.0   # cumulative uncovered withdrawals
    penalty_total:     float             = 0.0   # cumulative shortfall penalties

    # ── Valuation ────────────────────────────────────────────────────────────

    def market_value(self, prices: Dict[str, float]) -> float:
        sec_val = sum(
            self.pos_qty[t] * prices.get(t, self.securities[t].face_price)
            for t in self.pos_qty
        )
        td_val  = sum(a["amount"] for a in self.td_assets)
        return self.current_account + sec_val + td_val

    def net_score(self, prices: Dict[str, float]) -> float:
        """Total reserve minus cumulative penalties — the competition metric."""
        return self.market_value(prices) - self.penalty_total

    def summary(self, prices: Dict[str, float]) -> dict:
        sec_val = sum(
            self.pos_qty[t] * prices.get(t, self.securities[t].face_price)
            for t in self.pos_qty
        )
        return {
            "current_account":  self.current_account,
            "securities_mv":    sec_val,
            "repo_outstanding": sum(l["amount"] for l in self.repo_liabilities),
            "td_invested":      sum(a["amount"] for a in self.td_assets),
            "pnl_realized":     self.pnl_realized,
            "shortfall_total":  self.shortfall_total,
            "penalty_total":    self.penalty_total,
            "total_mv":         self.market_value(prices),
            "net_score":        self.net_score(prices),
        }


# ── Security metadata auto-derivation ───────────────────────────────────────

def derive_security_specs(
    price_history: Dict[str, List[float]]
) -> Dict[str, SecuritySpec]:
    """
    Infer SecuritySpec from a price series — no manual input required.

    Rules
    -----
    * face_price   = first observed price, rounded to nearest integer
    * liquidity_score / bid_ask_bps derived from coefficient of variation (CV):
        CV < 2 %  → score 1, spread 10 bps  (high liquidity, e.g. short gilts)
        CV < 5 %  → score 2, spread 25 bps  (medium liquidity)
        CV ≥ 5 %  → score 3, spread 50 bps  (low liquidity, e.g. long-dated / HY)
    """
    specs = {}
    for ticker, prices in price_history.items():
        # Safely coerce each value to float — skips None, strings (sub-header rows), and zeros
        clean = []
        for p in prices:
            try:
                v = float(p)
                if v > 0:
                    clean.append(v)
            except (TypeError, ValueError):
                pass
        prices = clean
        if not prices:
            specs[ticker] = SecuritySpec(ticker=ticker)
            continue

        face_price = round(float(prices[0]))
        if len(prices) > 1:
            mean = sum(prices) / len(prices)
            variance = sum((p - mean) ** 2 for p in prices) / len(prices)
            cv = (variance ** 0.5) / mean if mean else 0.0
        else:
            cv = 0.0

        if cv < 0.02:
            score, bps = 1, 10.0
        elif cv < 0.05:
            score, bps = 2, 25.0
        else:
            score, bps = 3, 50.0

        specs[ticker] = SecuritySpec(
            ticker=ticker,
            face_price=face_price,
            bid_ask_bps=bps,
            liquidity_score=score,
        )
    return specs


# ── Initialisation ───────────────────────────────────────────────────────────

def init_portfolios(
    tickers: List[str],
    specs: Dict[str, SecuritySpec],
    prices: Dict[str, float],
    num_groups: int = 4,
    total_reserve: float = 200_000.0,
    seed: int = 1234,
) -> List[Portfolio]:
    """
    Create `num_groups` portfolios.  Each gets 25 % cash and 75 % randomly
    weighted across the securities.  A deterministic seed ensures Host and
    Player sessions produce identical starting states.
    """
    rng = random.Random(seed)
    portfolios = []
    for i in range(num_groups):
        p = Portfolio(name=f"Group {i + 1}")
        p.current_account = total_reserve * 0.25
        remaining = total_reserve - p.current_account
        weights = [rng.random() for _ in tickers]
        s = sum(weights)
        weights = [w / s for w in weights]
        for t, w in zip(tickers, weights):
            p.securities[t] = specs[t]
            p.pos_qty[t]    = (remaining * w) / prices[t]
        portfolios.append(p)
    return portfolios


# ── Withdrawals ──────────────────────────────────────────────────────────────

def generate_withdrawal(
    round_idx: int,
    portfolio_reserve: float,
    rng: random.Random,
) -> float:
    """
    Withdrawal for a single group in a given round.
    Base fraction rises with round index (liquidity stress increases over time).
    A ±10 % per-group random variation ensures groups face different pressures.
    """
    base_frac = rng.uniform(0.18, 0.28) + 0.04 * round_idx
    base_frac = min(base_frac, 0.60)
    variation = rng.uniform(0.90, 1.10)
    return round(portfolio_reserve * base_frac * variation, 2)


def apply_withdrawal(portfolio: Portfolio, withdrawal: float) -> dict:
    """
    Auto-debit withdrawal from current_account.
    If insufficient, record shortfall and apply a 2 % penalty.
    The round still advances — players learn from the consequence.
    """
    available = max(0.0, portfolio.current_account)
    if available >= withdrawal:
        portfolio.current_account -= withdrawal
        return {"covered": True, "paid": withdrawal, "shortfall": 0.0, "penalty": 0.0}

    shortfall = withdrawal - available
    penalty   = round(shortfall * SHORTFALL_PENALTY, 2)
    portfolio.current_account    = 0.0
    portfolio.pnl_realized      -= (shortfall + penalty)
    portfolio.shortfall_total   += shortfall
    portfolio.penalty_total     += penalty
    return {
        "covered":   False,
        "paid":      available,
        "shortfall": shortfall,
        "penalty":   penalty,
    }


# ── Rate helpers ─────────────────────────────────────────────────────────────

def monthly_rate(annual_rate: float) -> float:
    """Convert an annualised rate to a per-round (monthly) effective rate."""
    return annual_rate / ROUNDS_PER_YEAR


# ── Actions ──────────────────────────────────────────────────────────────────

def execute_repo(
    portfolio: Portfolio,
    ticker: str,
    amount: float,
    mid_price: float,
    current_round: int,
    annual_rate: float,
) -> Tuple[float, str]:
    """
    Borrow `amount` by posting `ticker` bonds as collateral.
    Returns (cash_received, repo_id).  Amount is capped at holdings value.
    """
    spec     = portfolio.securities.get(ticker)
    if spec is None:
        return 0.0, None
    bid_px   = spec.bid(mid_price)          # collateral valued at bid
    max_amt  = portfolio.pos_qty.get(ticker, 0.0) * bid_px
    got      = min(amount, max_amt)
    if got <= 0:
        return 0.0, None

    qty_pledged = got / bid_px
    rate        = monthly_rate(annual_rate)
    portfolio.pos_qty[ticker]   -= qty_pledged
    portfolio.current_account   += got
    repo_id = str(uuid.uuid4())
    portfolio.repo_liabilities.append({
        "id":          repo_id,
        "amount":      got,
        "qty_pledged": qty_pledged,
        "ticker":      ticker,
        "annual_rate": annual_rate,
        "rate":        rate,
        "maturity":    current_round + 1,
    })
    return got, repo_id


def execute_sale(portfolio: Portfolio, ticker: str, qty: float, mid_price: float) -> dict:
    """Sell `qty` units at bid price."""
    available = portfolio.pos_qty.get(ticker, 0.0)
    if qty <= 0 or qty > available:
        return {"proceeds": 0.0, "qty": 0.0, "pnl_delta": 0.0, "effective_price": 0.0}

    spec      = portfolio.securities[ticker]
    eff_price = spec.bid(mid_price)
    proceeds  = qty * eff_price
    pnl_delta = (eff_price - spec.face_price) * qty

    portfolio.pos_qty[ticker]   -= qty
    portfolio.current_account   += proceeds
    portfolio.pnl_realized      += pnl_delta
    return {"proceeds": proceeds, "qty": qty, "pnl_delta": pnl_delta, "effective_price": eff_price}


def execute_buy(portfolio: Portfolio, ticker: str, qty: float, mid_price: float) -> dict:
    """Buy `qty` units at ask price."""
    if qty <= 0:
        return {"cost": 0.0, "qty": 0.0, "ticker": ticker, "effective_price": mid_price}

    spec      = portfolio.securities[ticker]
    eff_price = spec.ask(mid_price)
    cost      = qty * eff_price

    if portfolio.current_account < cost:
        return {"cost": 0.0, "qty": 0.0, "ticker": ticker, "effective_price": eff_price}

    portfolio.current_account             -= cost
    portfolio.pos_qty[ticker]              = portfolio.pos_qty.get(ticker, 0.0) + qty
    return {"cost": cost, "qty": qty, "ticker": ticker, "effective_price": eff_price}


def execute_invest_td(
    portfolio: Portfolio,
    amount: float,
    current_round: int,
    annual_rate: float,
) -> List[str]:
    """Invest `amount` in a term deposit maturing in 2 rounds."""
    if amount <= 0 or portfolio.current_account < amount:
        return []
    rate    = monthly_rate(annual_rate)
    td_id   = str(uuid.uuid4())
    portfolio.current_account -= amount
    portfolio.td_assets.append({
        "id":          td_id,
        "amount":      amount,
        "annual_rate": annual_rate,
        "rate":        rate,
        "maturity":    current_round + 2,
    })
    return [td_id]


def execute_redeem_td(portfolio: Portfolio, amount: float, current_round: int) -> dict:
    """Redeem up to `amount` from TDs.  Early redemption incurs a 0.5 % penalty."""
    to_redeem = amount
    redeemed, principal, penalty = [], 0.0, 0.0

    for asset in list(portfolio.td_assets):
        if to_redeem <= 0:
            break
        take      = min(asset["amount"], to_redeem)
        principal += take
        is_early  = asset["maturity"] > current_round
        pen       = round(take * TD_PENALTY_RATE, 2) if is_early else 0.0
        penalty   += pen
        asset["amount"] -= take
        if asset["amount"] <= 1e-9:
            portfolio.td_assets.remove(asset)
        redeemed.append({"id": asset["id"], "taken": take, "early": is_early})
        to_redeem -= take

    portfolio.current_account += (principal - penalty)
    portfolio.pnl_realized    -= penalty
    return {"redeemed": redeemed, "principal": principal, "penalty": penalty}


# ── Maturity processing ──────────────────────────────────────────────────────

def process_maturities(
    portfolio: Portfolio,
    current_round: int,
    prices: Dict[str, float],
) -> List[dict]:
    """
    Settle maturing repos and TDs.

    Repo solvency:
        If current_account cannot cover the repayment, auto-sell enough
        collateral (at bid) to make up the difference.  Any residual
        shortfall is charged as a penalty.
    """
    events = []

    # ── Repos ────────────────────────────────────────────────────────────────
    for liab in list(portfolio.repo_liabilities):
        if liab["maturity"] != current_round:
            continue

        repay   = liab["amount"] * (1 + liab["rate"])
        shortfall_needed = max(0.0, repay - portfolio.current_account)

        # Auto-liquidate pledged collateral if cash is short
        if shortfall_needed > 0:
            ticker = liab["ticker"]
            spec   = portfolio.securities.get(ticker)
            if spec and ticker in prices:
                bid_px = spec.bid(prices[ticker])
                qty_to_sell = min(
                    liab["qty_pledged"],
                    shortfall_needed / bid_px if bid_px > 0 else 0.0
                )
                if qty_to_sell > 0:
                    portfolio.pos_qty[ticker] = portfolio.pos_qty.get(ticker, 0.0) + liab["qty_pledged"] - qty_to_sell
                    proceed = qty_to_sell * bid_px
                    portfolio.current_account += proceed
                    liab["qty_pledged"] -= qty_to_sell
                    events.append({"type": "repo_auto_liquidation", "ticker": ticker,
                                   "qty": qty_to_sell, "proceeds": proceed})
            # Any remaining shortfall: return what collateral is left, charge penalty
            residual_short = max(0.0, repay - portfolio.current_account)
            if residual_short > 0:
                pen = round(residual_short * SHORTFALL_PENALTY, 2)
                portfolio.pnl_realized  -= pen
                portfolio.penalty_total += pen
                portfolio.current_account = 0.0
                events.append({"type": "repo_shortfall", "amount": residual_short, "penalty": pen})
            else:
                # Restore any unpledged collateral
                portfolio.pos_qty[liab["ticker"]] = (
                    portfolio.pos_qty.get(liab["ticker"], 0.0) + liab.get("qty_pledged", 0.0)
                )
        else:
            # Normal repayment — return collateral
            portfolio.pos_qty[liab["ticker"]] = (
                portfolio.pos_qty.get(liab["ticker"], 0.0) + liab["qty_pledged"]
            )

        portfolio.current_account  -= min(repay, portfolio.current_account)
        portfolio.pnl_realized     -= liab["rate"] * liab["amount"]
        portfolio.repo_liabilities.remove(liab)
        events.append({"type": "repo_matured", "amount": liab["amount"], "repaid": repay})

    # ── Term Deposits ────────────────────────────────────────────────────────
    for asset in list(portfolio.td_assets):
        if asset["maturity"] != current_round:
            continue
        interest  = asset["amount"] * asset["rate"]
        portfolio.current_account += asset["amount"] + interest
        portfolio.pnl_realized    += interest
        portfolio.td_assets.remove(asset)
        events.append({"type": "td_matured", "principal": asset["amount"], "interest": interest})

    return events


# ── Max repo capacity ────────────────────────────────────────────────────────

def max_repo_cash(portfolio: Portfolio, prices: Dict[str, float]) -> Dict[str, float]:
    """Maximum additional repo cash available per ticker."""
    result = {}
    for t, qty in portfolio.pos_qty.items():
        spec = portfolio.securities.get(t)
        if spec and t in prices:
            result[t] = qty * spec.bid(prices[t])
    return result
