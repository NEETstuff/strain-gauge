"""Primary dealer snapshot: NY Fed Markets API. No key. Daily cache.

Tried (all keyless, all documented-pattern guesses):
  /api/pd/get/positions.json              → 200 but empty timeseries (needs unknown filters)
  /api/pd/get/positions.json?last=2       → 200 but empty timeseries
  /api/pd/get/soma.json                   → 200 but empty timeseries
  /api/pd/positions/last/2.json           → 400
  /api/pd/weekly/positions/last/2.json    → 400
  /api/pd/all/fails/last/2.json           → 400
  /api/pd/get/positions.json?startDate..  → 400 (both date formats)
  /api/pd/get/transactions.json?startDate → 400
  /api/soma/all/holdings/last/2.json      → 400
The API docs page is JS-gated, so the filter params can't be confirmed.
Result: feed not mapped — sidebar says so, no numbers invented. Retried daily
in case the path starts responding.
"""
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "StrainGauge/1.0 (Lorca Labs; local dashboard)"}
BASE = "https://markets.newyorkfed.org/api/pd/get/positions.json"
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "dealers.json"
TZ = ZoneInfo("America/Chicago")


def _today():
    return datetime.now(TZ).date().isoformat()


def get_dealers():
    """Return {ok, mapped, ...}. Never raises. ok=False → 'Dealers: feed not mapped'."""
    rel = "data/cache/dealers.json"
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    today = _today()
    try:
        d = json.loads(CACHE.read_text())
        if d.get("_day") == today:
            d.update({"note": f"cached · {rel}", "cache": rel})
            return d
    except Exception:
        pass
    last = None
    for _ in range(2):  # one retry
        try:
            req = urllib.request.Request(BASE, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                payload = json.loads(r.read().decode())
            ts = ((payload.get("pd") or {}).get("timeseries") or [])
            if ts:  # mapped! parse net duration / long-short here
                d = {"_day": today, "ok": True, "mapped": True, "asof": ts[-1].get("asOfDate"),
                     "detail": ts[-1], "note": f"HTTP {r.status} · {rel}", "cache": rel}
            else:
                d = {"_day": today, "ok": False, "mapped": False,
                     "note": f"empty timeseries · {rel}", "cache": rel}
            CACHE.write_text(json.dumps(d))
            return d
        except Exception as e:
            code = getattr(e, "code", "ERR")
            last = f"HTTP {code}"
    d = {"_day": today, "ok": False, "mapped": False,
         "note": f"{last} · {rel}", "cache": rel}
    CACHE.write_text(json.dumps(d))
    return d
