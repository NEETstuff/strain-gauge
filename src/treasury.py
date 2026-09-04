"""Daily TGA pipe: Treasury Fiscal Data DTS operating-cash table. No key. Daily cache."""
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "StrainGauge/1.0 (Lorca Labs; local dashboard)"}
URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
       "v1/accounting/dts/operating_cash_balance?sort=-record_date&page[size]=30")
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "tga_daily.json"
TZ = ZoneInfo("America/Chicago")
TGA_ROW = "Treasury General Account (TGA) Closing Balance"


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


def get_tga_daily():
    """Return {ok, date, tga_bn, stale, note, cache}. Never raises. Context only."""
    rel = "data/cache/tga_daily.json"
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    today = _today()

    def fresh():
        try:
            d = json.loads(CACHE.read_text())
            return bool(d) and d.get("_day") == today and d.get("tga_bn")
        except Exception:
            return False

    if fresh():
        d = json.loads(CACHE.read_text())
        d.update({"ok": True, "stale": False, "note": f"cached · {rel}", "cache": rel})
        return d
    try:
        status, payload = _fetch()
        date, val = None, None
        for row in payload.get("data", []):
            if row.get("account_type") == TGA_ROW and row.get("open_today_bal") not in (None, "null", ""):
                # close_today_bal is null post-Apr-2022; the closing value sits in open_today_bal ($M)
                date, val = row["record_date"], float(row["open_today_bal"]) / 1000.0
                break
        if val is None:
            raise RuntimeError("TGA closing row not found")
        d = {"_day": today, "date": date, "tga_bn": val,
             "ok": True, "stale": False, "note": f"HTTP {status} · {rel}", "cache": rel}
        CACHE.write_text(json.dumps(d))
        return d
    except RuntimeError as e:
        try:
            d = json.loads(CACHE.read_text())
            d.update({"ok": bool(d.get("tga_bn")), "stale": True,
                      "note": f"{e} · {rel}", "cache": rel})
            return d
        except Exception:
            return {"ok": False, "stale": True, "date": None, "tga_bn": None,
                    "note": f"{e} · {rel}", "cache": rel}
