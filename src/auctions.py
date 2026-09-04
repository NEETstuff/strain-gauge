"""Treasury auction prints: TreasuryDirect TA_WS auctioned securities. No key. Daily cache.

Endpoint: https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json
Fields mapped: securityType (Bill/Note/Bond), securityTerm, auctionDate,
bidToCoverRatio, highInvestmentRate/highDiscountRate (bills), highYield (coupons).
No when-issued in payload → tail skipped, never invented.
"""
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "StrainGauge/1.0 (Lorca Labs; local dashboard)"}
URL = "https://www.treasurydirect.gov/TA_WS/securities/auctioned?format=json&limit=40"
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "auctions.json"
TZ = ZoneInfo("America/Chicago")

TERM_SHORT = {"4-Week": "4w", "8-Week": "8w", "13-Week": "13w", "17-Week": "17w",
              "26-Week": "6m", "52-Week": "1y", "2-Year": "2y", "3-Year": "3y",
              "5-Year": "5y", "7-Year": "7y", "10-Year": "10y", "20-Year": "20y",
              "30-Year": "30y"}


def _today():
    return datetime.now(TZ).date().isoformat()


def _fetch():
    last = None
    for _ in range(2):  # one retry
        try:
            req = urllib.request.Request(URL, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except Exception as e:
            code = getattr(e, "code", "ERR")
            last = RuntimeError(f"HTTP {code}")
    raise last


def _num(x):
    try:
        return float(x) if x not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _pick(rows, stype):
    done = [r for r in rows if r.get("securityType") == stype and _num(r.get("bidToCoverRatio"))]
    done.sort(key=lambda r: r.get("auctionDate", ""), reverse=True)
    return done[0] if done else None


def get_auctions():
    """Return {ok, line, bill, coupon, stale, note, cache}. Never raises."""
    rel = "data/cache/auctions.json"
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    today = _today()
    try:
        d = json.loads(CACHE.read_text())
        if d.get("_day") == today and d.get("line"):
            d.update({"ok": True, "stale": False, "note": f"cached · {rel}", "cache": rel})
            return d
    except Exception:
        pass
    try:
        status, rows = _fetch()
        bill, cpn = _pick(rows, "Bill"), None
        for t in ("Note", "Bond"):
            cpn = _pick(rows, t)
            if cpn:
                break
        if not bill and not cpn:
            raise RuntimeError("no completed auctions parsed")

        def fmt(r, is_bill):
            term = TERM_SHORT.get(r.get("securityTerm", ""), r.get("securityTerm", ""))
            rate = _num(r.get("highInvestmentRate") or r.get("highDiscountRate")) if is_bill \
                else _num(r.get("highYield"))
            dat = (r.get("auctionDate") or "")[:10]
            return {"term": term, "btc": _num(r.get("bidToCoverRatio")),
                    "rate": rate, "date": dat}

        b, c = (fmt(bill, True) if bill else None), (fmt(cpn, False) if cpn else None)
        parts = []
        if b:
            parts.append(f"Bills: BTC {b['btc']:.2f} · {b['term']} {b['rate']:.2f}% · {b['date'][5:]}")
        if c:
            parts.append(f"{c['term']}: BTC {c['btc']:.2f} · {c['rate']:.2f}% · {c['date'][5:]}")
        d = {"_day": today, "line": " | ".join(parts), "bill": b, "coupon": c,
             "ok": True, "stale": False, "note": f"HTTP {status} · {rel}", "cache": rel}
        CACHE.write_text(json.dumps(d))
        return d
    except RuntimeError as e:
        try:
            d = json.loads(CACHE.read_text())
            if d.get("line"):
                d.update({"ok": True, "stale": True, "note": f"{e} · {rel}", "cache": rel})
                return d
        except Exception:
            pass
        return {"ok": False, "stale": True, "line": "Auctions: no parseable feed — check TreasuryDirect.",
                "note": f"{e} · {rel}", "cache": rel}
