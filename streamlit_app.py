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

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Liquidity Management Simulation",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

/* ── Base ── */
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp {
    background: #080E1A;
    color: #E2E8F0;
}

/* ── Hide default Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.5rem 2rem 2rem; max-width: 1400px; }

/* ── Headings ── */
h1, h2, h3, h4 { font-family: 'Syne', sans-serif !important; color: #F1F5F9 !important; letter-spacing: -0.02em; }
h1 { font-size: 1.9rem !important; font-weight: 800 !important; }
h2 { font-size: 1.4rem !important; font-weight: 700 !important; }
h3 { font-size: 1.1rem !important; font-weight: 600 !important; }

/* ── Paragraphs & captions ── */
p, .stMarkdown p { color: #94A3B8 !important; }
.stCaption, .stCaption p, small { color: #64748B !important; font-size: 0.78rem !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: #0D1625 !important;
    border-right: 1px solid #1E2D45;
}
section[data-testid="stSidebar"] * { color: #CBD5E1 !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: #F1F5F9 !important; }
section[data-testid="stSidebar"] .stMarkdown p { color: #94A3B8 !important; }

/* Sidebar inputs */
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] select,
section[data-testid="stSidebar"] textarea {
    background: #131F33 !important;
    border: 1px solid #2A3F5F !important;
    color: #E2E8F0 !important;
    border-radius: 6px !important;
}
section[data-testid="stSidebar"] .stSelectbox > div > div {
    background: #131F33 !important;
    border: 1px solid #2A3F5F !important;
    border-radius: 6px !important;
}

/* ── Buttons ── */
div.stButton > button {
    background: #1D4ED8 !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    padding: 0.5rem 1.2rem !important;
    transition: all 0.15s ease !important;
    letter-spacing: 0.01em !important;
}
div.stButton > button:hover {
    background: #1E40AF !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 14px rgba(29, 78, 216, 0.35) !important;
}
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1D4ED8, #2563EB) !important;
    box-shadow: 0 2px 8px rgba(29, 78, 216, 0.3) !important;
}

/* ── Text inputs & number inputs ── */
.stTextInput input, .stNumberInput input {
    background: #0D1625 !important;
    border: 1px solid #1E2D45 !important;
    color: #E2E8F0 !important;
    border-radius: 8px !important;
    font-family: 'DM Mono', monospace !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
    border-color: #2563EB !important;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2) !important;
}
.stNumberInput button {
    background: #1E2D45 !important;
    color: #94A3B8 !important;
    border: none !important;
}

/* ── Selectbox ── */
.stSelectbox > div > div {
    background: #0D1625 !important;
    border: 1px solid #1E2D45 !important;
    color: #E2E8F0 !important;
    border-radius: 8px !important;
}
.stSelectbox svg { fill: #94A3B8 !important; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid #1E2D45;
    gap: 0;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #64748B !important;
    border: none !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    padding: 0.6rem 1.2rem !important;
    border-bottom: 2px solid transparent !important;
    margin-bottom: -1px !important;
}
.stTabs [aria-selected="true"] {
    background: transparent !important;
    color: #60A5FA !important;
    border-bottom: 2px solid #2563EB !important;
}
.stTabs [data-baseweb="tab-panel"] {
    background: transparent !important;
    padding-top: 1.5rem !important;
}

/* ── Expanders ── */
.streamlit-expanderHeader {
    background: #0D1625 !important;
    border: 1px solid #1E2D45 !important;
    border-radius: 8px !important;
    color: #94A3B8 !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
}
.streamlit-expanderContent {
    background: #0A1220 !important;
    border: 1px solid #1E2D45 !important;
    border-top: none !important;
    border-radius: 0 0 8px 8px !important;
}

/* ── Metrics (override completely) ── */
[data-testid="stMetric"] {
    background: #0D1625 !important;
    border: 1px solid #1E2D45 !important;
    border-radius: 10px !important;
    padding: 0.9rem 1rem !important;
}
[data-testid="stMetricLabel"] { color: #64748B !important; font-size: 0.72rem !important; font-weight: 600 !important; text-transform: uppercase !important; letter-spacing: 0.05em !important; }
[data-testid="stMetricValue"] { color: #F1F5F9 !important; font-family: 'DM Mono', monospace !important; font-size: 1.15rem !important; font-weight: 500 !important; }
[data-testid="stMetricDelta"] { font-size: 0.72rem !important; }

/* ── Progress bar ── */
.stProgress > div > div {
    background: #1E2D45 !important;
    border-radius: 4px !important;
}
.stProgress > div > div > div {
    background: linear-gradient(90deg, #1D4ED8, #60A5FA) !important;
    border-radius: 4px !important;
}

/* ── Alerts ── */
.stSuccess { background: rgba(16, 185, 129, 0.1) !important; border-left: 3px solid #10B981 !important; border-radius: 8px !important; }
.stWarning { background: rgba(245, 158, 11, 0.1) !important; border-left: 3px solid #F59E0B !important; border-radius: 8px !important; }
.stError   { background: rgba(239, 68, 68, 0.1)  !important; border-left: 3px solid #EF4444  !important; border-radius: 8px !important; }
.stInfo    { background: rgba(59, 130, 246, 0.1)  !important; border-left: 3px solid #3B82F6  !important; border-radius: 8px !important; }
.stSuccess *, .stWarning *, .stError *, .stInfo * { color: #E2E8F0 !important; }

/* ── Divider ── */
hr { border-color: #1E2D45 !important; margin: 1.2rem 0 !important; }

/* ── Dataframe ── */
.stDataFrame { border: 1px solid #1E2D45 !important; border-radius: 10px !important; overflow: hidden !important; }
.stDataFrame th { background: #0D1625 !important; color: #64748B !important; font-size: 0.72rem !important; text-transform: uppercase !important; letter-spacing: 0.05em !important; border-bottom: 1px solid #1E2D45 !important; }
.stDataFrame td { background: #080E1A !important; color: #E2E8F0 !important; font-family: 'DM Mono', monospace !important; font-size: 0.82rem !important; border-bottom: 1px solid #111827 !important; }
.stDataFrame tr:hover td { background: #0D1625 !important; }

/* ── File uploader ── */
[data-testid="stFileUploader"] {
    background: #0D1625 !important;
    border: 1px dashed #2A3F5F !important;
    border-radius: 10px !important;
}

/* ── Radio ── */
.stRadio label { color: #94A3B8 !important; }
.stRadio [data-testid="stMarkdownContainer"] p { color: #94A3B8 !important; }

/* ── Custom components ── */
.app-header {
    background: linear-gradient(135deg, #0D1625 0%, #111827 100%);
    border: 1px solid #1E2D45;
    border-radius: 14px;
    padding: 1.4rem 1.8rem;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.app-header-title {
    font-family: 'Syne', sans-serif;
    font-size: 1.5rem;
    font-weight: 800;
    color: #F1F5F9;
    letter-spacing: -0.03em;
}
.app-header-title span { color: #3B82F6; }
.app-header-meta {
    font-family: 'DM Mono', monospace;
    font-size: 0.78rem;
    color: #475569;
    text-align: right;
    line-height: 1.8;
}

.round-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    background: #131F33;
    border: 1px solid #2A3F5F;
    border-radius: 100px;
    padding: 0.35rem 1rem;
    font-family: 'DM Mono', monospace;
    font-size: 0.78rem;
    color: #60A5FA;
    font-weight: 500;
}

.rate-strip {
    background: #0D1625;
    border: 1px solid #1E2D45;
    border-radius: 10px;
    padding: 0.75rem 1.2rem;
    display: flex;
    gap: 2rem;
    align-items: center;
    margin-bottom: 1.2rem;
    flex-wrap: wrap;
}
.rate-item { display: flex; flex-direction: column; }
.rate-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.07em; color: #475569; font-weight: 600; }
.rate-value { font-family: 'DM Mono', monospace; font-size: 0.92rem; color: #E2E8F0; font-weight: 500; }
.rate-value.green  { color: #34D399; }
.rate-value.amber  { color: #FBBF24; }
.rate-value.red    { color: #F87171; }

.portfolio-card {
    background: #0D1625;
    border: 1px solid #1E2D45;
    border-radius: 14px;
    padding: 1.2rem;
    height: 100%;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s;
}
.portfolio-card.ready  { border-color: #065F46; }
.portfolio-card.short  { border-color: #7C1D1D; }
.portfolio-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    border-radius: 14px 14px 0 0;
}
.portfolio-card.ready::before  { background: linear-gradient(90deg, #059669, #34D399); }
.portfolio-card.short::before  { background: linear-gradient(90deg, #DC2626, #F87171); }
.portfolio-card.neutral::before { background: linear-gradient(90deg, #1D4ED8, #60A5FA); }

.card-name {
    font-family: 'Syne', sans-serif;
    font-size: 0.9rem;
    font-weight: 700;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.5rem;
}
.card-value {
    font-family: 'DM Mono', monospace;
    font-size: 1.6rem;
    font-weight: 500;
    color: #F1F5F9;
    line-height: 1.1;
    margin-bottom: 0.3rem;
}
.card-sub {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: #475569;
    margin-bottom: 0.8rem;
}
.card-pill {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 100px;
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.pill-ready  { background: rgba(5, 150, 105, 0.15); color: #34D399; border: 1px solid rgba(52, 211, 153, 0.3); }
.pill-short  { background: rgba(220, 38, 38, 0.15);  color: #F87171; border: 1px solid rgba(248, 113, 113, 0.3); }
.pill-neutral { background: rgba(29, 78, 216, 0.15); color: #60A5FA; border: 1px solid rgba(96, 165, 250, 0.3); }
.pill-amber  { background: rgba(245, 158, 11, 0.15); color: #FBBF24; border: 1px solid rgba(251, 191, 36, 0.3); }

.ticker-row {
    display: flex;
    justify-content: space-between;
    padding: 0.3rem 0;
    border-bottom: 1px solid #111827;
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
}
.ticker-row:last-child { border-bottom: none; }
.ticker-name { color: #64748B; }
.ticker-qty  { color: #94A3B8; }
.ticker-price { color: #60A5FA; }

.penalty-badge {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-top: 0.6rem;
    padding: 0.3rem 0.6rem;
    background: rgba(220, 38, 38, 0.1);
    border: 1px solid rgba(248, 113, 113, 0.2);
    border-radius: 6px;
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: #F87171;
}

.section-header {
    font-family: 'Syne', sans-serif;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #475569;
    padding: 0.5rem 0;
    margin-bottom: 0.5rem;
    border-bottom: 1px solid #1E2D45;
}

.coverage-tracker {
    background: #0D1625;
    border: 1px solid #1E2D45;
    border-radius: 12px;
    padding: 1rem 1.2rem;
    margin: 1rem 0;
}
.coverage-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: 'DM Mono', monospace;
    font-size: 0.82rem;
    padding: 0.25rem 0;
    color: #94A3B8;
}
.coverage-row .label { color: #64748B; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; }
.coverage-row .val   { color: #E2E8F0; }
.coverage-status {
    margin-top: 0.8rem;
    padding-top: 0.8rem;
    border-top: 1px solid #1E2D45;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.coverage-status .target { font-family: 'DM Mono', monospace; font-size: 0.78rem; color: #64748B; }
.coverage-status .result { font-family: 'DM Mono', monospace; font-size: 1rem; font-weight: 600; }
.coverage-status .result.ok  { color: #34D399; }
.coverage-status .result.bad { color: #F87171; }

.action-box {
    background: #0A1220;
    border: 1px solid #1E2D45;
    border-radius: 10px;
    padding: 1rem;
    margin-bottom: 0.8rem;
}
.action-box-title {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.78rem;
    font-weight: 600;
    color: #64748B;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 0.7rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}

.spec-row {
    display: flex;
    justify-content: space-between;
    padding: 0.5rem 0.8rem;
    border-bottom: 1px solid #111827;
    font-size: 0.8rem;
}
.spec-row:last-child { border-bottom: none; }
.spec-name { color: #94A3B8; font-weight: 500; }
.spec-detail { font-family: 'DM Mono', monospace; color: #60A5FA; font-size: 0.75rem; }
.liq-high   { color: #34D399 !important; }
.liq-medium { color: #FBBF24 !important; }
.liq-low    { color: #F87171 !important; }

.host-controls {
    background: #0D1625;
    border: 1px solid #1E2D45;
    border-radius: 12px;
    padding: 1rem 1.4rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    margin-top: 1.5rem;
}
.host-controls-label {
    font-size: 0.8rem;
    color: #64748B;
}

.scoreboard-card {
    background: #0D1625;
    border: 1px solid #1E2D45;
    border-radius: 14px;
    padding: 1.5rem;
    text-align: center;
    margin-bottom: 1rem;
}
.rank-medal { font-size: 2.5rem; line-height: 1; margin-bottom: 0.5rem; }
.score-name { font-family: 'Syne', sans-serif; font-size: 1rem; font-weight: 700; color: #F1F5F9; margin-bottom: 0.3rem; }
.score-val  { font-family: 'DM Mono', monospace; font-size: 1.4rem; color: #34D399; font-weight: 500; }

.history-entry {
    background: #0A1220;
    border: 1px solid #111827;
    border-radius: 8px;
    padding: 0.7rem 0.9rem;
    margin-bottom: 0.5rem;
}
.history-round { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.07em; color: #475569; margin-bottom: 0.4rem; }
.history-action { font-family: 'DM Mono', monospace; font-size: 0.75rem; color: #94A3B8; padding: 0.15rem 0; }

.waiting-screen {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 4rem 2rem;
    text-align: center;
}
.waiting-icon { font-size: 3rem; margin-bottom: 1rem; }
.waiting-title { font-family: 'Syne', sans-serif; font-size: 1.4rem; font-weight: 700; color: #F1F5F9; margin-bottom: 0.5rem; }
.waiting-sub { color: #475569; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

# ── Config ────────────────────────────────────────────────────────────────────
BASE_REPO_RATE_PA  = 0.045
BASE_TD_RATE_PA    = 0.050
RATE_SPREAD_PA     = 0.005
MAX_GROUPS_UI      = 8
TOTAL_RESERVE      = 200_000.0

SHARED_STATE_PATH  = ".shared_state.json"
UPLOADED_CSV_PATH  = ".uploaded.csv"
SNAPSHOT_PATH      = ".snapshot.json"
PORTFOLIO_DIR      = "."

# ── File helpers ──────────────────────────────────────────────────────────────
def _portfolio_path(name: str) -> str:
    return os.path.join(PORTFOLIO_DIR, f".portfolio_{name.replace(' ','_')}.json")
def _all_portfolio_paths() -> List[str]:
    return sorted(glob.glob(os.path.join(PORTFOLIO_DIR, ".portfolio_*.json")))
def _json_read(path: str, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default
def _json_write(path: str, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(payload, f)
    os.replace(tmp, path)
def _json_mutate(path: str, default, fn):
    data = _json_read(path, default)
    new  = fn(data if isinstance(data, (dict, list)) else default)
    _json_write(path, new); return new
def _now() -> float: return time.time()
def _fmt(x: float, nd: int = 2) -> str:
    try:    return f"${x:,.{nd}f}"
    except: return f"${x}"
def _safe_rerun():
    try:    st.rerun()
    except:
        try: st.experimental_rerun()
        except: pass

# ── Portfolio serialisation ───────────────────────────────────────────────────
def _p_to_dict(p: Portfolio) -> dict:
    return {
        "name": p.name, "current_account": p.current_account,
        "pos_qty": dict(p.pos_qty), "pnl_realized": p.pnl_realized,
        "shortfall_total": p.shortfall_total, "penalty_total": p.penalty_total,
        "repo_liabilities": list(p.repo_liabilities), "td_assets": list(p.td_assets),
        "securities": {t: {"ticker": s.ticker, "face_price": s.face_price,
            "bid_ask_bps": s.bid_ask_bps, "liquidity_score": s.liquidity_score}
            for t, s in p.securities.items()},
        "last_updated": _now(),
    }
def _p_from_dict(d: dict) -> Portfolio:
    p = Portfolio(name=d["name"], current_account=d["current_account"],
        pnl_realized=d.get("pnl_realized",0.0), shortfall_total=d.get("shortfall_total",0.0),
        penalty_total=d.get("penalty_total",0.0))
    p.pos_qty = d.get("pos_qty",{}); p.repo_liabilities = d.get("repo_liabilities",[])
    p.td_assets = d.get("td_assets",[])
    for t, s in d.get("securities",{}).items():
        p.securities[t] = SecuritySpec(ticker=s["ticker"], face_price=s.get("face_price",100.0),
            bid_ask_bps=s.get("bid_ask_bps",20.0), liquidity_score=s.get("liquidity_score",2))
    return p
def _load_portfolio(name: str) -> Optional[Portfolio]:
    d = _json_read(_portfolio_path(name), None)
    return _p_from_dict(d) if d else None
def _save_portfolio(p: Portfolio): _json_write(_portfolio_path(p.name), _p_to_dict(p))
def _load_all_portfolios() -> Dict[str, dict]:
    result = {}
    for path in _all_portfolio_paths():
        d = _json_read(path, None)
        if d and "name" in d: result[d["name"]] = d
    return result

# ── Rate helpers ──────────────────────────────────────────────────────────────
def _rates_for_round(r: int) -> Tuple[float, float]:
    rng = random.Random(st.session_state.rng_seed * 991 + r * 7919)
    repo_pa = max(0.005, BASE_REPO_RATE_PA + rng.uniform(-RATE_SPREAD_PA, RATE_SPREAD_PA))
    td_pa   = max(0.005, BASE_TD_RATE_PA   + rng.uniform(-RATE_SPREAD_PA, RATE_SPREAD_PA))
    return repo_pa, td_pa
def _prices_for_round(r: int) -> Tuple[str, Dict[str, float]]:
    df = st.session_state.price_df
    ix = min(r, len(df) - 1)
    tickers = [c for c in df.columns if c != "date"]
    return str(df.loc[ix, "date"]), {t: float(df.loc[ix, t]) for t in tickers}

# ── Session state bootstrap ───────────────────────────────────────────────────
def _init_state():
    ss = st.session_state
    ss.initialized=False; ss.rng_seed=1234; ss.rounds=4; ss.current_round=0
    ss.withdrawals={}; ss.portfolios=[]; ss.logs={}; ss.price_df=None
    ss.maturity_events={}; ss.num_groups=4; ss.role="Host"
    ss.player_group_idx=0; ss.player_name=""
if "initialized" not in st.session_state: _init_state()

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown(
    "<div style='font-family:Syne,sans-serif;font-size:1.1rem;font-weight:800;"
    "color:#F1F5F9;letter-spacing:-0.02em;padding:0.5rem 0 1rem;'>"
    "🏦 Liquidity Sim</div>", unsafe_allow_html=True)

st.sidebar.markdown("<div class='section-header'>Session Role</div>", unsafe_allow_html=True)
role = st.sidebar.radio("", ["Host", "Player"],
    index=0 if st.session_state.role == "Host" else 1,
    label_visibility="collapsed")
st.session_state.role = role

if role == "Host":
    st.sidebar.markdown("<div class='section-header' style='margin-top:1rem;'>Game Setup</div>", unsafe_allow_html=True)
    uploaded = st.sidebar.file_uploader("Price file (.csv or .xlsx)", type=["csv","xlsx"])
    col_s, col_r = st.sidebar.columns(2)
    seed   = col_s.number_input("RNG Seed", value=st.session_state.rng_seed, step=1)
    rounds = col_r.number_input("Rounds", value=st.session_state.rounds, min_value=2, max_value=10, step=1)
    groups = st.sidebar.number_input("Groups", value=st.session_state.num_groups, min_value=1, max_value=MAX_GROUPS_UI, step=1)
    st.sidebar.markdown("")
    c1, c2 = st.sidebar.columns(2)
    start_btn   = c1.button("▶ Start", type="primary", use_container_width=True)
    refresh_btn = c2.button("↻ Refresh", use_container_width=True)
    end_btn     = st.sidebar.button("⏹ End Game", use_container_width=True)

    with st.sidebar.expander("📥 Template"):
        import io
        sample = pd.DataFrame({
            "date":   ["2025-01-01","2025-02-01","2025-03-01","2025-04-01","2025-05-01","2025-06-01"],
            "BOND_A": [100.60,100.64,100.05,100.32,99.85,102.91],
            "BOND_B": [101.01,100.97,101.15,104.74,99.81,102.99],
            "BOND_C": [100.04,101.59,99.77,69.99,101.53,100.70],
        })
        buf = io.BytesIO(); sample.to_excel(buf, index=False)
        st.download_button("Download template.xlsx", buf.getvalue(),
            file_name="template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.sidebar.markdown("<div class='section-header' style='margin-top:1rem;'>Player Info</div>", unsafe_allow_html=True)
    st.session_state.player_name = st.sidebar.text_input("Your name", value=st.session_state.player_name or "", placeholder="Enter name…")
    uploaded = None; start_btn = refresh_btn = end_btn = False
    if _HAS_AUTOREFRESH: st_autorefresh(interval=5000, key="player_autorefresh")
    if not os.path.exists(SNAPSHOT_PATH):
        st.sidebar.markdown("<div style='color:#475569;font-size:0.78rem;padding:0.5rem 0;'>⏳ Waiting for host…</div>", unsafe_allow_html=True)
    else:
        shared = _json_read(SHARED_STATE_PATH, {})
        if shared.get("initialized"):
            st.sidebar.markdown(
                f"<div style='font-family:DM Mono,monospace;font-size:0.72rem;color:#475569;line-height:2;'>"
                f"Rounds: {shared.get('rounds')} &nbsp;·&nbsp; Groups: {shared.get('num_groups')}"
                f"</div>", unsafe_allow_html=True)

st.sidebar.markdown("<div class='section-header' style='margin-top:1rem;'>Rules</div>", unsafe_allow_html=True)
with st.sidebar.expander("How to play"):
    st.markdown(f"""
Raise enough cash each round to cover your **withdrawal target** before the Host advances.

Use any combination of:
- **Repo** — borrow against bonds
- **Sell bonds** — at bid price
- **Redeem TD** — {TD_PENALTY_RATE*100:.1f}% early penalty

Invest spare cash in **Term Deposits** to earn yield (matures R+2).

If you fall short → **{SHORTFALL_PENALTY*100:.0f}% penalty** on uncovered amount.

**Net Score** = Total Reserve − Cumulative Penalties.
""")

# ── Start / End (Host) ────────────────────────────────────────────────────────
if role == "Host" and start_btn:
    if uploaded is None:
        st.sidebar.error("Upload a price file first.")
    else:
        df = pd.read_excel(uploaded) if uploaded.name.endswith(".xlsx") else pd.read_csv(uploaded)
        bond_cols = [c for c in df.columns if c != "date"]
        if "date" not in df.columns or len(bond_cols) < 2:
            st.sidebar.error("Need 'date' column + at least 2 bond columns.")
        else:
            with open(UPLOADED_CSV_PATH, "wb") as f: f.write(uploaded.getbuffer())
            seed_val=int(seed); rounds_val=int(rounds); cap=min(MAX_GROUPS_UI,int(groups))
            _init_state()
            st.session_state.initialized=True; st.session_state.rng_seed=seed_val
            st.session_state.rounds=rounds_val; st.session_state.num_groups=cap
            st.session_state.price_df=df.reset_index(drop=True)
            price_history={t: df[t].dropna().tolist() for t in bond_cols}
            specs=derive_security_specs(price_history)
            _, prices0=_prices_for_round(0)
            portfolios=init_portfolios(tickers=bond_cols,specs=specs,prices=prices0,
                num_groups=cap,total_reserve=TOTAL_RESERVE,seed=seed_val)
            rng_td=random.Random(seed_val^0xA5A5); _,td_pa0=_rates_for_round(0)
            for p in portfolios:
                frac=rng_td.uniform(0.10,0.30); amt=round(p.current_account*frac,2)
                if amt>0: execute_invest_td(p,amt,0,td_pa0)
            st.session_state.portfolios=portfolios
            withdrawals={}
            for p in portfolios:
                rng_w=random.Random(seed_val+hash(p.name)); mv0=p.market_value(prices0)
                withdrawals[p.name]=[generate_withdrawal(r,mv0,rng_w) for r in range(rounds_val)]
            st.session_state.withdrawals=withdrawals
            st.session_state.logs={p.name:[] for p in portfolios}
            st.session_state.maturity_events={p.name:[] for p in portfolios}
            for old in _all_portfolio_paths():
                try: os.remove(old)
                except: pass
            if os.path.exists(SNAPSHOT_PATH): os.remove(SNAPSHOT_PATH)
            for p in portfolios: _save_portfolio(p)
            _json_write(SHARED_STATE_PATH, {"initialized":True,"rng_seed":seed_val,
                "rounds":rounds_val,"num_groups":cap,"current_round":0,
                "withdrawals":withdrawals,
                "specs":{t:{"ticker":s.ticker,"face_price":s.face_price,
                    "bid_ask_bps":s.bid_ask_bps,"liquidity_score":s.liquidity_score}
                    for t,s in specs.items()},
                "claims":{},"ts":_now()})
            _json_write(SNAPSHOT_PATH,{"published":True,"ts":_now()})
            _safe_rerun()

if role=="Host" and end_btn and st.session_state.initialized:
    _json_mutate(SHARED_STATE_PATH,{},
        lambda s:{**s,"current_round":s.get("rounds",st.session_state.rounds),"ts":_now()})
    st.session_state.current_round=st.session_state.rounds; _safe_rerun()

# ── Player bootstrap ──────────────────────────────────────────────────────────
if role=="Player" and not st.session_state.initialized:
    if not os.path.exists(SNAPSHOT_PATH):
        st.markdown("""<div class='waiting-screen'>
            <div class='waiting-icon'>⏳</div>
            <div class='waiting-title'>Waiting for Host</div>
            <div class='waiting-sub'>The host hasn't started the session yet. Stand by.</div>
        </div>""", unsafe_allow_html=True); st.stop()
    shared=_json_read(SHARED_STATE_PATH,{})
    if not shared.get("initialized"):
        st.markdown("""<div class='waiting-screen'>
            <div class='waiting-icon'>⚙️</div>
            <div class='waiting-title'>Host is setting up…</div>
            <div class='waiting-sub'>The session will begin shortly.</div>
        </div>""", unsafe_allow_html=True); st.stop()
    if not os.path.exists(UPLOADED_CSV_PATH):
        st.info("Waiting for price data…"); st.stop()
    df_raw=pd.read_csv(UPLOADED_CSV_PATH) if UPLOADED_CSV_PATH.endswith(".csv") else pd.read_excel(UPLOADED_CSV_PATH)
    _init_state()
    st.session_state.initialized=True
    st.session_state.rng_seed=int(shared.get("rng_seed",1234))
    st.session_state.rounds=int(shared.get("rounds",4))
    st.session_state.num_groups=int(shared.get("num_groups",4))
    st.session_state.price_df=df_raw.reset_index(drop=True)
    st.session_state.current_round=int(shared.get("current_round",0))
    st.session_state.withdrawals=shared.get("withdrawals",{})
    st.session_state.logs={}; st.session_state.maturity_events={}

if not st.session_state.initialized:
    st.markdown("""<div class='waiting-screen'>
        <div class='waiting-icon'>🏦</div>
        <div class='waiting-title'>Liquidity Management Simulation</div>
        <div class='waiting-sub'>Upload a price file and click <strong>▶ Start</strong> to begin.</div>
    </div>""", unsafe_allow_html=True); st.stop()

# Sync round for players
if role=="Player":
    shared=_json_read(SHARED_STATE_PATH,{})
    if shared.get("initialized"):
        host_round=int(shared.get("current_round",0))
        if host_round!=st.session_state.current_round:
            st.session_state.current_round=host_round
            st.session_state.withdrawals=shared.get("withdrawals",st.session_state.withdrawals)

df=st.session_state.price_df
all_tickers=[c for c in df.columns if c!="date"]
r=st.session_state.current_round; NG=st.session_state.num_groups
date_str,prices_all=_prices_for_round(r)
repo_pa,td_pa=_rates_for_round(r)
tickers_ui=all_tickers[:4]

# ── Host refresh ──────────────────────────────────────────────────────────────
if role=="Host" and st.session_state.portfolios and refresh_btn:
    all_raw=_load_all_portfolios()
    for p in st.session_state.portfolios:
        if p.name in all_raw:
            fresh=_p_from_dict(all_raw[p.name])
            p.current_account=fresh.current_account; p.pos_qty=fresh.pos_qty
            p.pnl_realized=fresh.pnl_realized; p.shortfall_total=fresh.shortfall_total
            p.penalty_total=fresh.penalty_total; p.repo_liabilities=fresh.repo_liabilities
            p.td_assets=fresh.td_assets; p.securities=fresh.securities
    _safe_rerun()

# ── Player group claim ────────────────────────────────────────────────────────
if role=="Player":
    shared=_json_read(SHARED_STATE_PATH,{}); all_raw=_load_all_portfolios()
    group_names=list(all_raw.keys())
    if not group_names:
        st.info("Waiting for Host to initialise groups…"); st.stop()
    claims:Dict[str,str]=shared.get("claims",{})
    valid_idx=min(max(st.session_state.player_group_idx,0),len(group_names)-1)
    st.session_state.player_group_idx=valid_idx
    chosen=st.sidebar.selectbox("Select Group",group_names,index=valid_idx,key="group_sel")
    st.session_state.player_group_idx=group_names.index(chosen)
    if st.sidebar.button("⚑ Claim Group",disabled=not st.session_state.player_name.strip(),
                          use_container_width=True):
        def _claim(s):
            s=dict(s or {}); s.setdefault("claims",{})
            if chosen not in s["claims"]: s["claims"][chosen]=st.session_state.player_name.strip()
            return s
        before=_json_read(SHARED_STATE_PATH,{}); after=_json_mutate(SHARED_STATE_PATH,{},_claim)
        if after.get("claims",{}).get(chosen)!=before.get("claims",{}).get(chosen):
            st.sidebar.success(f"Claimed {chosen} ✓")
        else: st.sidebar.warning("Already claimed.")
    you_own=claims.get(chosen,"")==st.session_state.player_name.strip()

# ── APP HEADER ────────────────────────────────────────────────────────────────
rounds_total=st.session_state.rounds
round_dots="".join(
    [f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:#2563EB;margin:0 2px;'></span>" if i<r
     else f"<span style='display:inline-block;width:10px;height:10px;border-radius:50%;background:#60A5FA;border:2px solid #93C5FD;margin:0 2px;'></span>" if i==r
     else f"<span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:#1E2D45;margin:0 2px;'></span>"
     for i in range(rounds_total)]
)
st.markdown(f"""
<div class='app-header'>
    <div>
        <div class='app-header-title'>Liquidity <span>Management</span> Simulation</div>
        <div style='margin-top:0.5rem;display:flex;align-items:center;gap:0.8rem;'>
            <span class='round-badge'>Round {r+1} of {rounds_total}</span>
            <div style='display:inline-flex;align-items:center;gap:2px;'>{round_dots}</div>
        </div>
    </div>
    <div class='app-header-meta'>
        <div>{date_str}</div>
        <div>{'HOST VIEW' if role=='Host' else f'PLAYER — {st.session_state.player_name or "Anonymous"}'}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── RATE STRIP ────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class='rate-strip'>
    <div class='rate-item'>
        <span class='rate-label'>Repo Rate</span>
        <span class='rate-value amber'>{repo_pa*100:.2f}% p.a.</span>
    </div>
    <div class='rate-item'>
        <span class='rate-label'>TD Rate</span>
        <span class='rate-value green'>{td_pa*100:.2f}% p.a.</span>
    </div>
    <div class='rate-item'>
        <span class='rate-label'>Monthly Repo</span>
        <span class='rate-value'>{monthly_rate(repo_pa)*100:.3f}%</span>
    </div>
    <div class='rate-item'>
        <span class='rate-label'>Monthly TD</span>
        <span class='rate-value'>{monthly_rate(td_pa)*100:.3f}%</span>
    </div>
    <div class='rate-item'>
        <span class='rate-label'>Early TD Penalty</span>
        <span class='rate-value red'>{TD_PENALTY_RATE*100:.1f}%</span>
    </div>
    <div class='rate-item'>
        <span class='rate-label'>Shortfall Penalty</span>
        <span class='rate-value red'>{SHORTFALL_PENALTY*100:.0f}%</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ── PORTFOLIO OVERVIEW CARDS ──────────────────────────────────────────────────
if role=="Host": portfolios_display=st.session_state.portfolios[:NG]
else:
    all_raw=_load_all_portfolios()
    portfolios_display=[_p_from_dict(d) for d in all_raw.values()]

if portfolios_display:
    cols=st.columns(len(portfolios_display))
    for g,(col,p) in enumerate(zip(cols,portfolios_display)):
        with col:
            wlist=st.session_state.withdrawals.get(p.name,[0]*(r+1))
            w=float(wlist[r]) if r<len(wlist) else 0.0
            ca=p.current_account; ready=ca>=w
            pct=min(1.0,ca/w) if w>0 else 1.0
            state="ready" if ready else "short"
            pill_cls="pill-ready" if ready else "pill-short"
            pill_txt="✓ COVERED" if ready else "⚠ NEEDS CASH"
            tickers_html="".join(
                f"<div class='ticker-row'>"
                f"<span class='ticker-name'>{t}</span>"
                f"<span class='ticker-qty'>{p.pos_qty.get(t,0):,.0f}</span>"
                f"<span class='ticker-price'>{_fmt(prices_all.get(t,0))}</span>"
                f"</div>" for t in tickers_ui if t in p.pos_qty
            )
            penalty_html=f"<div class='penalty-badge'>⚠ Penalties {_fmt(p.penalty_total)}</div>" if p.penalty_total>0 else ""
            bar_w=int(pct*100)
            bar_col="#059669" if ready else "#DC2626"
            st.markdown(f"""
<div class='portfolio-card {state}'>
    <div class='card-name'>{p.name}</div>
    <div class='card-value'>{_fmt(p.market_value(prices_all),0)}</div>
    <div class='card-sub'>Cash {_fmt(ca,0)} &nbsp;·&nbsp; Need {_fmt(w,0)}</div>
    <span class='{pill_cls} card-pill'>{pill_txt}</span>
    <div style='margin:0.7rem 0 0.4rem;background:#111827;border-radius:4px;height:4px;'>
        <div style='width:{bar_w}%;height:4px;border-radius:4px;background:{bar_col};'></div>
    </div>
    <div style='margin-top:0.6rem;border-top:1px solid #111827;padding-top:0.6rem;'>
        {tickers_html}
    </div>
    {penalty_html}
</div>""", unsafe_allow_html=True)

# ── SECURITY DETAILS ──────────────────────────────────────────────────────────
if role=="Host": specs_src={t:p.securities[t] for p in st.session_state.portfolios[:1] for t in p.securities}
else:
    all_raw_spec=_load_all_portfolios(); first_grp=next(iter(all_raw_spec.values()),{})
    specs_src={t:SecuritySpec(**{k:v for k,v in s.items()}) for t,s in first_grp.get("securities",{}).items()}

if specs_src:
    st.markdown("")
    with st.expander("🔍 Security Details (auto-derived from price volatility)"):
        spec_rows="".join(
            f"<div class='spec-row'>"
            f"<span class='spec-name'>{t}</span>"
            f"<span class='spec-detail'>Mid {_fmt(prices_all.get(t,s.face_price))} &nbsp; "
            f"Bid {_fmt(s.bid(prices_all.get(t,s.face_price)))} &nbsp; "
            f"Ask {_fmt(s.ask(prices_all.get(t,s.face_price)))} &nbsp; "
            f"Spread {s.bid_ask_bps:.0f}bps &nbsp; "
            f"<span class='liq-{'high' if s.liquidity_score==1 else 'medium' if s.liquidity_score==2 else 'low'}'>"
            f"{'● High' if s.liquidity_score==1 else '● Medium' if s.liquidity_score==2 else '● Low'} Liquidity"
            f"</span></span></div>"
            for t,s in specs_src.items()
        )
        st.markdown(f"<div style='background:#0A1220;border:1px solid #1E2D45;border-radius:10px;padding:0.2rem 0;'>{spec_rows}</div>", unsafe_allow_html=True)

# ── DETAILED TABS ─────────────────────────────────────────────────────────────
st.markdown("")

if role=="Host":
    tabs_list=[p.name for p in st.session_state.portfolios[:NG]]
    tabs=st.tabs(tabs_list or ["Group 1"])
    for p,tab in zip(st.session_state.portfolios[:NG],tabs):
        with tab:
            wlist=st.session_state.withdrawals.get(p.name,[])
            w=float(wlist[r]) if r<len(wlist) else 0.0
            s=p.summary(prices_all)
            ca=p.current_account; gap=w-ca
            c1,c2,c3,c4,c5,c6=st.columns(6)
            c1.metric("Current Account",   _fmt(s["current_account"]))
            c2.metric("Securities Value",  _fmt(s["securities_mv"]))
            c3.metric("Term Deposits",     _fmt(s["td_invested"]))
            c4.metric("Repo Outstanding",  _fmt(s["repo_outstanding"]))
            c5.metric("PnL Realized",      _fmt(s["pnl_realized"]))
            c6.metric("Net Score",         _fmt(s["net_score"]))
            st.markdown("")
            status_col=":green" if gap<=0 else ":red"
            st.markdown(
                f"Withdrawal **{_fmt(w)}** &nbsp;·&nbsp; "
                f"Cash available {status_col}[**{_fmt(ca)}**] &nbsp;·&nbsp; "
                f"{'✅ Covered' if gap<=0 else f'⚠ Short by **{_fmt(gap)}**'} &nbsp;·&nbsp; "
                f"Penalties :red[{_fmt(s['penalty_total'])}]"
            )

else:
    # ── PLAYER TABS ───────────────────────────────────────────────────────────
    all_raw=_load_all_portfolios(); group_names_list=list(all_raw.keys())
    shared=_json_read(SHARED_STATE_PATH,{}); claims=shared.get("claims",{})
    if group_names_list:
        tabs=st.tabs(group_names_list)
        chosen_idx=st.session_state.player_group_idx
        for gi,(gn,tab) in enumerate(zip(group_names_list,tabs)):
            with tab:
                p=_load_portfolio(gn)
                if not p: st.error(f"Could not load {gn}"); continue
                is_mine=(gi==chosen_idx and claims.get(gn,"")==st.session_state.player_name.strip())
                wlist=st.session_state.withdrawals.get(gn,[])
                w=float(wlist[r]) if r<len(wlist) else 0.0
                s=p.summary(prices_all); ca=p.current_account; gap=w-ca

                # ── Metrics row ───────────────────────────────────────────────
                c1,c2,c3,c4,c5,c6=st.columns(6)
                c1.metric("Current Account",  _fmt(s["current_account"]))
                c2.metric("Securities Value", _fmt(s["securities_mv"]))
                c3.metric("Term Deposits",    _fmt(s["td_invested"]))
                c4.metric("Repo Outstanding", _fmt(s["repo_outstanding"]))
                c5.metric("PnL Realized",     _fmt(s["pnl_realized"]))
                c6.metric("Net Score",        _fmt(s["net_score"]))

                # ── Status banner ─────────────────────────────────────────────
                st.markdown("")
                if gap>0:
                    st.markdown(f"""
<div style='background:rgba(220,38,38,0.08);border:1px solid rgba(248,113,113,0.25);
border-radius:10px;padding:0.8rem 1.1rem;display:flex;align-items:center;justify-content:space-between;'>
    <span style='color:#F87171;font-weight:600;font-size:0.9rem;'>⚠ Shortfall</span>
    <span style='font-family:DM Mono,monospace;font-size:0.82rem;color:#94A3B8;'>
        Need <strong style='color:#F1F5F9;'>{_fmt(w)}</strong> &nbsp;·&nbsp;
        Have <strong style='color:#F87171;'>{_fmt(ca)}</strong> &nbsp;·&nbsp;
        Gap <strong style='color:#F87171;'>{_fmt(gap)}</strong>
    </span>
</div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""
<div style='background:rgba(5,150,105,0.08);border:1px solid rgba(52,211,153,0.25);
border-radius:10px;padding:0.8rem 1.1rem;display:flex;align-items:center;justify-content:space-between;'>
    <span style='color:#34D399;font-weight:600;font-size:0.9rem;'>✓ Covered</span>
    <span style='font-family:DM Mono,monospace;font-size:0.82rem;color:#94A3B8;'>
        Need <strong style='color:#F1F5F9;'>{_fmt(w)}</strong> &nbsp;·&nbsp;
        Have <strong style='color:#34D399;'>{_fmt(ca)}</strong> &nbsp;·&nbsp;
        Surplus <strong style='color:#34D399;'>{_fmt(-gap)}</strong>
    </span>
</div>""", unsafe_allow_html=True)

                # ── Open positions ────────────────────────────────────────────
                st.markdown("")
                info_col1, info_col2 = st.columns(2)
                with info_col1:
                    if p.td_assets:
                        with st.expander(f"📅 Term Deposits ({len(p.td_assets)})"):
                            for td in p.td_assets:
                                left=td["maturity"]-r
                                lbl=("✅ Next round" if left==1 else ("⏳ This round" if left<=0 else f"🔒 {left} rounds"))
                                interest=td["amount"]*td["rate"]
                                st.markdown(f"""
<div class='history-entry'>
    <div class='history-action'>{_fmt(td['amount'])} @ {td['annual_rate']*100:.2f}% p.a.</div>
    <div class='history-action'>+{_fmt(interest)} interest at maturity · {lbl}</div>
</div>""", unsafe_allow_html=True)
                with info_col2:
                    if p.repo_liabilities:
                        with st.expander(f"🏦 Open Repos ({len(p.repo_liabilities)})"):
                            for lib in p.repo_liabilities:
                                repay=lib["amount"]*(1+lib["rate"])
                                st.markdown(f"""
<div class='history-entry'>
    <div class='history-action'>{_fmt(lib['amount'])} on {lib['ticker']}</div>
    <div class='history-action'>Repay {_fmt(repay)} → Round {lib['maturity']}</div>
</div>""", unsafe_allow_html=True)

                # ── Action history ────────────────────────────────────────────
                group_logs=st.session_state.logs.get(gn,[])
                if group_logs:
                    with st.expander(f"📋 History ({len(group_logs)} entries)"):
                        for entry in reversed(group_logs):
                            action_lines="".join(
                                f"<div class='history-action'>"
                                + (f"🏦 Repo {a.get('ticker','')} → {_fmt(a.get('got',0))} @ {a.get('annual_rate',0)*100:.2f}% p.a." if t=="repo"
                                else f"📉 Sold {a.get('qty',0):,.2f} {a.get('ticker','')} → {_fmt(a.get('proceeds',0))} (PnL {_fmt(a.get('pnl_delta',0))})" if t=="sell"
                                else f"📈 Bought {a.get('qty',0):,.2f} {a.get('ticker','')} for {_fmt(a.get('cost',0))}" if t=="buy"
                                else f"💰 TD Invest {_fmt(a.get('amount',0))} @ {a.get('annual_rate',0)*100:.2f}% p.a." if t=="invest_td"
                                else f"🔓 TD Redeem {_fmt(a.get('principal',0))}, penalty {_fmt(a.get('penalty',0))}" if t=="redeem_td"
                                else f"💸 Withdrawal {_fmt(a.get('paid',0))} — {'✅ Covered' if a.get('covered') else '❌ Shortfall '+_fmt(a.get('shortfall',0))}" if t=="withdrawal"
                                else f"💵 Cash {_fmt(a.get('used',0))}")
                                + "</div>"
                                for t,a in entry.get("actions",[])
                            )
                            st.markdown(f"""
<div class='history-entry'>
    <div class='history-round'>Round {entry.get('round','?')} · Withdrawal {_fmt(entry.get('withdrawal',0))}</div>
    {action_lines}
</div>""", unsafe_allow_html=True)

                # ── ACTION PANEL ──────────────────────────────────────────────
                if is_mine:
                    st.markdown("")
                    st.markdown("<div class='section-header'>⚡ Actions</div>", unsafe_allow_html=True)

                    def _gf(key):
                        try: return float(st.session_state.get(key,0.0) or 0.0)
                        except: return 0.0
                    rk=f"{gn}_{r}"

                    # ── Coverage section ──────────────────────────────────────
                    st.markdown("<div style='color:#64748B;font-size:0.78rem;margin-bottom:0.8rem;'>Raise cash to cover your withdrawal. Mix and match any combination below.</div>", unsafe_allow_html=True)

                    col_repo,col_sell,col_td=st.columns(3)

                    with col_repo:
                        st.markdown("<div class='action-box-title'>🏦 Repo</div>", unsafe_allow_html=True)
                        rt_key=f"repo_t_{rk}"; ra_key=f"repo_a_{rk}"
                        st.selectbox("Collateral bond",["(none)"]+all_tickers,key=rt_key,label_visibility="collapsed")
                        st.number_input("Borrow amount ($)",min_value=0.0,step=100.0,format="%.2f",key=ra_key,label_visibility="collapsed",placeholder="Amount ($)")
                        rt=st.session_state.get(rt_key,"(none)"); ra=_gf(ra_key)
                        repo_preview=0.0
                        if rt!="(none)" and ra>0 and rt in prices_all:
                            spec=p.securities.get(rt)
                            if spec:
                                bid=spec.bid(prices_all[rt]); max_r=p.pos_qty.get(rt,0.0)*bid
                                actual=min(ra,max_r); repay_amt=actual*(1+monthly_rate(repo_pa))
                                repo_preview=actual
                                st.markdown(f"<div style='font-family:DM Mono,monospace;font-size:0.7rem;color:#64748B;'>Receive <strong style='color:#60A5FA;'>{_fmt(actual)}</strong> · Repay {_fmt(repay_amt)} · Max {_fmt(max_r)}</div>", unsafe_allow_html=True)

                    with col_sell:
                        st.markdown("<div class='action-box-title'>📉 Sell Bonds</div>", unsafe_allow_html=True)
                        sel_t_key=f"sell_t_{rk}"; sel_q_key=f"sell_q_{rk}"
                        st.selectbox("Bond to sell",["(none)"]+all_tickers,key=sel_t_key,label_visibility="collapsed")
                        st.number_input("Quantity",min_value=0.0,step=1.0,format="%.2f",key=sel_q_key,label_visibility="collapsed",placeholder="Qty")
                        sell_t=st.session_state.get(sel_t_key,"(none)"); sell_q=_gf(sel_q_key)
                        sell_preview=0.0
                        if sell_t!="(none)" and sell_q>0 and sell_t in prices_all:
                            spec=p.securities.get(sell_t)
                            if spec:
                                bid=spec.bid(prices_all[sell_t]); avail=p.pos_qty.get(sell_t,0.0)
                                actual_q=min(sell_q,avail); sell_preview=actual_q*bid
                                st.markdown(f"<div style='font-family:DM Mono,monospace;font-size:0.7rem;color:#64748B;'>Bid <strong style='color:#60A5FA;'>{_fmt(bid)}</strong> · Proceeds <strong style='color:#60A5FA;'>{_fmt(sell_preview)}</strong> · Have {avail:,.0f}</div>", unsafe_allow_html=True)

                    with col_td:
                        td_total=sum(a["amount"] for a in p.td_assets)
                        st.markdown("<div class='action-box-title'>🔓 Redeem TD</div>", unsafe_allow_html=True)
                        rd_key=f"redeem_{rk}"
                        st.number_input(f"Redeem (avail {_fmt(td_total)})",min_value=0.0,max_value=float(td_total),step=100.0,format="%.2f",key=rd_key,label_visibility="collapsed",placeholder="Amount ($)")
                        rd_amt=_gf(rd_key); net_td=0.0
                        if rd_amt>0:
                            pen_p=rd_amt*TD_PENALTY_RATE; net_td=rd_amt-pen_p
                            st.markdown(f"<div style='font-family:DM Mono,monospace;font-size:0.7rem;color:#64748B;'>Penalty <strong style='color:#F87171;'>{_fmt(pen_p)}</strong> · Net <strong style='color:#60A5FA;'>{_fmt(net_td)}</strong></div>", unsafe_allow_html=True)
                        elif td_total==0:
                            st.markdown("<div style='font-size:0.7rem;color:#475569;'>No TDs held</div>", unsafe_allow_html=True)

                    # ── Coverage tracker ──────────────────────────────────────
                    total_cov=repo_preview+sell_preview+net_td
                    gap_after=w-ca-total_cov
                    ok=gap_after<=0
                    result_cls="ok" if ok else "bad"
                    result_txt=f"✓ Ready  (surplus {_fmt(-gap_after)})" if ok else f"⚠ Still short  {_fmt(gap_after)}"
                    st.markdown(f"""
<div class='coverage-tracker'>
    <div class='coverage-row'><span class='label'>Repo</span><span class='val'>{_fmt(repo_preview)}</span></div>
    <div class='coverage-row'><span class='label'>Bond Sale</span><span class='val'>{_fmt(sell_preview)}</span></div>
    <div class='coverage-row'><span class='label'>TD Redemption</span><span class='val'>{_fmt(net_td)}</span></div>
    <div class='coverage-status'>
        <span class='target'>Target {_fmt(w)} · Cash {_fmt(ca)} · Raising {_fmt(total_cov)}</span>
        <span class='result {result_cls}'>{result_txt}</span>
    </div>
</div>""", unsafe_allow_html=True)

                    if st.button("⚡ Execute Coverage Actions", type="primary", key=f"exec_cov_{rk}"):
                        has_any=(rt!="(none)" and ra>0) or (sell_t!="(none)" and sell_q>0) or _gf(rd_key)>0
                        if not has_any:
                            st.warning("Fill in at least one action above.")
                        else:
                            p2=_load_portfolio(gn); process_maturities(p2,r,prices_all)
                            actions=[]; errors=[]
                            if rt!="(none)" and ra>0:
                                got,rid=execute_repo(p2,rt,ra,prices_all.get(rt,0),r,repo_pa)
                                if got>0: actions.append(("repo",{"ticker":rt,"got":round(got,2),"annual_rate":repo_pa}))
                                else: errors.append("Repo failed — check holdings.")
                            if _gf(rd_key)>0:
                                res=execute_redeem_td(p2,_gf(rd_key),r)
                                if res["principal"]>0: actions.append(("redeem_td",{"principal":round(res["principal"],2),"penalty":round(res["penalty"],2)}))
                                else: errors.append("TD redemption failed.")
                            if sell_t!="(none)" and sell_q>0:
                                res=execute_sale(p2,sell_t,sell_q,prices_all.get(sell_t,0))
                                if res["proceeds"]>0: actions.append(("sell",{"ticker":sell_t,"qty":round(res["qty"],2),"proceeds":round(res["proceeds"],2),"pnl_delta":round(res["pnl_delta"],2)}))
                                else: errors.append("Sale failed — check quantity.")
                            _save_portfolio(p2)
                            if actions:
                                st.session_state.logs.setdefault(gn,[]).append({"round":r+1,"withdrawal":w,"actions":actions})
                                for k in [ra_key,rd_key,sel_q_key,rt_key,sel_t_key]: st.session_state.pop(k,None)
                                st.success(f"Done — {len(actions)} action(s). New cash: {_fmt(p2.current_account)}")
                            for err in errors: st.error(err)
                            _safe_rerun()

                    # ── Portfolio management ──────────────────────────────────
                    st.markdown("")
                    st.markdown("<div class='section-header'>Portfolio Management</div>", unsafe_allow_html=True)
                    pm1,pm2=st.columns(2)

                    with pm1:
                        with st.expander("💰 Invest in Term Deposit"):
                            inv_key=f"invest_{rk}"
                            st.number_input(f"Amount (cash: {_fmt(p.current_account)})",
                                min_value=0.0,max_value=float(max(0.0,p.current_account)),
                                step=100.0,format="%.2f",key=inv_key)
                            inv_amt=_gf(inv_key)
                            if inv_amt>0:
                                st.caption(f"Rate {td_pa*100:.2f}% p.a. · Interest {_fmt(inv_amt*monthly_rate(td_pa))} · Matures Round {r+2}")
                            if st.button("Invest",key=f"do_invest_{rk}"):
                                if inv_amt<=0: st.warning("Enter an amount.")
                                else:
                                    p2=_load_portfolio(gn); process_maturities(p2,r,prices_all)
                                    ids=execute_invest_td(p2,inv_amt,r,td_pa); _save_portfolio(p2)
                                    if ids:
                                        st.session_state.logs.setdefault(gn,[]).append({"round":r+1,"withdrawal":w,"actions":[("invest_td",{"amount":round(inv_amt,2),"annual_rate":td_pa})]})
                                        st.success(f"Invested {_fmt(inv_amt)} @ {td_pa*100:.2f}% p.a."); _safe_rerun()
                                    else: st.error("Failed — check cash balance.")

                    with pm2:
                        with st.expander("📈 Buy Bonds"):
                            bt_key=f"buy_t_{rk}"; bq_key=f"buy_q_{rk}"
                            st.selectbox("Bond",["(none)"]+all_tickers,key=bt_key)
                            st.number_input("Quantity",min_value=0.0,step=1.0,format="%.2f",key=bq_key)
                            buy_t=st.session_state.get(bt_key,"(none)"); buy_q=_gf(bq_key)
                            if buy_t!="(none)" and buy_q>0 and buy_t in prices_all:
                                spec=p.securities.get(buy_t)
                                if spec:
                                    ask=spec.ask(prices_all[buy_t]); cost=buy_q*ask
                                    st.caption(f"Ask {_fmt(ask)} · Cost {_fmt(cost)}" + (" ⚠️ Insufficient" if cost>p.current_account else ""))
                            if st.button("Buy",key=f"do_buy_{rk}"):
                                if buy_t=="(none)" or buy_q<=0: st.warning("Select bond and quantity.")
                                else:
                                    p2=_load_portfolio(gn); process_maturities(p2,r,prices_all)
                                    res=execute_buy(p2,buy_t,buy_q,prices_all.get(buy_t,0)); _save_portfolio(p2)
                                    if res["cost"]>0:
                                        st.session_state.logs.setdefault(gn,[]).append({"round":r+1,"withdrawal":w,"actions":[("buy",{"ticker":buy_t,"qty":round(res["qty"],2),"cost":round(res["cost"],2)})]})
                                        st.success(f"Bought {res['qty']:,.2f} {buy_t} for {_fmt(res['cost'])}"); _safe_rerun()
                                    else: st.error("Failed — check cash.")

                else:
                    st.markdown("<div style='color:#475569;font-size:0.82rem;font-style:italic;padding:1rem 0;'>👁 Read-only — not your group</div>", unsafe_allow_html=True)

# ── HOST CONTROLS ─────────────────────────────────────────────────────────────
if role=="Host" and r<st.session_state.rounds:
    st.markdown(f"""
<div class='host-controls'>
    <div>
        <div style='font-family:Syne,sans-serif;font-weight:700;color:#F1F5F9;'>Host Controls</div>
        <div class='host-controls-label'>Advance to Round {r+2} when all groups are ready</div>
    </div>
""", unsafe_allow_html=True)
    if st.button(f"Advance → Round {r+2} ▶", type="primary"):
        all_raw=_load_all_portfolios()
        for p in st.session_state.portfolios:
            if p.name in all_raw:
                fresh=_p_from_dict(all_raw[p.name])
                p.current_account=fresh.current_account; p.pos_qty=fresh.pos_qty
                p.pnl_realized=fresh.pnl_realized; p.shortfall_total=fresh.shortfall_total
                p.penalty_total=fresh.penalty_total; p.repo_liabilities=fresh.repo_liabilities
                p.td_assets=fresh.td_assets; p.securities=fresh.securities
        for p in st.session_state.portfolios:
            wlist=st.session_state.withdrawals.get(p.name,[])
            w=float(wlist[r]) if r<len(wlist) else 0.0
            events=process_maturities(p,r,prices_all); result=apply_withdrawal(p,w)
            st.session_state.logs.setdefault(p.name,[]).append({"round":r+1,"withdrawal":w,"actions":[("withdrawal",result)],"maturity_events":events})
            _save_portfolio(p)
        new_round=r+1; st.session_state.current_round=new_round
        _json_mutate(SHARED_STATE_PATH,{},lambda s:{**s,"current_round":new_round,"ts":_now()})
        _safe_rerun()
    st.markdown("</div>", unsafe_allow_html=True)
elif role=="Player":
    st.markdown("<div style='text-align:center;color:#334155;font-size:0.78rem;padding:1rem 0;'>The host controls round advancement</div>", unsafe_allow_html=True)

# ── END GAME ──────────────────────────────────────────────────────────────────
if r>=st.session_state.rounds:
    last_ix=min(st.session_state.rounds-1,len(df)-1)
    _,final_px=_prices_for_round(last_ix)
    st.markdown("<div style='height:2rem;'></div>", unsafe_allow_html=True)
    st.markdown("""
<div style='text-align:center;margin-bottom:2rem;'>
    <div style='font-family:Syne,sans-serif;font-size:2rem;font-weight:800;color:#F1F5F9;letter-spacing:-0.03em;'>
        🏁 Final Results
    </div>
    <div style='color:#475569;font-size:0.9rem;margin-top:0.4rem;'>Ranked by Net Score = Total Reserve − Cumulative Penalties</div>
</div>""", unsafe_allow_html=True)

    if role=="Host":
        st.info("Tip: click **↻ Refresh** first to sync the latest player actions.")
        source_portfolios=st.session_state.portfolios
    else:
        all_raw=_load_all_portfolios(); source_portfolios=[_p_from_dict(d) for d in all_raw.values()]

    rows=[]
    for p in source_portfolios:
        s=p.summary(final_px)
        rows.append({"Group":p.name,"Total Reserve":s["total_mv"],"Cash":s["current_account"],
            "Securities":s["securities_mv"],"Term Deposits":s["td_invested"],
            "Repo Owed":s["repo_outstanding"],"PnL Realized":s["pnl_realized"],
            "Penalties":s["penalty_total"],"Net Score":s["net_score"]})

    if rows:
        rows.sort(key=lambda x:x["Net Score"],reverse=True)
        medals=["🥇","🥈","🥉"]+[f"#{i+4}" for i in range(len(rows))]
        podium_cols=st.columns(min(len(rows),4))
        for i,row in enumerate(rows[:4]):
            with podium_cols[i]:
                score_color="#FFD700" if i==0 else "#C0C0C0" if i==1 else "#CD7F32" if i==2 else "#60A5FA"
                st.markdown(f"""
<div class='scoreboard-card'>
    <div class='rank-medal'>{medals[i]}</div>
    <div class='score-name'>{row['Group']}</div>
    <div class='score-val' style='color:{score_color};'>{_fmt(row['Net Score'])}</div>
    <div style='font-family:DM Mono,monospace;font-size:0.7rem;color:#475569;margin-top:0.5rem;'>
        Reserve {_fmt(row['Total Reserve'])}<br>Penalties {_fmt(row['Penalties'])}
    </div>
</div>""", unsafe_allow_html=True)

        st.markdown("")
        sb_raw=pd.DataFrame(rows); sb_fmt=sb_raw.copy()
        for col in ["Total Reserve","Cash","Securities","Term Deposits","Repo Owed","PnL Realized","Penalties","Net Score"]:
            if col in sb_fmt.columns: sb_fmt[col]=sb_fmt[col].apply(_fmt)
        sb_fmt.insert(0,"Rank",medals[:len(rows)])
        col_order=["Rank","Group","Net Score","Total Reserve","Cash","Securities","Term Deposits","Repo Owed","PnL Realized","Penalties"]
        st.dataframe(sb_fmt[[c for c in col_order if c in sb_fmt.columns]],use_container_width=True,hide_index=True)

        if role=="Host":
            dc1,dc2=st.columns(2)
            dc1.download_button("⬇ Scoreboard CSV",sb_raw.to_csv(index=False).encode(),file_name="scoreboard.csv",mime="text/csv")
            dc2.download_button("⬇ Logs JSON",json.dumps(st.session_state.logs,indent=2).encode(),file_name="logs.json",mime="application/json")
        else:
            shared=_json_read(SHARED_STATE_PATH,{})
            my_groups=[g for g,o in shared.get("claims",{}).items() if o==st.session_state.player_name.strip()]
            if my_groups: st.success(f"You played as: **{', '.join(my_groups)}**")
    st.stop()
