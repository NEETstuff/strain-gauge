"""Thresholds → status + plain-English copy. Single config dict."""

THRESHOLDS = {
    "sofr_iorb_bp": {"green_max": 5, "yellow_max": 15},  # bp; red above yellow_max
    "swpt_yellow_bn": 1.0,       # $B
    "swpt_red_bn": 10.0,
    "liq_strain_slope_4w": -150.0,  # $B drained over 4 weeks = fast drain → STRAIN
    "liq_new_low_margin": 25.0,     # $B below recent-range low = scarce → STRAIN
    "usd_jpy_yellow": 158.0,
    "yen_rally_3d_pct": 2.0,     # >2% 3-day yen rally (USDJPY fall) = red
    "usdjpy_stretch": 157.0,     # with US 2y high = stretched carry → yellow
    "us2y_high": 4.5,            # %; corroborates stretched carry, never STRAIN alone
}

# As-of older than this → STALE; a stale series alone never promotes to STRAIN.
STALE_DAYS = {"daily": 3, "weekly": 10, "monthly (lagged)": 45}


def age_days(datestr, today):
    """Calendar-day age of a YYYY-MM-DD as-of vs today (YYYY-MM-DD). None if unknown."""
    try:
        y1, m1, d1 = map(int, datestr.split("-"))
        y2, m2, d2 = map(int, today.split("-"))
        from datetime import date as _date
        return (_date(y2, m2, d2) - _date(y1, m1, d1)).days
    except Exception:
        return None


def is_stale(datestr, lag, today):
    age = age_days(datestr, today)
    if age is None:
        return False
    return age > STALE_DAYS.get(lag, 10)

COPY = {
    "liquidity": {
        "green": "Cash in the system is steady.",
        "yellow": "The Treasury and the Fed are pulling cash out of the pipes.",
        "red": "Reserves are getting tight. Watch auctions and bill supply.",
    },
    "dollar": {
        "green": "Foreign banks can still borrow dollars at a normal price.",
        "yellow": "Offshore dollars are getting more expensive.",
        "red": "The eurodollar system is straining. Official backstops may get tapped.",
    },
    "carry": {
        "green": "Yen funding the world is still cheap.",
        "yellow": "The yen carry is getting expensive. Unwind risk is rising.",
        "red": "Carry trade under load. Fast yen strength can force selling elsewhere.",
    },
}

WORD = {"green": "CALM", "yellow": "TIGHTENING", "red": "STRAIN"}


def _asof(vals, dates, target):
    """Latest value on/before target date (YYYY-MM-DD). Falls back to oldest."""
    for v, dt in zip(reversed(vals), reversed(dates)):
        if dt <= target:
            return v
    return vals[0]


def liquidity_status(d):
    """Level + 4-week slope, all in $B. STRAIN only on fast drain or scarcity."""
    from datetime import date as _date
    liq = d["liquidity"]
    net = liq["walcl"] - liq["tga"] - liq["onrrp"]
    hist = d.get("hist") or {}
    if hist:
        w = hist["WALCL"]
        y, m, dd = map(int, w["dates"][-1].split("-"))
        cutoff = _date(y, m, dd).toordinal() - 28
        window = []
        for i, wdate in enumerate(w["dates"]):
            wy, wm, wd = map(int, wdate.split("-"))
            if _date(wy, wm, wd).toordinal() < cutoff:
                continue
            t = _asof(hist["TGA"]["vals"], hist["TGA"]["dates"], wdate)
            r = _asof(hist["ON RRP"]["vals"], hist["ON RRP"]["dates"], wdate)
            window.append(w["vals"][i] - t - r)
        slope_4w = window[-1] - window[0] if len(window) >= 2 else 0.0
        recent_low = min(window) if window else net
    else:  # demo fixtures: single step only
        prev = liq["walcl_prev"] - liq["tga_prev"] - liq["onrrp"]
        slope_4w = net - prev
        recent_low = min(net, prev)
    if slope_4w <= THRESHOLDS["liq_strain_slope_4w"] or \
            net < recent_low - THRESHOLDS["liq_new_low_margin"]:
        return "red", net, slope_4w
    if slope_4w < 0:
        return "yellow", net, slope_4w
    return "green", net, slope_4w


def dollar_status(d):
    """Print rule only: spread <5bp & SWPT <$1B CALM; 5–15bp or $1–10B TIGHTENING; else STRAIN."""
    dol = d["dollar"]
    spread_bp = (dol["sofr"] - dol["iorb"]) * 100
    swpt = dol["swpt"]  # $B
    if spread_bp > THRESHOLDS["sofr_iorb_bp"]["yellow_max"] or swpt > THRESHOLDS["swpt_red_bn"]:
        return "red", spread_bp
    if spread_bp >= THRESHOLDS["sofr_iorb_bp"]["green_max"] or swpt > THRESHOLDS["swpt_yellow_bn"]:
        return "yellow", spread_bp
    return "green", spread_bp


def carry_status(d):
    """USD/JPY + US 2y only. No JGB leg: no live FRED series (IRLTLT01JPM156N is
    monthly, last print June). Missing JGB is shown as n/a, never STRAIN."""
    c = d["carry"]
    if not c.get("usd_jpy") or not c.get("usd_jpy_3d_ago"):
        return None, None
    rally = (c["usd_jpy_3d_ago"] - c["usd_jpy"]) / c["usd_jpy_3d_ago"] * 100  # + = yen strengthening
    if rally > THRESHOLDS["yen_rally_3d_pct"]:
        return "red", rally
    us2y = c.get("us2y")
    if (c["usd_jpy"] > THRESHOLDS["usd_jpy_yellow"] or rally > 1.0
            or (c["usd_jpy"] > THRESHOLDS["usdjpy_stretch"] and us2y is not None
                and us2y >= THRESHOLDS["us2y_high"])):
        return "yellow", rally
    return "green", rally


def system_line(statuses):
    if "red" in statuses:
        return "System: strain. Plumbing first, headlines later."
    if "yellow" in statuses:
        return "System: tightening. Watch the yen and the short end."
    return "System: calm."
