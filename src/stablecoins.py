"""Daily, keyless DefiLlama stablecoin scrape. No auth. Daily cache only."""
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "StrainGauge/1.0 (Lorca Labs; local dashboard)"}
LIST_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
HIST_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
LATEST_PATH = CACHE_DIR / "stablecoins_latest.json"
HIST_PATH = CACHE_DIR / "stablecoins_history.json"
TZ = ZoneInfo("America/Chicago")
TRACK = ("USDT", "USDC", "RLUSD", "DAI")


def _today():
    return datetime.now(TZ).date().isoformat()


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except Exception as e:
        code = getattr(e, "code", "ERR")
        raise RuntimeError(f"HTTP {code}") from e


def _fetch(url):
    last = None
    for _ in range(2):  # one retry
        try:
            return _get(url)
        except RuntimeError as e:
            last = e
    raise last


def _num(x):
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, dict):  # e.g. {"peggedUSD": ...}
        for k in ("peggedUSD", "peggedEUR", "peggedVAR"):
            if isinstance(x.get(k), (int, float)):
                return float(x[k])
        for v in x.values():
            if isinstance(v, (int, float)):
                return float(v)
    return None


def _parse_latest(payload):
    assets = payload.get("peggedAssets", payload if isinstance(payload, list) else [])
    rows = {}
    for a in assets:
        sym = str(a.get("symbol", "")).upper()
        mcap = _num(a.get("circulating", a.get("mcap")))
        if sym and isinstance(mcap, (int, float)):
            rows[sym] = {"name": a.get("name", sym), "mcap": float(mcap),
                         "price": a.get("price"), "change_24h": a.get("change_24h"),
                         "change_7d": a.get("change_7d")}
    total = sum(v["mcap"] for v in rows.values())
    other = total - sum(rows.get(s, {"mcap": 0})["mcap"] for s in TRACK if s in rows)
    return total, rows, other


def _parse_hist(payload):
    pts = payload if isinstance(payload, list) else payload.get("data", payload.get("chart", []))
    out = []
    for p in pts:
        if isinstance(p, dict):
            t = _num(p.get("totalCirculatingUSD", p.get("totalCirculating")))
            d = p.get("date")
            if isinstance(t, (int, float)):
                out.append({"date": d, "total": float(t)})
        elif isinstance(p, (list, tuple)) and len(p) == 2:
            out.append({"date": p[0], "total": float(p[1])})
    return out[-180:]


def get_stablecoins():
    """Return dict for the On-chain dollars card. Never raises; never touches gauges."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today = _today()
    note, stale = "", False

    def fresh(path):
        try:
            d = json.loads(path.read_text())
            return bool(d) and d.get("_day") == today
        except Exception:
            return False

    if fresh(LATEST_PATH) and fresh(HIST_PATH):
        note = "cached · data/cache/stablecoins_latest.json"
        latest, hist = json.loads(LATEST_PATH.read_text()), json.loads(HIST_PATH.read_text())
    else:
        try:
            s1, lp = _fetch(LIST_URL)
            s2, hp = _fetch(HIST_URL)
            total, rows, other = _parse_latest(lp)
            hist_pts = _parse_hist(hp)
            latest = {"_day": today, "total_mcap": total, "assets": rows, "other_mcap": other}
            hist = {"_day": today, "points": hist_pts}
            LATEST_PATH.write_text(json.dumps(latest))
            HIST_PATH.write_text(json.dumps(hist))
            note = f"HTTP {s1} · data/cache/stablecoins_latest.json"
        except RuntimeError as e:
            stale = True
            note = f"{e} · data/cache/stablecoins_latest.json"
            try:
                latest, hist = json.loads(LATEST_PATH.read_text()), json.loads(HIST_PATH.read_text())
            except Exception:
                return {"ok": False, "stale": True, "note": note, "cache": "data/cache/stablecoins_latest.json"}

    pts = hist.get("points", [])
    total = latest.get("total_mcap", 0)
    chg7 = None
    if len(pts) >= 8:
        base = pts[-8]["total"] or 1
        chg7 = (pts[-1]["total"] - base) / base * 100
    direction = "flat" if chg7 is None or abs(chg7) < 0.5 else ("rising" if chg7 > 0 else "falling")
    line = {"rising": "More tokenized dollars in circulation.",
            "flat": "Stablecoin float is steady.",
            "falling": "Tokenized dollars are leaving the system."}[direction]
    return {"ok": True, "total_mcap": total, "chg7": chg7, "direction": direction, "line": line,
            "assets": latest.get("assets", {}), "other_mcap": latest.get("other_mcap", 0),
            "stale": stale, "note": note, "cache": "data/cache/stablecoins_latest.json"}
