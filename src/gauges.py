"""Thresholds → status + plain-English copy. Single config dict."""

THRESHOLDS = {
    "sofr_iorb_bp": {"green_max": 5, "yellow_max": 15},  # bp; red above yellow_max
    "tga_wow_rise": 30.0,        # $B week-over-week rise = fast drain flag
    "net_liq_slope_warn": 0.0,   # $B slope below this = draining
    "usd_jpy_yellow": 158.0,
    "yen_rally_3d_pct": 2.0,     # >2% 3-day yen rally (USDJPY fall) = red
    "jgb10y_red": 3.0,
    "usdjpy_red_hold": 157.0,
    "swpt_yellow_bn": 1.0,       # $B
    "swpt_red_bn": 10.0,
}

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


def liquidity_status(d):
    liq = d["liquidity"]
    net = liq["walcl"] - liq["tga"] - liq["onrrp"]
    prev = liq["walcl_prev"] - liq["tga_prev"] - liq["onrrp"]
    slope = net - prev
    tga_rise = liq["tga"] - liq["tga_prev"]
    if slope < -40 or net < 5400:
        return "red", net, slope
    if slope < THRESHOLDS["net_liq_slope_warn"] or tga_rise > THRESHOLDS["tga_wow_rise"]:
        return "yellow", net, slope
    return "green", net, slope


def dollar_status(d):
    dol = d["dollar"]
    spread_bp = (dol["sofr"] - dol["iorb"]) * 100
    swpt = dol["swpt"]  # $B
    if spread_bp > THRESHOLDS["sofr_iorb_bp"]["yellow_max"] or swpt > THRESHOLDS["swpt_red_bn"]:
        return "red", spread_bp
    if spread_bp >= THRESHOLDS["sofr_iorb_bp"]["green_max"] or swpt > THRESHOLDS["swpt_yellow_bn"]:
        return "yellow", spread_bp
    # near-zero ON RRP = buffer gone: yellow only if TGA also elevated
    liq = d["liquidity"]
    if liq["onrrp"] < 50 and liq["tga"] > 800:
        return "yellow", spread_bp
    return "green", spread_bp


def carry_status(d):
    c = d["carry"]
    rally = (c["usd_jpy_3d_ago"] - c["usd_jpy"]) / c["usd_jpy_3d_ago"] * 100  # + = yen strengthening
    if rally > THRESHOLDS["yen_rally_3d_pct"] or (
        c["jgb10y"] >= THRESHOLDS["jgb10y_red"] and c["usd_jpy"] > THRESHOLDS["usdjpy_red_hold"]
    ):
        return "red", rally
    if c["usd_jpy"] > THRESHOLDS["usd_jpy_yellow"] or c["jgb10y"] > 2.0 or rally > 1.0:
        return "yellow", rally
    return "green", rally


def system_line(statuses):
    if "red" in statuses:
        return "System: strain. Plumbing first, headlines later."
    if "yellow" in statuses:
        return "System: tightening. Watch the yen and the short end."
    return "System: calm."
