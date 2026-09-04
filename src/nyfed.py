"""NY Fed same-day rates pipe: EFFR / OBFR (unsecured) + SOFR (secured). No key. Daily cache."""
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "StrainGauge/1.0 (Lorca Labs; local dashboard)"}
BASE = "https://markets.newyorkfed.org/api/rates"
ENDPOINTS = {"EFFR": f"{BASE}/unsecured/effr/last/3.json",
             "OBFR": f"{BASE}/unsecured/obfr/last/3.json",
             "SOFR": f"{BASE}/secured/sofr/last/3.json"}
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "nyfed_rates.json"
TZ = ZoneInfo("America/Chicago")


def _today():
    return datetime.now(TZ).date().isoformat()


def _fetch(url):
    last = None
    for _ in range(2):  # one retry
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except Exception as e:
            code = getattr(e, "code", "ERR")
            last = RuntimeError(f"HTTP {code}")
    raise last


def _latest(payload):
    """Newest refRates obs → (date, rate, volume_bn). Volume may be absent."""
    obs = (payload.get("refRates") or payload.get("rates") or [])[-1]
    return obs.get("effectiveDate"), obs.get("percentRate"), obs.get("volumeInBillions")


def get_nyfed_rates():
    """Return {ok, date, sofr, effr, obfr, sofr_vol_bn, stale, note, cache}. Never raises."""
    rel = "data/cache/nyfed_rates.json"
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    today = _today()

    def fresh():
        try:
            d = json.loads(CACHE.read_text())
            return bool(d) and d.get("_day") == today and d.get("sofr") is not None
        except Exception:
            return False

    if fresh():
        d = json.loads(CACHE.read_text())
        d.update({"ok": True, "stale": False, "note": f"cached · {rel}", "cache": rel})
        return d
    try:
        out, codes = {}, []
        for name, url in ENDPOINTS.items():
            status, payload = _fetch(url)
            codes.append(str(status))
            dt, rate, vol = _latest(payload)
            out[name.lower()] = rate
            if name == "SOFR":
                out["date"], out["sofr_vol_bn"] = dt, vol
            if name == "EFFR":
                out["effr_date"] = dt
        if out.get("sofr") is None:
            raise RuntimeError("SOFR obs missing")
        d = {"_day": today, **out,
             "ok": True, "stale": False,
             "note": f"HTTP {'/'.join(codes)} · {rel}", "cache": rel}
        CACHE.write_text(json.dumps(d))
        return d
    except RuntimeError as e:
        try:
            d = json.loads(CACHE.read_text())
            d.update({"ok": d.get("sofr") is not None, "stale": True,
                      "note": f"{e} · {rel}", "cache": rel})
            return d
        except Exception:
            return {"ok": False, "stale": True, "date": None, "sofr": None,
                    "effr": None, "obfr": None, "note": f"{e} · {rel}", "cache": rel}
