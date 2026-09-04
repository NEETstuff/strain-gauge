"""XRPL public ledger snapshot: server_info only, plus an RLUSD read if present. No key.

RPC: XRPL_JSONRPC_URL from env if set, else https://s1.ripple.com:51234/
Methods: server_info (reserve_base_xrp, base_fee_xrp, validated ledger seq/close time).
RLUSD issued-currency read needs the issuer account; no issuer is pinned here, so
RLUSD is reported as not on this server view — no invented supply.
"""
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

UA = {"User-Agent": "StrainGauge/1.0 (Lorca Labs; local dashboard)"}
DEFAULT_RPC = "https://s1.ripple.com:51234/"
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "xrpl.json"
TZ = ZoneInfo("America/Chicago")


def _today():
    return datetime.now(TZ).date().isoformat()


def _rpc(url, method):
    last = None
    for _ in range(2):  # one retry
        try:
            body = json.dumps({"method": method, "params": [{}]}).encode()
            req = urllib.request.Request(url, data=body,
                                         headers={**UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except Exception as e:
            code = getattr(e, "code", "ERR")
            last = RuntimeError(f"HTTP {code}")
    raise last


def get_xrpl():
    """Return {ok, reserve, fee, seq, close_time, rlusd, ...}. Never raises."""
    rel = "data/cache/xrpl.json"
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    today = _today()
    try:
        d = json.loads(CACHE.read_text())
        if d.get("_day") == today and d.get("seq"):
            d.update({"ok": True, "stale": False, "note": f"cached · {rel}", "cache": rel})
            return d
    except Exception:
        pass
    url = os.getenv("XRPL_JSONRPC_URL", "").strip() or DEFAULT_RPC
    try:
        status, payload = _rpc(url, "server_info")
        info = payload["result"]["info"]
        vl = info["validated_ledger"]
        d = {"_day": today, "reserve_xrp": vl.get("reserve_base_xrp"),
             "fee_xrp": vl.get("base_fee_xrp"), "seq": vl.get("seq"),
             "close_time": vl.get("close_time_iso") or info.get("time"),
             "rlusd": None, "rlusd_note": "RLUSD: not on this server view",
             "ok": True, "stale": False, "note": f"HTTP {status} · {rel}", "cache": rel}
        CACHE.write_text(json.dumps(d))
        return d
    except (RuntimeError, KeyError) as e:
        try:
            d = json.loads(CACHE.read_text())
            if d.get("seq"):
                d.update({"ok": True, "stale": True, "note": f"{e} · {rel}", "cache": rel})
                return d
        except Exception:
            pass
        return {"ok": False, "stale": True, "seq": None, "rlusd": None,
                "rlusd_note": "RLUSD: not on this server view",
                "note": f"{e} · {rel}", "cache": rel}
