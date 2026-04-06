# streamlit_app.py  —  Liquidity Tranche Simulation v3
import os, json, time, random, glob
from typing import List, Dict, Tuple, Any, Optional

import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
    _HAS_AUTOREFRESH = True
except ImportError:
    _HAS_AUTOREFRESH = False

from game_core import (
    Portfolio, SecuritySpec,
    init_portfolios, derive_security_specs,
    generate_withdrawal, apply_withdrawal,
    execute_repo, execute_sale, execute_buy,
    execute_invest_td, execute_redeem_td,
    process_maturities, max_repo_cash,
    monthly_rate, ROUNDS_PER_YEAR, SHORTFALL_PENALTY, TD_PENALTY_RATE,
)

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Liquidity Simulation", layout="wide")

st.markdown("""
<style>
:root {
  --navy:#0B1F3B; --navy-strong:#0B3D91;
  --white:#FFFFFF; --ink:#111827;
  --green:#006400; --light-navy:#9DB7FF;
  --amber:#B45309; --red:#991B1B;
}
.stApp { background:var(--white); color:var(--ink); }
h1,h2,h3 { color:var(--navy-strong) !important; }
.stCaption, .stCaption * { color:var(--green) !important; }
.stMetricValue { color:var(--green) !important; font-weight:800 !important; }
.stMetricLabel { color:var(--ink) !important; font-weight:600 !important; }
.ticker-line { color:#000 !important; font-weight:700; }
.shortfall-warn { color:var(--red) !important; font-weight:700; }
section[data-testid="stSidebar"] {
  background:var(--navy); color:var(--white);
  border-right:4px solid var(--navy-strong);
}
section[data-testid="stSidebar"] * { color:var(--white) !important; opacity:1 !important; }
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] textarea,
section[data-testid="stSidebar"] select {
  background:#102A53 !important; color:var(--white) !important;
  border:1.5px solid var(--light-navy) !important; border-radius:8px !important;
}
div.stButton > button {
  background:var(--navy-strong) !important; color:var(--white) !important;
  border:0 !important; border-radius:8px !important; font-weight:700 !important;
}
div.stButton > button:hover { filter:brightness(.92); }
</style>
""", unsafe_allow_html=True)

# ── Config ───────────────────────────────────────────────────────────────────
BASE_REPO_RATE_PA  = 0.045    # 4.5 % p.a.
BASE_TD_RATE_PA    = 0.050    # 5.0 % p.a.
RATE_SPREAD_PA     = 0.005    # ±0.5 % p.a. daily variation
MAX_GROUPS_UI      = 8
TOTAL_RESERVE      = 200_000.0

SHARED_STATE_PATH  = ".shared_state.json"
UPLOADED_CSV_PATH  = ".uploaded.csv"
SNAPSHOT_PATH      = ".snapshot.json"
PORTFOLIO_DIR      = "."


# ── File helpers ─────────────────────────────────────────────────────────────
def _portfolio_path(name: str) -> str:
    return os.path.join(PORTFOLIO_DIR, f".portfolio_{name.replace(' ','_')}.json")

def _all_portfolio_paths() -> List[str]:
    return sorted(glob.glob(os.path.join(PORTFOLIO_DIR, ".portfolio_*.json")))

def _json_read(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _json_write(path: str, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)

def _json_mutate(path: str, default, fn):
    data = _json_read(path, default)
    new  = fn(data if isinstance(data, (dict, list)) else default)
    _json_write(path, new)
    return new

def _now() -> float:
    return time.time()

def _fmt(x: float, nd: int = 2) -> str:
    try:    return f"${x:,.{nd}f}"
    except: return f"${x}"

def _safe_rerun():
    try:    st.rerun()
    except Exception:
        try: st.experimental_rerun()
        except: pass


# ── Portfolio serialisation ───────────────────────────────────────────────────
def _p_to_dict(p: Portfolio) -> dict:
    return {
        "name":             p.name,
        "current_account":  p.current_account,
        "pos_qty":          dict(p.pos_qty),
        "pnl_realized":     p.pnl_realized,
        "shortfall_total":  p.shortfall_total,
        "penalty_total":    p.penalty_total,
        "repo_liabilities": list(p.repo_liabilities),
        "td_assets":        list(p.td_assets),
        "securities": {
            t: {"ticker": s.ticker, "face_price": s.face_price,
                "bid_ask_bps": s.bid_ask_bps, "liquidity_score": s.liquidity_score}
            for t, s in p.securities.items()
        },
        "last_updated": _now(),
    }

def _p_from_dict(d: dict) -> Portfolio:
    p = Portfolio(
        name            = d["name"],
        current_account = d["current_account"],
        pnl_realized    = d.get("pnl_realized", 0.0),
        shortfall_total = d.get("shortfall_total", 0.0),
        penalty_total   = d.get("penalty_total", 0.0),
    )
    p.pos_qty           = d.get("pos_qty", {})
    p.repo_liabilities  = d.get("repo_liabilities", [])
    p.td_assets         = d.get("td_assets", [])
    for t, s in d.get("securities", {}).items():
        p.securities[t] = SecuritySpec(
            ticker=s["ticker"], face_price=s.get("face_price", 100.0),
            bid_ask_bps=s.get("bid_ask_bps", 20.0),
            liquidity_score=s.get("liquidity_score", 2),
        )
    return p

def _load_portfolio(name: str) -> Optional[Portfolio]:
    d = _json_read(_portfolio_path(name), None)
    return _p_from_dict(d) if d else None

def _save_portfolio(p: Portfolio):
    _json_write(_portfolio_path(p.name), _p_to_dict(p))

def _load_all_portfolios() -> Dict[str, dict]:
    result = {}
    for path in _all_portfolio_paths():
        d = _json_read(path, None)
        if d and "name" in d:
            result[d["name"]] = d
    return result


# ── Rate helpers ─────────────────────────────────────────────────────────────
def _rates_for_round(r: int) -> Tuple[float, float]:
    """Return (repo_pa, td_pa) with a small per-round random variation."""
    rng = random.Random(st.session_state.rng_seed * 991 + r * 7919)
    repo_pa = max(0.005, BASE_REPO_RATE_PA + rng.uniform(-RATE_SPREAD_PA, RATE_SPREAD_PA))
    td_pa   = max(0.005, BASE_TD_RATE_PA   + rng.uniform(-RATE_SPREAD_PA, RATE_SPREAD_PA))
    return repo_pa, td_pa

def _prices_for_round(r: int) -> Tuple[str, Dict[str, float]]:
    df      = st.session_state.price_df
    ix      = min(r, len(df) - 1)
    tickers = [c for c in df.columns if c != "date"]
    return str(df.loc[ix, "date"]), {t: float(df.loc[ix, t]) for t in tickers}


# ── Session state bootstrap ───────────────────────────────────────────────────
def _init_state():
    ss = st.session_state
    ss.initialized      = False
    ss.rng_seed         = 1234
    ss.rounds           = 4
    ss.current_round    = 0
    ss.withdrawals      = {}    # group_name -> [float per round]
    ss.portfolios       = []
    ss.logs             = {}
    ss.price_df         = None
    ss.maturity_events  = {}    # group_name -> [events]
    ss.num_groups       = 4
    ss.role             = "Host"
    ss.player_group_idx = 0
    ss.player_name      = ""

if "initialized" not in st.session_state:
    _init_state()


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("### Session")
role = st.sidebar.radio("Role", ["Host", "Player"],
    index=0 if st.session_state.role == "Host" else 1)
st.session_state.role = role

if role == "Host":
    st.sidebar.header("Host Setup")
    uploaded   = st.sidebar.file_uploader(
        "Bond price file (.csv or .xlsx)\n\nColumns: `date`, then one column per bond.",
        type=["csv", "xlsx"]
    )
    seed       = st.sidebar.number_input("RNG seed", value=st.session_state.rng_seed, step=1)
    rounds     = st.sidebar.number_input("Rounds", value=st.session_state.rounds,
                                          min_value=2, max_value=10, step=1)
    groups     = st.sidebar.number_input("Groups", value=st.session_state.num_groups,
                                          min_value=1, max_value=MAX_GROUPS_UI, step=1)
    c1, c2, c3 = st.sidebar.columns(3)
    start_btn   = c1.button("Start/Reset", type="primary")
    refresh_btn = c2.button("Refresh 🔄")
    end_btn     = c3.button("End Game")

    # ── Template download ─────────────────────────────────────────────────────
    with st.sidebar.expander("📥 Download price template"):
        import io
        sample = pd.DataFrame({
            "date":   ["2025-01-01","2025-02-01","2025-03-01","2025-04-01",
                        "2025-05-01","2025-06-01"],
            "BOND_A": [100.60, 100.64, 100.05, 100.32, 99.85, 102.91],
            "BOND_B": [101.01, 100.97, 101.15, 104.74, 99.81, 102.99],
            "BOND_C": [100.04, 101.59,  99.77,  69.99,101.53, 100.70],
        })
        buf = io.BytesIO()
        sample.to_excel(buf, index=False)
        st.download_button("Download template.xlsx", buf.getvalue(),
                           file_name="template.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("Add as many bond columns as you like. "
                   "Bid-ask spread & liquidity tier are auto-derived from price volatility.")
else:
    st.sidebar.header("Player Setup")
    st.session_state.player_name = st.sidebar.text_input(
        "Your name", value=st.session_state.player_name or "")
    uploaded = None
    start_btn = refresh_btn = end_btn = False
    if _HAS_AUTOREFRESH:
        st_autorefresh(interval=5000, key="player_autorefresh")
    else:
        st.sidebar.caption("💡 Install `streamlit-autorefresh` for automatic sync.")
    if not os.path.exists(SNAPSHOT_PATH):
        st.sidebar.info("Waiting for Host to start…")
    else:
        shared = _json_read(SHARED_STATE_PATH, {})
        if shared.get("initialized"):
            st.sidebar.caption(
                f"Rounds: {shared.get('rounds')} • "
                f"Groups: {shared.get('num_groups')} • "
                f"Seed: {shared.get('rng_seed')}"
            )

with st.sidebar.expander("📖 How to play", expanded=False):
    st.markdown(f"""
**Goal:** Meet your withdrawal each round while maximising your final Net Score.

**Each round:**
1. A withdrawal is announced — you must have that much in your **Current Account** before the Host advances.
2. Raise cash using **Repo**, **Sell bonds**, or **Redeem TD** (early penalty: {TD_PENALTY_RATE*100:.1f}%).
3. Park spare cash in a **Term Deposit** to earn yield (matures in 2 rounds).
4. If you fall short, a **{SHORTFALL_PENALTY*100:.0f}% penalty** on the uncovered amount is charged automatically.

**Rates** are annualised (p.a.) and vary ±{RATE_SPREAD_PA*100:.1f}% each round.
**Net Score** = Total Reserve − Cumulative Penalties.
""")


# ── Start / End (Host) ────────────────────────────────────────────────────────
if role == "Host" and start_btn:
    if uploaded is None:
        st.sidebar.error("Please upload a price file first.")
    else:
        # Read CSV or Excel
        if uploaded.name.endswith(".xlsx"):
            df = pd.read_excel(uploaded)
        else:
            df = pd.read_csv(uploaded)

        bond_cols = [c for c in df.columns if c != "date"]
        if "date" not in df.columns or len(bond_cols) < 2:
            st.sidebar.error("File must have a 'date' column and at least 2 bond columns.")
        else:
            with open(UPLOADED_CSV_PATH, "wb") as f:
                f.write(uploaded.getbuffer())

            seed_val   = int(seed)
            rounds_val = int(rounds)
            cap        = min(MAX_GROUPS_UI, int(groups))

            _init_state()
            st.session_state.initialized   = True
            st.session_state.rng_seed      = seed_val
            st.session_state.rounds        = rounds_val
            st.session_state.num_groups    = cap
            st.session_state.price_df      = df.reset_index(drop=True)

            # Auto-derive security specs from price history
            price_history = {t: df[t].dropna().tolist() for t in bond_cols}
            specs = derive_security_specs(price_history)

            # Round 0 prices
            _, prices0 = _prices_for_round(0)

            # Initialise portfolios
            portfolios = init_portfolios(
                tickers=bond_cols, specs=specs, prices=prices0,
                num_groups=cap, total_reserve=TOTAL_RESERVE, seed=seed_val,
            )

            # Initial TD allocation (10–30 % of cash, deterministic)
            rng_td = random.Random(seed_val ^ 0xA5A5)
            repo_pa0, td_pa0 = _rates_for_round(0)
            for p in portfolios:
                frac = rng_td.uniform(0.10, 0.30)
                amt  = round(p.current_account * frac, 2)
                if amt > 0:
                    execute_invest_td(p, amt, 0, td_pa0)

            st.session_state.portfolios = portfolios

            # Generate per-group withdrawal schedule for all rounds
            withdrawals = {}
            for p in portfolios:
                rng_w = random.Random(seed_val + hash(p.name))
                mv0 = p.market_value(prices0)
                withdrawals[p.name] = [
                    generate_withdrawal(r, mv0, rng_w)
                    for r in range(rounds_val)
                ]
            st.session_state.withdrawals = withdrawals
            st.session_state.logs        = {p.name: [] for p in portfolios}
            st.session_state.maturity_events = {p.name: [] for p in portfolios}

            # Clear old portfolio files
            for old in _all_portfolio_paths():
                try: os.remove(old)
                except: pass
            if os.path.exists(SNAPSHOT_PATH):
                os.remove(SNAPSHOT_PATH)

            for p in portfolios:
                _save_portfolio(p)

            _json_write(SHARED_STATE_PATH, {
                "initialized": True, "rng_seed": seed_val,
                "rounds": rounds_val, "num_groups": cap,
                "current_round": 0,
                "withdrawals": withdrawals,
                "specs": {
                    t: {"ticker": s.ticker, "face_price": s.face_price,
                        "bid_ask_bps": s.bid_ask_bps,
                        "liquidity_score": s.liquidity_score}
                    for t, s in specs.items()
                },
                "claims": {}, "ts": _now(),
            })
            _json_write(SNAPSHOT_PATH, {"published": True, "ts": _now()})
            _safe_rerun()

if role == "Host" and end_btn and st.session_state.initialized:
    _json_mutate(SHARED_STATE_PATH, {},
        lambda s: {**s, "current_round": s.get("rounds", st.session_state.rounds), "ts": _now()})
    st.session_state.current_round = st.session_state.rounds
    _safe_rerun()


# ── Player bootstrap ──────────────────────────────────────────────────────────
st.title("Liquidity Tranche Simulation")

if role == "Player" and not st.session_state.initialized:
    if not os.path.exists(SNAPSHOT_PATH):
        st.info("Waiting for the Host to start the session.")
        st.stop()
    shared = _json_read(SHARED_STATE_PATH, {})
    if not shared.get("initialized"):
        st.info("Host is still setting up…")
        st.stop()
    if not os.path.exists(UPLOADED_CSV_PATH):
        st.info("Waiting for Host CSV…")
        st.stop()

    df_raw = pd.read_csv(UPLOADED_CSV_PATH) if UPLOADED_CSV_PATH.endswith(".csv") else pd.read_excel(UPLOADED_CSV_PATH)
    _init_state()
    st.session_state.initialized    = True
    st.session_state.rng_seed       = int(shared.get("rng_seed", 1234))
    st.session_state.rounds         = int(shared.get("rounds", 4))
    st.session_state.num_groups     = int(shared.get("num_groups", 4))
    st.session_state.price_df       = df_raw.reset_index(drop=True)
    st.session_state.current_round  = int(shared.get("current_round", 0))
    st.session_state.withdrawals    = shared.get("withdrawals", {})
    st.session_state.logs           = {}
    st.session_state.maturity_events = {}

if not st.session_state.initialized:
    st.info("Upload a price file and click **Start/Reset** to begin." if role == "Host"
            else "Waiting for the Host to start.")
    st.stop()

# Sync round for players
if role == "Player":
    shared = _json_read(SHARED_STATE_PATH, {})
    if shared.get("initialized"):
        host_round = int(shared.get("current_round", 0))
        if host_round != st.session_state.current_round:
            st.session_state.current_round = host_round
            st.session_state.withdrawals   = shared.get("withdrawals", st.session_state.withdrawals)

df        = st.session_state.price_df
all_tickers = [c for c in df.columns if c != "date"]
r         = st.session_state.current_round
NG        = st.session_state.num_groups
date_str, prices_all = _prices_for_round(r)
repo_pa, td_pa = _rates_for_round(r)
tickers_ui = all_tickers[:3]   # show up to 3 in summary cards


# ── Host: process maturities on round start ───────────────────────────────────
if role == "Host" and st.session_state.portfolios:
    # Refresh portfolios from files first
    if refresh_btn:
        all_raw = _load_all_portfolios()
        for p in st.session_state.portfolios:
            if p.name in all_raw:
                fresh = _p_from_dict(all_raw[p.name])
                p.current_account  = fresh.current_account
                p.pos_qty          = fresh.pos_qty
                p.pnl_realized     = fresh.pnl_realized
                p.shortfall_total  = fresh.shortfall_total
                p.penalty_total    = fresh.penalty_total
                p.repo_liabilities = fresh.repo_liabilities
                p.td_assets        = fresh.td_assets
                p.securities       = fresh.securities
        _safe_rerun()


# ── Player: group selection and claiming ──────────────────────────────────────
if role == "Player":
    shared     = _json_read(SHARED_STATE_PATH, {})
    all_raw    = _load_all_portfolios()
    group_names = list(all_raw.keys())
    if not group_names:
        st.info("Waiting for Host to initialise groups…")
        st.stop()

    claims: Dict[str, str] = shared.get("claims", {})

    # Claims banner
    claim_cols = st.columns(len(group_names))
    for i, gn in enumerate(group_names):
        owner = claims.get(gn, "")
        claim_cols[i].caption(f"{gn}: {'(unclaimed)' if not owner else owner}")

    valid_idx = min(max(st.session_state.player_group_idx, 0), len(group_names) - 1)
    st.session_state.player_group_idx = valid_idx
    chosen = st.sidebar.selectbox("Select your Group", group_names,
                                   index=valid_idx, key="group_sel")
    st.session_state.player_group_idx = group_names.index(chosen)

    if st.sidebar.button("Claim Group",
                          disabled=not st.session_state.player_name.strip()):
        def _claim(s):
            s = dict(s or {})
            s.setdefault("claims", {})
            if chosen not in s["claims"]:
                s["claims"][chosen] = st.session_state.player_name.strip()
            return s
        before = _json_read(SHARED_STATE_PATH, {})
        after  = _json_mutate(SHARED_STATE_PATH, {}, _claim)
        if after.get("claims", {}).get(chosen) != before.get("claims", {}).get(chosen):
            st.success(f"Claimed {chosen} ✅")
        else:
            st.warning("Group already claimed.")

    you_own = claims.get(chosen, "") == st.session_state.player_name.strip()


# ── Round header ──────────────────────────────────────────────────────────────
st.subheader(f"Round {r + 1} of {st.session_state.rounds}  —  {date_str}")
st.caption(
    f"Repo: **{repo_pa*100:.2f}% p.a.**  ({monthly_rate(repo_pa)*100:.3f}% this round)  •  "
    f"TD: **{td_pa*100:.2f}% p.a.**  ({monthly_rate(td_pa)*100:.3f}% this round)  •  "
    f"Early TD penalty: {TD_PENALTY_RATE*100:.1f}%  •  "
    f"Shortfall penalty: {SHORTFALL_PENALTY*100:.0f}% of uncovered amount"
)


# ── Security specs banner ─────────────────────────────────────────────────────
if role == "Host":
    specs_src = {t: p.securities[t]
                 for p in st.session_state.portfolios[:1] for t in p.securities}
else:
    all_raw_for_specs = _load_all_portfolios()
    first_grp = next(iter(all_raw_for_specs.values()), {})
    specs_src = {t: SecuritySpec(**{k: v for k, v in s.items()})
                 for t, s in first_grp.get("securities", {}).items()}

if specs_src:
    with st.expander("🔍 Security Details (auto-derived)", expanded=False):
        rows = []
        for t, s in specs_src.items():
            mid = prices_all.get(t, s.face_price)
            rows.append({
                "Bond": t,
                "Mid Price": _fmt(mid),
                "Face Value": _fmt(s.face_price),
                "Bid": _fmt(s.bid(mid)),
                "Ask": _fmt(s.ask(mid)),
                "Spread (bps)": f"{s.bid_ask_bps:.0f}",
                "Liquidity": s.liquidity_label,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Portfolio cards ───────────────────────────────────────────────────────────
if role == "Host":
    portfolios_display = st.session_state.portfolios[:NG]
else:
    all_raw = _load_all_portfolios()
    portfolios_display = [_p_from_dict(d) for d in all_raw.values()]

if portfolios_display:
    cols = st.columns(len(portfolios_display))
    for g, (col, p) in enumerate(zip(cols, portfolios_display)):
        with col:
            withdrawal = (st.session_state.withdrawals.get(p.name, [0]*r)
                          or [0] * (r+1))
            w = float(withdrawal[r]) if r < len(withdrawal) else 0.0
            ca = p.current_account
            ready = ca >= w
            colour = "#006400" if ready else "#991B1B"
            st.markdown(f"### {p.name}")
            st.markdown(
                f"<div style='font-size:24px;font-weight:800;color:{colour};'>"
                f"{_fmt(p.market_value(prices_all), 0)}</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"Cash: {_fmt(ca, 0)}  |  Need: {_fmt(w, 0)}")
            prog = min(1.0, ca / w) if w > 0 else 1.0
            st.progress(prog)
            for t in tickers_ui:
                st.markdown(
                    f"<div class='ticker-line'>{t}: "
                    f"{p.pos_qty.get(t, 0):,.0f} @ {_fmt(prices_all.get(t, 0))}</div>",
                    unsafe_allow_html=True,
                )
            if p.penalty_total > 0:
                st.markdown(
                    f"<div class='shortfall-warn'>⚠ Penalties: {_fmt(p.penalty_total)}</div>",
                    unsafe_allow_html=True,
                )


# ── Detailed tabs ─────────────────────────────────────────────────────────────
st.divider()

if role == "Host":
    tabs_list = [p.name for p in st.session_state.portfolios[:NG]]
    tabs = st.tabs(tabs_list or ["Group 1"])
    for p, tab in zip(st.session_state.portfolios[:NG], tabs):
        with tab:
            withdrawal_list = st.session_state.withdrawals.get(p.name, [])
            w = float(withdrawal_list[r]) if r < len(withdrawal_list) else 0.0
            s = p.summary(prices_all)
            st.markdown(f"### {p.name}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Current Account",   _fmt(s["current_account"]))
            c1.metric("Repo Outstanding",  _fmt(s["repo_outstanding"]))
            c2.metric("Securities Value",  _fmt(s["securities_mv"]))
            c2.metric("Term Deposits",     _fmt(s["td_invested"]))
            c3.metric("PnL Realized",      _fmt(s["pnl_realized"]))
            c3.metric("Net Score",         _fmt(s["net_score"]))
            st.markdown(f"**Withdrawal target:** :blue[{_fmt(w)}]  |  "
                        f"**Cash available:** :{'green' if p.current_account >= w else 'red'}[{_fmt(p.current_account)}]  |  "
                        f"**Penalties:** :red[{_fmt(s['penalty_total'])}]")
else:
    # ── Player tabs ───────────────────────────────────────────────────────────
    all_raw = _load_all_portfolios()
    group_names_list = list(all_raw.keys())
    shared   = _json_read(SHARED_STATE_PATH, {})
    claims   = shared.get("claims", {})

    if group_names_list:
        tabs = st.tabs(group_names_list)
        chosen_idx = st.session_state.player_group_idx

        for gi, (gn, tab) in enumerate(zip(group_names_list, tabs)):
            with tab:
                p = _load_portfolio(gn)
                if not p:
                    st.error(f"Could not load {gn}")
                    continue

                is_mine = (gi == chosen_idx and
                           claims.get(gn, "") == st.session_state.player_name.strip())

                withdrawal_list = st.session_state.withdrawals.get(gn, [])
                w = float(withdrawal_list[r]) if r < len(withdrawal_list) else 0.0
                s = p.summary(prices_all)

                st.markdown(f"### {gn}{' 🏦 (You)' if is_mine else ''}")
                c1, c2, c3 = st.columns(3)
                c1.metric("Current Account",  _fmt(s["current_account"]))
                c1.metric("Repo Outstanding", _fmt(s["repo_outstanding"]))
                c2.metric("Securities Value", _fmt(s["securities_mv"]))
                c2.metric("Term Deposits",    _fmt(s["td_invested"]))
                c3.metric("PnL Realized",     _fmt(s["pnl_realized"]))
                c3.metric("Net Score",        _fmt(s["net_score"]))

                ca = p.current_account
                gap = w - ca
                if gap > 0:
                    st.warning(f"⚠️  You need **{_fmt(gap)}** more in your Current Account to cover this round's withdrawal ({_fmt(w)}).")
                else:
                    st.success(f"✅  Current Account ({_fmt(ca)}) covers withdrawal ({_fmt(w)}). You're ready.")

                # TD schedule
                if p.td_assets:
                    with st.expander("📅 Term Deposit Schedule"):
                        for td in p.td_assets:
                            left = td["maturity"] - r
                            lbl  = ("✅ Matures next round" if left == 1
                                    else ("⏳ Matures this round" if left <= 0
                                          else f"🔒 {left} rounds left"))
                            interest = td["amount"] * td["rate"]
                            st.caption(
                                f"{_fmt(td['amount'])} @ {td['annual_rate']*100:.2f}% p.a.  →  "
                                f"+{_fmt(interest)} at maturity  —  {lbl}"
                            )

                # Repo liabilities
                if p.repo_liabilities:
                    with st.expander("🏦 Open Repo Positions"):
                        for lib in p.repo_liabilities:
                            repay = lib["amount"] * (1 + lib["rate"])
                            st.caption(
                                f"{_fmt(lib['amount'])} on {lib['ticker']}  →  "
                                f"repay {_fmt(repay)} in Round {lib['maturity']}"
                            )

                # Action history
                group_logs = st.session_state.logs.get(gn, [])
                if group_logs:
                    with st.expander(f"📋 Action History ({len(group_logs)} entries)"):
                        for entry in reversed(group_logs):
                            st.markdown(f"**Round {entry.get('round','?')}** — "
                                        f"withdrawal: {_fmt(entry.get('withdrawal',0))}")
                            for atype, adata in entry.get("actions", []):
                                if atype == "cash":
                                    st.caption(f"  💵 Used cash: {_fmt(adata.get('used',0))}")
                                elif atype == "repo":
                                    st.caption(f"  🏦 Repo {adata.get('ticker','')} → received {_fmt(adata.get('got',0))} @ {adata.get('annual_rate',0)*100:.2f}% p.a.")
                                elif atype == "sell":
                                    st.caption(f"  📉 Sold {adata.get('qty',0):,.2f} {adata.get('ticker','')} → {_fmt(adata.get('proceeds',0))} (PnL: {_fmt(adata.get('pnl_delta',0))})")
                                elif atype == "buy":
                                    st.caption(f"  📈 Bought {adata.get('qty',0):,.2f} {adata.get('ticker','')} for {_fmt(adata.get('cost',0))}")
                                elif atype == "invest_td":
                                    st.caption(f"  💰 Invested {_fmt(adata.get('amount',0))} in TD @ {adata.get('annual_rate',0)*100:.2f}% p.a.")
                                elif atype == "redeem_td":
                                    st.caption(f"  🔓 Redeemed TD: {_fmt(adata.get('principal',0))} principal, {_fmt(adata.get('penalty',0))} penalty")
                                elif atype == "withdrawal":
                                    status = "✅ Covered" if adata.get("covered") else f"❌ Shortfall {_fmt(adata.get('shortfall',0))}"
                                    st.caption(f"  💸 Withdrawal {_fmt(adata.get('paid',0))} — {status}")
                            st.divider()

                # ── Action panel (only for claimed group) ─────────────────────
                if is_mine:
                    st.divider()

                    def _gf(key):
                        try:    return float(st.session_state.get(key, 0.0) or 0.0)
                        except: return 0.0

                    rk = f"{gn}_{r}"   # key prefix resets each new round

                    # ── COVERAGE PANEL ─────────────────────────────────────────
                    # Players choose HOW to cover the withdrawal:
                    # any combination of cash, repo, TD redemption, and bond sale.
                    # A live tracker shows total planned coverage vs. target.
                    # Everything executes with one button.
                    st.markdown("#### 💰 Cover the Withdrawal")
                    st.caption(
                        f"Withdrawal target: **{_fmt(w)}**  |  "
                        f"Current cash: **{_fmt(p.current_account)}**  |  "
                        f"Fill any combination below and click **Execute**."
                    )

                    # ── Row 1: Cash + TD redemption ────────────────────────────
                    col_cash, col_td = st.columns(2)

                    with col_cash:
                        st.markdown("**💵 Use Cash**")
                        cash_max = max(0.0, p.current_account)
                        cash_key = f"cash_{rk}"
                        st.number_input(
                            f"Amount from current account (max {_fmt(cash_max)})",
                            min_value=0.0,
                            max_value=cash_max,
                            step=100.0,
                            format="%.2f",
                            key=cash_key,
                        )
                        cash_use = min(_gf(cash_key), cash_max)
                        if cash_use > 0:
                            st.caption(f"Will debit {_fmt(cash_use)} from your cash balance.")
                        else:
                            st.caption("Enter an amount to use your cash balance directly.")

                    with col_td:
                        st.markdown("**🔓 Redeem Term Deposit** *(early penalty applies)*")
                        td_total = sum(a["amount"] for a in p.td_assets)
                        rd_key = f"redeem_{rk}"
                        st.number_input(
                            f"Amount to redeem (available: {_fmt(td_total)})",
                            min_value=0.0,
                            max_value=float(td_total),
                            step=100.0,
                            format="%.2f",
                            key=rd_key,
                        )
                        rd_amt = _gf(rd_key)
                        if rd_amt > 0:
                            pen_preview = rd_amt * TD_PENALTY_RATE
                            net_td      = rd_amt - pen_preview
                            st.caption(
                                f"Penalty: {_fmt(pen_preview)}  →  "
                                f"Net cash received: **{_fmt(net_td)}**"
                            )
                        elif td_total == 0:
                            st.caption("No term deposits currently held.")
                        else:
                            st.caption(f"Penalty rate: {TD_PENALTY_RATE*100:.1f}% of redeemed amount.")

                    # ── Row 2: Repo + Sell bonds ───────────────────────────────
                    col_repo, col_sell = st.columns(2)

                    with col_repo:
                        st.markdown("**🏦 Repo** *(borrow against bonds)*")
                        rt_key = f"repo_t_{rk}"
                        ra_key = f"repo_a_{rk}"
                        st.selectbox(
                            "Bond to use as collateral",
                            ["(none)"] + all_tickers,
                            key=rt_key,
                        )
                        st.number_input(
                            "Amount to borrow ($)",
                            min_value=0.0,
                            step=100.0,
                            format="%.2f",
                            key=ra_key,
                        )
                        rt = st.session_state.get(rt_key, "(none)")
                        ra = _gf(ra_key)
                        repo_preview = 0.0
                        if rt != "(none)" and ra > 0 and rt in prices_all:
                            spec = p.securities.get(rt)
                            if spec:
                                bid      = spec.bid(prices_all[rt])
                                max_repo = p.pos_qty.get(rt, 0.0) * bid
                                actual   = min(ra, max_repo)
                                repay    = actual * (1 + monthly_rate(repo_pa))
                                repo_preview = actual
                                st.caption(
                                    f"Receive: **{_fmt(actual)}**  •  "
                                    f"Repay next round: {_fmt(repay)}  •  "
                                    f"Rate: {repo_pa*100:.2f}% p.a.  •  "
                                    f"Max available: {_fmt(max_repo)}"
                                )

                    with col_sell:
                        st.markdown("**📉 Sell Bonds**")
                        sel_t_key = f"sell_t_{rk}"
                        sel_q_key = f"sell_q_{rk}"
                        st.selectbox(
                            "Bond to sell",
                            ["(none)"] + all_tickers,
                            key=sel_t_key,
                        )
                        st.number_input(
                            "Quantity",
                            min_value=0.0,
                            step=1.0,
                            format="%.2f",
                            key=sel_q_key,
                        )
                        sell_t = st.session_state.get(sel_t_key, "(none)")
                        sell_q = _gf(sel_q_key)
                        sell_preview = 0.0
                        if sell_t != "(none)" and sell_q > 0 and sell_t in prices_all:
                            spec = p.securities.get(sell_t)
                            if spec:
                                bid      = spec.bid(prices_all[sell_t])
                                avail    = p.pos_qty.get(sell_t, 0.0)
                                actual_q = min(sell_q, avail)
                                sell_preview = actual_q * bid
                                st.caption(
                                    f"Bid: {_fmt(bid)}  •  "
                                    f"Proceeds: **{_fmt(sell_preview)}**  •  "
                                    f"Holdings: {avail:,.0f} units"
                                )

                    # ── Live coverage tracker ─────────────────────────────────
                    st.markdown("---")
                    net_td_proceeds  = max(0.0, _gf(rd_key) - _gf(rd_key) * TD_PENALTY_RATE)
                    total_planned    = cash_use + repo_preview + net_td_proceeds + sell_preview
                    gap_after        = w - total_planned
                    tracker_colour   = "#006400" if gap_after <= 0 else "#991B1B"
                    status_icon      = "✅" if gap_after <= 0 else "⚠️"

                    t1, t2, t3, t4, t5 = st.columns(5)
                    t1.metric("Cash",        _fmt(cash_use))
                    t2.metric("Repo",        _fmt(repo_preview))
                    t3.metric("TD Redemption", _fmt(net_td_proceeds))
                    t4.metric("Bond Sale",   _fmt(sell_preview))
                    t5.metric("Total Coverage", _fmt(total_planned))

                    st.markdown(
                        f"<div style='font-size:16px; font-weight:700; color:{tracker_colour}; "
                        f"padding:6px 0;'>"
                        f"{status_icon}  Withdrawal: {_fmt(w)}  |  "
                        f"Planned coverage: {_fmt(total_planned)}  |  "
                        f"{'Surplus: ' + _fmt(-gap_after) if gap_after <= 0 else 'Still needed: ' + _fmt(gap_after)}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    st.markdown("---")

                    # ── Execute all coverage actions ───────────────────────────
                    if st.button("⚡ Execute Coverage Actions", type="primary",
                                 key=f"exec_cov_{rk}"):
                        has_any = (cash_use > 0 or
                                   (rt != "(none)" and ra > 0) or
                                   _gf(rd_key) > 0 or
                                   (sell_t != "(none)" and sell_q > 0))
                        if not has_any:
                            st.warning("Enter at least one action above.")
                        else:
                            p2      = _load_portfolio(gn)
                            process_maturities(p2, r, prices_all)
                            actions = []
                            errors  = []

                            # 1. Cash
                            if cash_use > 0:
                                actual_cash = min(cash_use, p2.current_account)
                                if actual_cash > 0:
                                    p2.current_account -= actual_cash
                                    actions.append(("cash", {
                                        "used": round(actual_cash, 2),
                                    }))

                            # 2. Repo
                            if rt != "(none)" and ra > 0:
                                got, rid = execute_repo(
                                    p2, rt, ra, prices_all.get(rt, 0), r, repo_pa
                                )
                                if got > 0:
                                    actions.append(("repo", {
                                        "ticker": rt,
                                        "got": round(got, 2),
                                        "annual_rate": repo_pa,
                                    }))
                                else:
                                    errors.append("Repo failed — insufficient bond holdings.")

                            # 3. TD redemption
                            if _gf(rd_key) > 0:
                                res = execute_redeem_td(p2, _gf(rd_key), r)
                                if res["principal"] > 0:
                                    actions.append(("redeem_td", {
                                        "principal": round(res["principal"], 2),
                                        "penalty":   round(res["penalty"], 2),
                                    }))
                                else:
                                    errors.append("TD redemption failed — no balance available.")

                            # 4. Sell bonds
                            if sell_t != "(none)" and sell_q > 0:
                                res = execute_sale(
                                    p2, sell_t, sell_q, prices_all.get(sell_t, 0)
                                )
                                if res["proceeds"] > 0:
                                    actions.append(("sell", {
                                        "ticker":    sell_t,
                                        "qty":       round(res["qty"], 2),
                                        "proceeds":  round(res["proceeds"], 2),
                                        "pnl_delta": round(res["pnl_delta"], 2),
                                    }))
                                else:
                                    errors.append("Bond sale failed — check quantity vs. holdings.")

                            _save_portfolio(p2)
                            if actions:
                                st.session_state.logs.setdefault(gn, []).append({
                                    "round":      r + 1,
                                    "withdrawal": w,
                                    "actions":    actions,
                                })
                                # Clear the coverage inputs
                                for k in [cash_key, rd_key, ra_key, sel_q_key]:
                                    st.session_state.pop(k, None)
                                for k in [rt_key, sel_t_key]:
                                    st.session_state.pop(k, None)
                                st.success(
                                    f"Executed {len(actions)} action(s). "
                                    f"New cash balance: {_fmt(p2.current_account)}"
                                )
                            for err in errors:
                                st.error(err)
                            _safe_rerun()

                    # ── PORTFOLIO MANAGEMENT ────────────────────────────────────
                    # Buy bonds and invest in TDs are independent of the withdrawal.
                    st.markdown("#### 📊 Portfolio Management *(optional)*")
                    st.caption("These actions don't affect the withdrawal directly but optimise your portfolio.")

                    pm_col1, pm_col2 = st.columns(2)

                    with pm_col1:
                        with st.expander("💰 Invest in Term Deposit"):
                            inv_key = f"invest_{rk}"
                            st.number_input(
                                f"Amount (cash available: {_fmt(p.current_account)})",
                                min_value=0.0,
                                max_value=float(max(0.0, p.current_account)),
                                step=100.0,
                                format="%.2f",
                                key=inv_key,
                            )
                            inv_amt = _gf(inv_key)
                            if inv_amt > 0:
                                interest = inv_amt * monthly_rate(td_pa)
                                st.caption(
                                    f"Rate: {td_pa*100:.2f}% p.a.  •  "
                                    f"Interest at maturity: {_fmt(interest)}  •  "
                                    f"Matures: Round {r + 2}"
                                )
                            if st.button("Invest in TD", key=f"do_invest_{rk}"):
                                if inv_amt <= 0:
                                    st.warning("Enter an amount.")
                                else:
                                    p2  = _load_portfolio(gn)
                                    process_maturities(p2, r, prices_all)
                                    ids = execute_invest_td(p2, inv_amt, r, td_pa)
                                    _save_portfolio(p2)
                                    if ids:
                                        st.session_state.logs.setdefault(gn, []).append({
                                            "round": r + 1, "withdrawal": w,
                                            "actions": [("invest_td", {
                                                "amount": round(inv_amt, 2),
                                                "annual_rate": td_pa,
                                            })],
                                        })
                                        st.success(
                                            f"Invested {_fmt(inv_amt)} @ {td_pa*100:.2f}% p.a., "
                                            f"matures Round {r + 2}."
                                        )
                                        _safe_rerun()
                                    else:
                                        st.error("Investment failed — check cash balance.")

                    with pm_col2:
                        with st.expander("📈 Buy Bonds"):
                            bt_key = f"buy_t_{rk}"
                            bq_key = f"buy_q_{rk}"
                            st.selectbox("Bond to buy", ["(none)"] + all_tickers, key=bt_key)
                            st.number_input(
                                "Quantity",
                                min_value=0.0,
                                step=1.0,
                                format="%.2f",
                                key=bq_key,
                            )
                            buy_t = st.session_state.get(bt_key, "(none)")
                            buy_q = _gf(bq_key)
                            if buy_t != "(none)" and buy_q > 0 and buy_t in prices_all:
                                spec = p.securities.get(buy_t)
                                if spec:
                                    ask  = spec.ask(prices_all[buy_t])
                                    cost = buy_q * ask
                                    st.caption(
                                        f"Ask: {_fmt(ask)}  •  "
                                        f"Cost: {_fmt(cost)}  •  "
                                        f"Cash: {_fmt(p.current_account)}"
                                        + ("  ⚠️ Insufficient" if cost > p.current_account else "")
                                    )
                            if st.button("Execute Buy", key=f"do_buy_{rk}"):
                                if buy_t == "(none)" or buy_q <= 0:
                                    st.warning("Select a bond and enter a quantity.")
                                else:
                                    p2  = _load_portfolio(gn)
                                    process_maturities(p2, r, prices_all)
                                    res = execute_buy(p2, buy_t, buy_q, prices_all.get(buy_t, 0))
                                    _save_portfolio(p2)
                                    if res["cost"] > 0:
                                        st.session_state.logs.setdefault(gn, []).append({
                                            "round": r + 1, "withdrawal": w,
                                            "actions": [("buy", {
                                                "ticker": buy_t,
                                                "qty":    round(res["qty"], 2),
                                                "cost":   round(res["cost"], 2),
                                            })],
                                        })
                                        st.success(
                                            f"Bought {res['qty']:,.2f} {buy_t} "
                                            f"for {_fmt(res['cost'])}."
                                        )
                                        _safe_rerun()
                                    else:
                                        st.error("Buy failed — insufficient cash.")

                else:
                    st.caption("👁 Read-only view (not your group).")


# ── Controls ──────────────────────────────────────────────────────────────────
st.divider()
lft, rgt = st.columns([3, 1])
lft.subheader("Controls")

if role == "Host" and r < st.session_state.rounds:
    with rgt:
        if st.button("Next Round ▶️"):
            # Sync from files
            all_raw = _load_all_portfolios()
            for p in st.session_state.portfolios:
                if p.name in all_raw:
                    fresh = _p_from_dict(all_raw[p.name])
                    p.current_account  = fresh.current_account
                    p.pos_qty          = fresh.pos_qty
                    p.pnl_realized     = fresh.pnl_realized
                    p.shortfall_total  = fresh.shortfall_total
                    p.penalty_total    = fresh.penalty_total
                    p.repo_liabilities = fresh.repo_liabilities
                    p.td_assets        = fresh.td_assets
                    p.securities       = fresh.securities

            # Process maturities then auto-debit withdrawals for each group
            for p in st.session_state.portfolios:
                wlist = st.session_state.withdrawals.get(p.name, [])
                w = float(wlist[r]) if r < len(wlist) else 0.0
                events = process_maturities(p, r, prices_all)
                result = apply_withdrawal(p, w)
                # Log the withdrawal outcome
                st.session_state.logs.setdefault(p.name, []).append({
                    "round": r + 1,
                    "withdrawal": w,
                    "actions": [("withdrawal", result)],
                    "maturity_events": events,
                })
                _save_portfolio(p)

            # Advance round
            new_round = r + 1
            st.session_state.current_round = new_round
            _json_mutate(SHARED_STATE_PATH, {},
                lambda s: {**s, "current_round": new_round, "ts": _now()})
            _safe_rerun()
elif role == "Player":
    with rgt:
        st.caption("Only the Host can advance rounds.")


# ── End game ──────────────────────────────────────────────────────────────────
if r >= st.session_state.rounds:
    last_ix = min(st.session_state.rounds - 1, len(df) - 1)
    _, final_px = _prices_for_round(last_ix)

    st.header("🏁 Final Results")

    if role == "Host":
        st.info("💡 Click **Refresh 🔄** above to sync the latest player actions before reading scores.")
        source_portfolios = st.session_state.portfolios
    else:
        all_raw = _load_all_portfolios()
        source_portfolios = [_p_from_dict(d) for d in all_raw.values()]

    rows = []
    for p in source_portfolios:
        s = p.summary(final_px)
        rows.append({
            "Group":            p.name,
            "Total Reserve":    s["total_mv"],
            "Cash":             s["current_account"],
            "Securities":       s["securities_mv"],
            "Term Deposits":    s["td_invested"],
            "Repo Owed":        s["repo_outstanding"],
            "PnL Realized":     s["pnl_realized"],
            "Penalties":        s["penalty_total"],
            "Net Score":        s["net_score"],
        })

    if rows:
        rows.sort(key=lambda x: x["Net Score"], reverse=True)
        medals = ["🥇","🥈","🥉"] + [f"#{i+4}" for i in range(len(rows))]
        for i, row in enumerate(rows):
            row["Rank"] = medals[i]

        sb_raw = pd.DataFrame(rows)
        sb_fmt = sb_raw.copy()
        for col in ["Total Reserve","Cash","Securities","Term Deposits",
                    "Repo Owed","PnL Realized","Penalties","Net Score"]:
            if col in sb_fmt.columns:
                sb_fmt[col] = sb_fmt[col].apply(_fmt)

        col_order = ["Rank","Group","Net Score","Total Reserve","Cash",
                     "Securities","Term Deposits","Repo Owed","PnL Realized","Penalties"]
        st.dataframe(sb_fmt[[c for c in col_order if c in sb_fmt.columns]],
                     use_container_width=True, hide_index=True)

        if role == "Host":
            st.download_button("⬇️ Download scoreboard CSV",
                               sb_raw.to_csv(index=False).encode(),
                               file_name="scoreboard.csv", mime="text/csv")
            st.download_button("⬇️ Download logs JSON",
                               json.dumps(st.session_state.logs, indent=2).encode(),
                               file_name="logs.json", mime="application/json")
        else:
            shared = _json_read(SHARED_STATE_PATH, {})
            my_groups = [g for g, o in shared.get("claims", {}).items()
                         if o == st.session_state.player_name.strip()]
            if my_groups:
                st.success(f"You played as: **{', '.join(my_groups)}**")
    st.stop()
