"""COMEX gold stocks pipe: registered vs eligible. No key.

Attempted (documented, keyless, durable):
  https://www.cmegroup.com/delivery_reports/GoldStocksReport.csv       → 403 anti-scrape
  https://www.cmegroup.com/delivery_reports/MetalsSettlementReport.csv → 403 anti-scrape
FRED series/search "comex gold stocks" → 0 hits.
CME hard-blocks scripts, so there is no durable script-safe URL for both numbers.
Result: COMEX: feed not mapped. Retried daily; no blog scraping, no invented numbers.
"""
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "StrainGauge/1.0 (Lorca Labs; local dashboard)"}
URL = "https://www.cmegroup.com/delivery_reports/GoldStocksReport.csv"
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "comex_gold.json"
TZ = ZoneInfo("America/Chicago")


def _today():
    return datetime.now(TZ).date().isoformat()


def get_comex_gold():
    """Return {ok, mapped, line, ...}. Never raises. ok=False → not-mapped line."""
    rel = "data/cache/comex_gold.json"
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    today = _today()
    try:
        d = json.loads(CACHE.read_text())
        if d.get("_day") == today:
            d.update({"note": f"cached · {rel}", "cache": rel})
            return d
    except Exception:
        pass
    reason = "CME 403 anti-scrape; no FRED series"
    for _ in range(2):  # one retry
        try:
            req = urllib.request.Request(URL, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read().decode(errors="replace")
            # Only accept if both registered and eligible parse cleanly; else not-mapped.
            low = body.lower()
            if "registered" in low and "eligible" in low:
                raise RuntimeError("CSV shape unconfirmed — refusing to guess columns")
            raise RuntimeError("registered+eligible not parseable")
        except Exception as e:
            code = getattr(e, "code", None)
            reason = f"CME HTTP {code}" if code else str(e)[:80]
    d = {"_day": today, "ok": False, "mapped": False,
         "line": "COMEX: feed not mapped",
         "note": f"{reason} · {rel}", "cache": rel}
    CACHE.write_text(json.dumps(d))
    return d
