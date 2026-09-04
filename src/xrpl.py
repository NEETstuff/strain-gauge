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

# Canonical RLUSD issuer (pinned, not guessed). Obligations key is the 160-bit hex
# of "RLUSD": 524C555344000000000000000000000000000000.
RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_HEX = "524C555344000000000000000000000000000000"
# Ethereum contract (context only): 0x8292bb45bf1ee4d140127049757c2e0ff06317ed
# No working keyless ETH RPC (llamarpc 521, cloudflare internal error) → not mapped.


def _today():
    return datetime.now(TZ).date().isoformat()


def _rpc(url, payload):
    last = None
    for _ in range(2):  # one retry
        try:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=body,
                                         headers={**UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except Exception as e:
            code = getattr(e, "code", "ERR")
            last = RuntimeError(f"HTTP {code}")
    raise last


def _rlusd_issued(url):
    """gateway_balances obligations for the pinned issuer. Returns (units, seq) or (None, None)."""
    try:
        _, payload = _rpc(url, {"method": "gateway_balances",
                                "params": [{"account": RLUSD_ISSUER, "ledger_index": "validated"}]})
        obl = (payload.get("result") or {}).get("obligations") or {}
        raw = obl.get(RLUSD_HEX)
        seq = (payload.get("result") or {}).get("ledger_index")
        return (float(raw), seq) if raw is not None else (None, seq)
    except (RuntimeError, ValueError, TypeError):
        return None, None


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
        status, payload = _rpc(url, {"method": "server_info", "params": [{}]})
        info = payload["result"]["info"]
        vl = info["validated_ledger"]
        issued, gw_seq = _rlusd_issued(url)
        d = {"_day": today, "reserve_xrp": vl.get("reserve_base_xrp"),
             "fee_xrp": vl.get("base_fee_xrp"), "seq": vl.get("seq"),
             "close_time": vl.get("close_time_iso") or info.get("time"),
             "rlusd": issued, "rlusd_seq": gw_seq,
             "rlusd_note": ("RLUSD: not on this server view" if issued is None else None),
             "rlusd_eth": "not mapped",
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
