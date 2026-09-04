"""Daily USD/JPY pipe: FRED DEXJPUS preferred, keyless public close fallback. Daily cache.

Fallback chain (documented URLs, all keyless public JSON/XML):
  1. FRED DEXJPUS (passed in by caller) if no more than 3 days old
  2. https://open.er-api.com/v6/latest/USD            → rates.JPY, time_last_update_utc
  3. https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml → USDJPY = JPY/EUR ÷ USD/EUR
Rolling closes accumulate in cache for the 3-day rally read. No BOJ scrape:
no stable public JSON found (FRED only has monthly OECD prints) — skipped.
"""
import json
import re
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "StrainGauge/1.0 (Lorca Labs; local dashboard)"}
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "usdjpy_daily.json"
TZ = ZoneInfo("America/Chicago")
ER_API = "https://open.er-api.com/v6/latest/USD"
ECB = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


def _today():
    return datetime.now(TZ).date().isoformat()


def _fetch(url, parse):
    last = None
    for _ in range(2):  # one retry
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, parse(r.read().decode())
        except Exception as e:
            code = getattr(e, "code", "ERR")
            last = RuntimeError(f"HTTP {code}")
    raise last


def _er_api(body):
    d = json.loads(body)
    dt = parsedate_to_datetime(d["time_last_update_utc"]).date().isoformat()
    return dt, float(d["rates"]["JPY"])


def _ecb(body):
    day = re.findall(r"time='(\d{4}-\d{2}-\d{2})'", body)[0]
    rates = dict(re.findall(r"currency='(USD|JPY)' rate='([\d.]+)'", body))
    return day, float(rates["JPY"]) / float(rates["USD"])


def get_usdjpy_daily(fred_date=None, fred_val=None):
    """Return {ok, date, val, val_3d_ago, source, stale, note, cache}. Never raises."""
    rel = "data/cache/usdjpy_daily.json"
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    today = _today()
    try:
        cache = json.loads(CACHE.read_text())
        closes = cache.get("closes", [])
    except Exception:
        closes, cache = [], {}

    def _record(date, val, source, status_note, stale=False):
        if val is not None and (not closes or closes[-1]["date"] < date):
            closes.append({"date": date, "val": val})
        hist = closes[-14:]
        # 3-calendar-day reference: newest close on/before latest − 3d
        y, m, dd = map(int, hist[-1]["date"].split("-"))
        from datetime import date as _date
        cutoff = _date(y, m, dd).toordinal() - 3
        ref = hist[0]
        for c in hist:
            cy, cm, cd = map(int, c["date"].split("-"))
            if _date(cy, cm, cd).toordinal() <= cutoff:
                ref = c
        d = {"_day": today, "date": hist[-1]["date"], "val": hist[-1]["val"],
             "val_3d_ago": ref["val"], "ref_date": ref["date"], "source": source,
             "closes": hist, "ok": True, "stale": stale,
             "note": f"{status_note} · {rel}", "cache": rel}
        CACHE.write_text(json.dumps(d))
        return d

    if cache.get("_day") == today and cache.get("val") is not None:
        cache.update({"ok": True, "stale": False,
                      "note": f"cached · {rel}", "cache": rel})
        return cache

    # 1. FRED DEXJPUS if fresh (≤3 days vs today)
    if fred_date and fred_val is not None:
        try:
            y, m, dd = map(int, fred_date.split("-"))
            ty, tm, td = map(int, today.split("-"))
            from datetime import date as _date
            if (_date(ty, tm, td) - _date(y, m, dd)).days <= 3:
                return _record(fred_date, float(fred_val), "FRED DEXJPUS", "FRED fresh")
        except Exception:
            pass
    # 2-3. Keyless public closes. Prefer ECB when both prints are ≤2 days old;
    # otherwise take the newest available. (Wrapper open.er-api.com is fallback.)
    from datetime import date as _date
    ty, tm, td = map(int, today.split("-"))
    _now = _date(ty, tm, td).toordinal()
    got = []
    for url, parse, name in ((ER_API, _er_api, "open.er-api.com"), (ECB, _ecb, "ECB eurofxref")):
        try:
            status, (dt, val) = _fetch(url, parse)
            got.append((dt, val, name, status))
        except RuntimeError:
            continue
    if got:
        fresh = [(dt, val, name, st) for dt, val, name, st in got
                 if _now - _date(*map(int, dt.split("-"))).toordinal() <= 2]
        ecb = [g for g in fresh if g[2] == "ECB eurofxref"]
        pick = ecb[0] if ecb else max(got, key=lambda g: g[0])
        dt, val, name, status = pick
        return _record(dt, val, name, f"HTTP {status}")
    # 4. Fail open on last cached close
    if closes:
        d = {"_day": closes[-1]["date"], "date": closes[-1]["date"], "val": closes[-1]["val"],
             "val_3d_ago": closes[0]["val"], "ref_date": closes[0]["date"],
             "source": cache.get("source", "cache"), "closes": closes,
             "ok": True, "stale": True, "note": f"all sources failed · {rel}", "cache": rel}
        return d
    return {"ok": False, "stale": True, "date": None, "val": None, "val_3d_ago": None,
            "source": "none", "note": f"all sources failed · {rel}", "cache": rel}
