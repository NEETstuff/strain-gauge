"""Strain Gauge — Lorca Labs local liquidity-plumbing dashboard."""
import contextlib as _contextlib
import os
import re
from pathlib import Path

_nullcontext = _contextlib.nullcontext

import streamlit as st
from src.fetch import fetch_live_or_demo, load_demo
from src.stablecoins import get_stablecoins
from src.treasury import get_tga_daily
from src.nyfed import get_nyfed_rates
from src.fx import get_usdjpy_daily
from src.auctions import get_auctions
from src.dealers import get_dealers
from src.comex import get_comex_gold
from src.xrpl import get_xrpl
from src.calendar import PRINTS
from src.gauges import COPY, WORD, carry_status, dollar_status, liquidity_status, system_line, is_stale
from src.charts import spark
from src.units import fmt_T, fmt_B, fmt_dB, to_T

st.set_page_config(page_title="Strain Gauge", layout="wide")

st.title("Strain Gauge")
st.sidebar.markdown("Loading…")


def _load_key():
    """Resolve .env next to this file only; normalize export/quotes/BOM/CRLF. Never log value."""
    p = Path(__file__).resolve().parent / ".env"
    try:
        from dotenv import load_dotenv
        if p.is_file():
            load_dotenv(dotenv_path=p, override=True)
    except ImportError:
        pass
    if p.is_file():
        try:
            for ln in p.read_bytes().decode("utf-8-sig").splitlines():
                s = ln.strip()
                if s.startswith("export "):
                    s = s[len("export "):].strip()
                if s.startswith("FRED_API_KEY") and "=" in s:
                    v = s.split("=", 1)[1].strip().strip('"').strip("'").strip()
                    if v:
                        os.environ["FRED_API_KEY"] = v
                    break
        except Exception:
            pass
    return os.getenv("FRED_API_KEY", "").strip()


def _scrub(msg):
    """Strip keys and local paths. Never display secrets or lab details."""
    s = re.sub(r"\b[a-fA-F0-9]{32}\b", "[redacted]", str(msg))
    s = re.sub(r"/Users/\S+", "[redacted-path]", s)
    s = re.sub(r"[A-Za-z]:\\[^\s]*", "[redacted-path]", s)
    return s


def _is_public():
    """Public when forced, on Streamlit sharing, or serving a non-local host."""
    v = os.getenv("STRAIN_GAUGE_PUBLIC", "").strip().lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    if os.getenv("STREAMLIT_SHARING"):
        return True
    try:
        host = (st.context.headers.get("Host", "") or "").split(":")[0].strip().lower()
        if host and host not in ("localhost", "127.0.0.1", "::1"):
            return True
    except Exception:
        pass
    return False


try:
    _KEY = _load_key()
    _KEY_LEN = len(_KEY)
    result = fetch_live_or_demo()
except Exception as e:  # page must always paint: fall back to demo gauges
    _KEY_LEN = len(os.getenv("FRED_API_KEY", "").strip())
    _boom = f"Load failed ({type(e).__name__}): {_scrub(e)} — showing demo fixtures."
    _d = load_demo()
    result = {"mode": "DEMO", "data": _d, "updated": _d["meta"]["as_of"] + " (demo)",
              "error": f"Load failed ({type(e).__name__}); demo fallback.",
              "series_status": {}, "partial": {}, "checked_at": None, "env": None,
              "probe_status": None}
else:
    _boom = None

PUBLIC = _is_public()
if PUBLIC:
    st.markdown("<style>footer {visibility: hidden;}</style>", unsafe_allow_html=True)
if _boom and not PUBLIC:
    st.error(_boom)
elif _boom:
    st.error("Feed delayed.")
COLOR = {"green": "#22c55e", "yellow": "#eab308", "red": "#ef4444"}

mode, data, updated = result["mode"], result["data"], result["updated"]
partial = result.get("partial", {})
badge = "🟢 LIVE" if mode == "LIVE" else "🟡 DEMO"

def _err(detail):
    st.error("Feed delayed." if PUBLIC else detail)


def _slab(*a, **kw):
    if not PUBLIC:
        st.sidebar.markdown(*a, **kw)


def _swarn(*a, **kw):
    if not PUBLIC:
        st.sidebar.warning(*a, **kw)


# Sidebar: public sees LIVE/DEMO + last update only; lab sees internals.
st.sidebar.markdown(f"## {badge}")
if not PUBLIC:
    _slab(f"key_len: {_KEY_LEN}")
if result.get("env") and not PUBLIC:
    _slab(result["env"])
if result.get("checked_at"):
    st.sidebar.markdown(f"Last successful fetch: {result['checked_at']}")
else:
    st.sidebar.markdown(f"Last update: {updated}")
if result.get("error") and not PUBLIC:
    _swarn(_scrub(result["error"]))
ss = result.get("series_status", {})
if ss and not PUBLIC:
    _slab("### Series")
    for label, r in ss.items():
        mark = "✅" if r["ok"] else "❌"
        date = r["dates"][-1] if r["ok"] and r["dates"] else "—"
        id_note = "" if r["id"] == label else f" ({r['id']})"
        _slab(f"{mark} {label}{id_note} · {date} · {r['lag']}")

# Gauge computation; partial gauges never use demo numbers
def guarded(which, fn, d):
    if partial.get(which):
        return None, None
    try:
        return fn(d)[0], fn(d)
    except (TypeError, KeyError):
        return None, None

liq_s, _liq = guarded("liquidity", liquidity_status, data)
dol_s, _dol = guarded("dollar", dollar_status, data)
spread = ((data.get("dollar", {}).get("sofr") or 0) - (data.get("dollar", {}).get("iorb") or 0)) * 100
net = data.get("liquidity", {}).get("walcl", 0) or 0
net -= (data.get("liquidity", {}).get("tga", 0) or 0) + (data.get("liquidity", {}).get("onrrp", 0) or 0)
slope_4w = _liq[2] if _liq else None
spread = ((data.get("dollar", {}).get("sofr") or 0) - (data.get("dollar", {}).get("iorb") or 0)) * 100

# Stale flags: daily >3d, weekly >10d (lags in data["lag"]). LIVE only; a stale
# series alone never promotes a card to STRAIN (red capped at yellow).
CARD_SERIES = {"liquidity": ["WALCL", "TGA", "ON RRP"], "dollar": ["SOFR", "IORB", "SWPT"],
               "carry": ["USD/JPY"]}  # carry freshness owned by the daily FX pipe below
today = (result.get("checked_at") or "")[:10]
asof, lags = data.get("asof", {}), data.get("lag", {})
stale = {}
for _card, _labels in CARD_SERIES.items():
    _ages = [(lb, asof.get(lb), lags.get(lb, "daily")) for lb in _labels]
    stale[_card] = any(asof.get(lb) and is_stale(asof.get(lb), lags.get(lb, "daily"), today)
                       for lb in _labels) if today and mode == "LIVE" else False
if stale.get("liquidity") and liq_s == "red":
    liq_s, _capped_liq = "yellow", True
else:
    _capped_liq = False
if stale.get("dollar") and dol_s == "red":
    dol_s, _capped_dol = "yellow", True
else:
    _capped_dol = False
_capped_car = False  # carry capped in the FX-pipe block below, after recompute


def _md(datestr):
    """YYYY-MM-DD → 'Aug 28'. Raw string back if unparseable."""
    try:
        from datetime import date as _date
        y, m, d = map(int, datestr.split("-"))
        return _date(y, m, d).strftime("%b %-d")
    except Exception:
        return datestr or "—"


# Daily context pipes (fail independently; never feed gauges or thresholds).
try:
    tga_d = get_tga_daily()
except Exception as e:
    _err(f"TGA daily failed ({type(e).__name__}): {_scrub(e)}")
    tga_d = {"ok": False, "stale": True, "date": None, "tga_bn": None,
             "note": "feed error · data/cache/tga_daily.json"}
try:
    nyf = get_nyfed_rates()
except Exception as e:
    _err(f"NY Fed failed ({type(e).__name__}): {_scrub(e)}")
    nyf = {"ok": False, "stale": True, "date": None, "sofr": None,
           "note": "feed error · data/cache/nyfed_rates.json"}

if tga_d.get("ok"):
    _tag = " · STALE" if tga_d["stale"] else ""
    _w = asof.get("TGA")
    try:
        from datetime import date as _date
        _gap = (_date(*map(int, tga_d["date"].split("-"))) - _date(*map(int, _w.split("-")))).days \
            if (tga_d.get("date") and _w) else "?"
        _gap_s = f"{_gap:+d}d vs weekly"
    except Exception:
        _gap_s = "gap n/a"
    _slab(
        f"TGA daily · {tga_d['date']} · {fmt_B(tga_d['tga_bn'], 1)}{_tag} (weekly {_w or '—'}, {_gap_s})")
else:
    _slab(f"TGA daily: {tga_d['note']}")
if nyf.get("ok"):
    _tag = " · STALE" if nyf["stale"] else ""
    _slab(f"NY Fed · {nyf['date']} · SOFR {nyf['sofr']:.2f}%{_tag}")
else:
    _slab(f"NY Fed: {nyf['note']}")

# Dollar card as-of: NY Fed wins only when strictly newer than FRED SOFR.
_fred_sofr_d = asof.get("SOFR")
if nyf.get("ok") and nyf.get("date") and _fred_sofr_d and nyf["date"] > _fred_sofr_d:
    _dol_asof = f"NY Fed {_md(nyf['date'])}"
else:
    _dol_asof = f"FRED {_md(_fred_sofr_d)}" if _fred_sofr_d else "date n/a"

# Daily USD/JPY: FRED DEXJPUS preferred if ≤3d, else keyless public close.
try:
    _fxx = ss.get("USD/JPY", {})
    _fx_fred_d = (_fxx.get("dates") or [None])[-1]
    _fx_fred_v = (_fxx.get("vals") or [None])[-1]
    fx = get_usdjpy_daily(_fx_fred_d, _fx_fred_v)
except Exception as e:
    _err(f"USD/JPY failed ({type(e).__name__}): {_scrub(e)}")
    fx = {"ok": False, "stale": True, "date": None, "val": None, "val_3d_ago": None,
          "source": "none", "note": "feed error · data/cache/usdjpy_daily.json"}
if fx.get("ok"):
    data["carry"]["usd_jpy"] = fx["val"]
    data["carry"]["usd_jpy_3d_ago"] = fx["val_3d_ago"] or fx["val"]
    data["series"]["usd_jpy"] = [c["val"] for c in fx.get("closes", [])[-7:]] or \
        data["series"].get("usd_jpy", [])
car_s, _car = guarded("carry", carry_status, data)
if fx.get("ok"):
    stale["carry"] = bool(fx["stale"] or is_stale(fx["date"], "daily", today))
    if stale["carry"] and car_s == "red":
        car_s, _capped_car = "yellow", True
_slab(f"USD/JPY · {fx.get('date') or '—'} · {fx.get('source', 'none')}")
_slab("JGB10y · n/a · no live FRED series")

ok_statuses = [s for s in (liq_s, dol_s, car_s) if s]
st.subheader(system_line(ok_statuses) if ok_statuses else "System: data partial — live series missing.")
st.caption("Plumbing pulse. Not a trade signal.")
st.markdown(f"**{badge}** · Updated: {updated}")


def card(title, status, line, number, is_partial=False, is_stale=False):
    label = "PARTIAL" if is_partial else WORD.get(status, "—")
    if is_stale and not is_partial:
        label += " · STALE"
    pip = "#9ca3af" if (is_partial or is_stale) else COLOR.get(status, "#9ca3af")
    st.markdown(
        f"<div style='border:1px solid #333;border-radius:10px;padding:12px'>"
        f"<span style='color:{pip};font-size:22px'>●</span> "
        f"<b>{title}</b> — {label}<br>{line}<br>"
        f"<code>{number}</code></div>",
        unsafe_allow_html=True,
    )


def line_for(which, status, base):
    if partial.get(which):
        return base + " (partial — live series stale or missing, not replaced with demo.)"
    _capped = {"liquidity": _capped_liq, "dollar": _capped_dol, "carry": _capped_car}.get(which)
    if _capped:
        return base + " (inputs stale — capped at TIGHTENING, not STRAIN.)"
    return base


c1, c2, c3 = st.columns(3)
with c1:
    p = partial.get("liquidity", False) or liq_s is None
    base = COPY["liquidity"][liq_s] if liq_s else "Liquidity data unavailable."
    card("Liquidity Health", liq_s or "green", line_for("liquidity", liq_s, base),
         f"Net liq {fmt_T(net)} · {fmt_dB(slope_4w)}" if not p else "n/a (partial)", p,
         stale.get("liquidity", False))
with c2:
    p = partial.get("dollar", False) or dol_s is None
    base = COPY["dollar"][dol_s] if dol_s else "Dollar funding data unavailable."
    iorb_id = data.get("dollar", {}).get("iorb_id", "IORB")
    card("Dollar Stress", dol_s or "green", line_for("dollar", dol_s, base),
         f"SOFR–{iorb_id} {spread:.0f}bp · Swaps {fmt_B(data.get('dollar', {}).get('swpt'))}"
         f" · as of {_dol_asof}"
         if not p else "n/a (partial)", p, stale.get("dollar", False))
with c3:
    p = partial.get("carry", False) or car_s is None
    base = COPY["carry"][car_s] if car_s else "Carry data unavailable."
    uj = data.get("carry", {}).get("usd_jpy")
    u2 = data.get("carry", {}).get("us2y")
    u2_d = _md(asof.get("US 2y")) if asof.get("US 2y") else "—"
    card("Carry Risk", car_s or "green", line_for("carry", car_s, base),
         f"USD/JPY {uj:.1f} ({_md(fx.get('date'))}, {fx.get('source')}) · "
         f"US2y {u2:.2f}% ({u2_d}) · JGB10y n/a · no live FRED series"
         if (not p and uj and u2) else "n/a (partial)", p, stale.get("carry", False))

s1, s2, s3 = st.columns(3)
with s1:
    if data.get("series", {}).get("net_liquidity"):
        st.plotly_chart(spark(to_T(data["series"]["net_liquidity"]), "Net liquidity ($T)"),
                        use_container_width=True)
with s2:
    if data.get("series", {}).get("sofr_iorb_bp"):
        st.plotly_chart(spark(data["series"]["sofr_iorb_bp"], "SOFR–IORB (bp)"), use_container_width=True)
with s3:
    if data.get("series", {}).get("usd_jpy"):
        st.plotly_chart(spark(data["series"]["usd_jpy"], "USD/JPY"), use_container_width=True)

if "fima_state" not in st.session_state:
    st.session_state["fima_state"] = "dormant"
st.info(f"FIMA: manual — set after H.4.1 Thursday · current: {st.session_state['fima_state']}")

# Thursday ritual (context only — SWPT stays the live swap print, no new gauge).
_slab("### Thursday ritual")
_sw, _sw_d = data.get("dollar", {}).get("swpt"), asof.get("SWPT")
_slab(f"Swaps (SWPT) · {_sw_d or '—'} · {fmt_B(_sw) if _sw is not None else 'n/a'}")
fima = st.session_state["fima_state"] if PUBLIC else st.sidebar.selectbox(
    "FIMA", ["dormant", "elevated", "drawing"], key="fima_state")
_h41 = result.get("h41_date")
_H41_URL = "https://www.federalreserve.gov/releases/h41/current/default.htm"
if _h41:
    _slab(f"H.4.1 · {_h41} · [open the release]({_H41_URL})")
else:
    _slab(f"H.4.1 · open the release · [link]({_H41_URL})")
_rsv = ss.get("WRESBAL", {})
_rsv_bn = (_rsv.get("vals") or [None])[-1]
_rsv_bn = _rsv_bn / 1000.0 if _rsv_bn is not None else None  # FRED $M → $B
_slab(f"Reserves · {asof.get('WRESBAL') or '—'} · {fmt_T(_rsv_bn)}")

# Auction + dealer context (fail independently; never feed gauges).
try:
    auc = get_auctions()
except Exception as e:
    _err(f"Auctions failed ({type(e).__name__}): {_scrub(e)}")
    auc = {"ok": False, "stale": True,
           "line": "Auctions: no parseable feed — check TreasuryDirect.",
           "note": "feed error · data/cache/auctions.json"}
try:
    dlr = get_dealers()
except Exception as e:
    _err(f"Dealers failed ({type(e).__name__}): {_scrub(e)}")
    dlr = {"ok": False, "mapped": False, "note": "feed error · data/cache/dealers.json"}
_tag = " · STALE" if auc.get("stale") else ""
st.markdown(f"<div style='border:1px solid #333;border-radius:10px;padding:12px'>"
            f"<b>Auction prints</b>{_tag}<br>{auc['line']}</div>",
            unsafe_allow_html=True)
if dlr.get("ok") and dlr.get("mapped"):
    _tag = " · STALE" if dlr.get("stale") else ""
    _slab(f"Dealers · {dlr.get('asof', '—')}{_tag} · {dlr['note']}")
else:
    _slab("Dealers: feed not mapped")

# COMEX + XRPL context (fail independently; never feed gauges).
try:
    cmx = get_comex_gold()
except Exception as e:
    _err(f"COMEX failed ({type(e).__name__}): {_scrub(e)}")
    cmx = {"ok": False, "mapped": False, "line": "COMEX: feed not mapped",
           "note": "feed error · data/cache/comex_gold.json"}
try:
    xrp = get_xrpl()
except Exception as e:
    _err(f"XRPL failed ({type(e).__name__}): {_scrub(e)}")
    xrp = {"ok": False, "stale": True, "seq": None,
           "rlusd_note": "RLUSD: not on this server view",
           "note": "feed error · data/cache/xrpl.json"}
_tag = " · STALE" if cmx.get("stale") else ""
st.markdown(f"<div style='border:1px solid #333;border-radius:10px;padding:12px'>"
            f"<b>Gold vault</b>{_tag}<br>{cmx['line']}</div>",
            unsafe_allow_html=True)
if xrp.get("ok"):
    _tag = " · STALE" if xrp.get("stale") else ""
    _rl = f" · RLUSD issued ${xrp['rlusd'] / 1e9:.2f}B" if xrp.get("rlusd") \
        else f" · {xrp.get('rlusd_note', 'RLUSD: not on this server view')}"
    _slab(f"XRPL · res {xrp['reserve_xrp']} · fee {xrp['fee_xrp']}{_rl} · "
                        f"ledger {xrp['seq']} ({xrp['close_time']}){_tag}")
    _slab(f"RLUSD ETH contract: {xrp.get('rlusd_eth', 'not mapped')}")
else:
    _slab(f"XRPL: {xrp['note']} · {xrp['rlusd_note']}")

with st.expander("Next prints"):
    st.table([{"date": d, "event": e} for d, e in PRINTS])

# On-chain dollars (context card; not a gauge; never feeds gauge status)
try:
    sc = get_stablecoins()
except Exception as e:
    _err(f"Stablecoins failed ({type(e).__name__}): {_scrub(e)}")
    sc = {"ok": False, "stale": True, "note": "feed error · data/cache/stablecoins_latest.json"}
_sc_note = sc["note"].replace(str(Path(__file__).resolve().parent) + "/", "")
_slab(f"Stablecoins: {_sc_note}")
if sc.get("ok"):
    tag = " · STALE" if sc["stale"] else ""
    chg = f"{sc['chg7']:+.1f}% 7d" if sc["chg7"] is not None else "7d n/a"
    st.markdown(
        f"<div style='border:1px solid #333;border-radius:10px;padding:12px'>"
        f"<b>On-chain dollars</b>{tag}<br>{sc['line']}<br>"
        f"<code>${sc['total_mcap']:,.0f} · {chg}</code></div>",
        unsafe_allow_html=True,
    )
    with st.expander("Stablecoin breakdown"):
        rows = [{"token": s, "mcap": sc["assets"][s]["mcap"]} for s in ("USDT", "USDC", "DAI") if s in sc["assets"]]
        if "RLUSD" in sc["assets"]:
            rows.append({"token": "RLUSD", "mcap": sc["assets"]["RLUSD"]["mcap"]})
        else:
            rows.append({"token": "RLUSD: not in DefiLlama feed", "mcap": "—"})
        rows.append({"token": "Other", "mcap": sc["other_mcap"]})
        st.table(rows)
else:
    st.markdown("<div style='border:1px solid #333;border-radius:10px;padding:12px'>"
                "<b>On-chain dollars</b> · STALE<br>Stablecoin feed unavailable.</div>",
                unsafe_allow_html=True)

with st.expander("For operators") if not PUBLIC else _nullcontext():
    _units = {"WALCL": "$B", "TGA": "$B", "ON RRP": "$B", "SOFR": "%", "EFFR": "%",
              "IORB": "%", "USD/JPY": "level", "US 2y": "%", "US 10y": "%",
              "SWPT": "$B", "OBFRVOL": "$B", "WRESBAL": "$B"}
    _mln = {"WALCL", "TGA", "ON RRP", "SWPT", "WRESBAL"}  # FRED prints $M → show $B

    def _latest(k, v):
        if not (v["ok"] and v["vals"]):
            return "missing"
        x = v["vals"][-1]
        return x / 1000.0 if k in _mln else x

    _rows = [{"series": k, "fred_id": v["id"],
              "last_date": v["dates"][-1] if v["ok"] and v["dates"] else "—",
              "latest": _latest(k, v),
              "unit": _units.get(k, "—"), "lag": v["lag"],
              "status": "ok" if v["ok"] else "missing"}
             for k, v in ss.items()] if ss else [{"note": "DEMO mode — fixtures in data/demo.json"}]
    _rows.append({"series": "JGB 10y", "fred_id": "none — no live FRED series",
                  "last_date": "n/a", "latest": "n/a (IRLTLT01JPM156N ends 2026-06-01)",
                  "unit": "%", "lag": "monthly (lagged)", "status": "missing"})
    if fx.get("ok"):
        _rows.append({"series": "USD/JPY daily", "fred_id": fx["source"],
                      "last_date": fx["date"] or "—", "latest": fx["val"],
                      "unit": "level", "lag": "daily (context)",
                      "status": "STALE" if fx["stale"] else "ok"})
    if tga_d.get("ok"):
        _rows.append({"series": "TGA daily", "fred_id": "DTS operating_cash_balance",
                      "last_date": tga_d["date"] or "—", "latest": tga_d["tga_bn"],
                      "unit": "$B", "lag": "daily (context)",
                      "status": "STALE" if tga_d["stale"] else "ok"})
    if nyf.get("ok"):
        for _k, _unit in (("sofr", "%"), ("effr", "%"), ("obfr", "%")):
            _rows.append({"series": f"NY Fed {_k.upper()}", "fred_id": "NY Fed markets API",
                          "last_date": nyf["date"] or "—", "latest": nyf.get(_k),
                          "unit": _unit, "lag": "daily (context)",
                          "status": "STALE" if nyf["stale"] else "ok"})
    if auc.get("ok"):
        _rows.append({"series": "Auction prints", "fred_id": "TreasuryDirect TA_WS",
                      "last_date": (auc.get("bill") or {}).get("date") or "—",
                      "latest": auc["line"][:80], "unit": "context", "lag": "daily (context)",
                      "status": "STALE" if auc["stale"] else "ok"})
    _rows.append({"series": "COMEX gold", "fred_id": "CME (blocked)" if not cmx.get("mapped") else "CME",
                  "last_date": cmx.get("date", "—") or "—", "latest": cmx["line"][:80],
                  "unit": "context", "lag": "daily (context)",
                  "status": "STALE" if cmx.get("stale") else ("ok" if cmx.get("ok") else "unmapped")})
    if xrp.get("ok"):
        _rows.append({"series": "XRPL ledger", "fred_id": "XRPL JSON-RPC",
                      "last_date": xrp.get("close_time") or "—", "latest": xrp["seq"],
                      "unit": "ledger", "lag": "realtime (context)",
                      "status": "STALE" if xrp["stale"] else "ok"})
    if not PUBLIC:
        st.table(_rows)

st.caption("Lorca Labs — sovereign monitor. Data can be late. Thresholds are starting points, not gospel.")
st.caption("This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.")
