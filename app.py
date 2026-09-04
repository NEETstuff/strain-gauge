"""Strain Gauge — Lorca Labs local liquidity-plumbing dashboard."""
import os
import re
from pathlib import Path

import streamlit as st
from src.fetch import fetch_live_or_demo, load_demo
from src.stablecoins import get_stablecoins
from src.gauges import COPY, WORD, carry_status, dollar_status, liquidity_status, system_line
from src.charts import spark

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
    """Strip anything resembling a 32-char hex key. Never display secrets."""
    return re.sub(r"\b[a-fA-F0-9]{32}\b", "[redacted]", str(msg))


try:
    _KEY = _load_key()
    _KEY_LEN = len(_KEY)
    result = fetch_live_or_demo()
except Exception as e:  # page must always paint: fall back to demo gauges
    _KEY_LEN = len(os.getenv("FRED_API_KEY", "").strip())
    st.error(f"Load failed ({type(e).__name__}): {_scrub(e)} — showing demo fixtures.")
    _d = load_demo()
    result = {"mode": "DEMO", "data": _d, "updated": _d["meta"]["as_of"] + " (demo)",
              "error": f"Load failed ({type(e).__name__}); demo fallback.",
              "series_status": {}, "partial": {}, "checked_at": None, "env": None,
              "probe_status": None}
COLOR = {"green": "#22c55e", "yellow": "#eab308", "red": "#ef4444"}

mode, data, updated = result["mode"], result["data"], result["updated"]
partial = result.get("partial", {})
badge = "🟢 LIVE" if mode == "LIVE" else "🟡 DEMO"

# Sidebar: one badge only, key_len cannot lie (no key, no abs paths)
st.sidebar.markdown(f"## {badge}")
st.sidebar.markdown(f"key_len: {_KEY_LEN}")
if result.get("env"):
    st.sidebar.markdown(result["env"])
if result.get("checked_at"):
    st.sidebar.markdown(f"Last successful fetch: {result['checked_at']}")
else:
    st.sidebar.markdown(f"Last update: {updated}")
if result.get("error"):
    st.sidebar.warning(result["error"])
ss = result.get("series_status", {})
if ss:
    st.sidebar.markdown("### Series")
    for label, r in ss.items():
        mark = "✅" if r["ok"] else "❌"
        date = r["dates"][-1] if r["ok"] and r["dates"] else "—"
        id_note = "" if r["id"] == label else f" ({r['id']})"
        st.sidebar.markdown(f"{mark} {label}{id_note} · {date} · {r['lag']}")
    jp = result.get("jp10y")
    if jp:
        mark = "✅" if jp["ok"] else "❌"
        date = jp["dates"][-1] if jp["ok"] and jp["dates"] else "—"
        st.sidebar.markdown(f"{mark} JP 10y ({jp['id']}) · {date} · {jp['lag']}")

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
car_s, _car = guarded("carry", carry_status, data)
net = data.get("liquidity", {}).get("walcl", 0) or 0
net -= (data.get("liquidity", {}).get("tga", 0) or 0) + (data.get("liquidity", {}).get("onrrp", 0) or 0)
spread = ((data.get("dollar", {}).get("sofr") or 0) - (data.get("dollar", {}).get("iorb") or 0)) * 100

ok_statuses = [s for s in (liq_s, dol_s, car_s) if s]
st.subheader(system_line(ok_statuses) if ok_statuses else "System: data partial — live series missing.")
st.caption("Plumbing pulse. Not a trade signal.")
st.markdown(f"**{badge}** · Updated: {updated}")


def card(title, status, line, number, is_partial=False):
    label = "PARTIAL" if is_partial else WORD.get(status, "—")
    pip = "#9ca3af" if is_partial else COLOR.get(status, "#9ca3af")
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
    return base


c1, c2, c3 = st.columns(3)
with c1:
    p = partial.get("liquidity", False) or liq_s is None
    base = COPY["liquidity"][liq_s] if liq_s else "Liquidity data unavailable."
    card("Liquidity Health", liq_s or "green", line_for("liquidity", liq_s, base),
         f"Net liq ${net:,.0f}B" if not p else "n/a (partial)", p)
with c2:
    p = partial.get("dollar", False) or dol_s is None
    base = COPY["dollar"][dol_s] if dol_s else "Dollar funding data unavailable."
    iorb_id = data.get("dollar", {}).get("iorb_id", "IORB")
    card("Dollar Stress", dol_s or "green", line_for("dollar", dol_s, base),
         f"SOFR–{iorb_id} {spread:.0f}bp · Swaps ${(data.get('dollar', {}).get('swpt') or 0):.2f}B"
         if not p else "n/a (partial)", p)
with c3:
    p = partial.get("carry", False) or car_s is None
    base = COPY["carry"][car_s] if car_s else "Carry data unavailable."
    uj = data.get("carry", {}).get("usd_jpy")
    j10 = data.get("carry", {}).get("jgb10y")
    card("Carry Risk", car_s or "green", line_for("carry", car_s, base),
         f"USD/JPY {uj:.1f} · JGB10y {j10:.2f}%" if (not p and uj and j10) else "n/a (partial)", p)

s1, s2, s3 = st.columns(3)
with s1:
    if data.get("series", {}).get("net_liquidity"):
        st.plotly_chart(spark(data["series"]["net_liquidity"], "Net liquidity"), use_container_width=True)
with s2:
    if data.get("series", {}).get("sofr_iorb_bp"):
        st.plotly_chart(spark(data["series"]["sofr_iorb_bp"], "SOFR–IORB (bp)"), use_container_width=True)
with s3:
    if data.get("series", {}).get("usd_jpy"):
        st.plotly_chart(spark(data["series"]["usd_jpy"], "USD/JPY"), use_container_width=True)

st.info(data.get("fima_note", "FIMA: dormant / elevated / drawing — update from H.4.1 Thursday."))

# On-chain dollars (context card; not a gauge; never feeds gauge status)
try:
    sc = get_stablecoins()
except Exception as e:
    st.error(f"Stablecoins failed ({type(e).__name__}): {_scrub(e)}")
    sc = {"ok": False, "stale": True, "note": "feed error · data/cache/stablecoins_latest.json"}
_sc_note = sc["note"].replace(str(Path(__file__).resolve().parent) + "/", "")
st.sidebar.markdown(f"Stablecoins: {_sc_note}")
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

with st.expander("For operators"):
    st.table([{"series": k, "fred_id": v["id"],
               "last_date": v["dates"][-1] if v["ok"] and v["dates"] else "—",
               "latest": v["vals"][-1] if v["ok"] and v["vals"] else "missing",
               "lag": v["lag"], "status": "ok" if v["ok"] else "missing"}
              for k, v in ss.items()] if ss else [{"note": "DEMO mode — fixtures in data/demo.json"}])

st.caption("Lorca Labs — sovereign monitor. Data can be late. Thresholds are starting points, not gospel.")
st.caption("This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.")
