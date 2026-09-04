"""FRED fetch with per-series independent failure. Never silently mixes demo into live."""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CALL_TIMEOUT = 8  # seconds per HTTP call; overall page budget enforced via _DEADLINE
PAGE_BUDGET = 20  # seconds max for probe + full fetch; exceeding aborts to DEMO
_DEADLINE = None


def _ensure_env():
    """Load .env next to the app dir only; normalize export/quotes/BOM/CRLF. No network. No logging."""
    try:
        from dotenv import load_dotenv
        _env_p = Path(__file__).resolve().parent.parent / ".env"  # app dir only, never cwd
        if _env_p.is_file():
            load_dotenv(dotenv_path=_env_p, override=True)
    except ImportError:
        pass
    try:
        _env_p = Path(__file__).resolve().parent.parent / ".env"
        if _env_p.is_file():
            for _ln in _env_p.read_bytes().decode("utf-8-sig").splitlines():
                _s = _ln.strip()
                if _s.startswith("export "):
                    _s = _s[len("export "):].strip()
                if _s.startswith("FRED_API_KEY") and "=" in _s:
                    _v = _s.split("=", 1)[1].strip().strip('"').strip("'").strip()
                    if _v:
                        os.environ["FRED_API_KEY"] = _v
                    break
    except Exception:
        pass


def _check_budget():
    if _DEADLINE is not None and time.monotonic() > _DEADLINE:
        raise TimeoutError("FRED timeout: 20s page budget exceeded, aborting to DEMO")

DEMO_PATH = Path(__file__).resolve().parent.parent / "data" / "demo.json"

# series -> (FRED id(s) to try in order, cadence label)
WANT = {
    "WALCL": (["WALCL"], "weekly"),
    "TGA": (["WTREGEN", "WDTGAL"], "weekly"),
    "ON RRP": (["RRPONTSYD"], "daily"),
    "SOFR": (["SOFR"], "daily"),
    "EFFR": (["EFFR"], "daily"),
    "IORB": (["IORB", "IOER"], "daily"),  # IOER = pre-2021 administered-rate predecessor
    "USD/JPY": (["DEXJPUS"], "daily"),
    "US 2y": (["DGS2"], "daily"),
    "US 10y": (["DGS10"], "daily"),
    "SWPT": (["SWPT"], "weekly"),
    "OBFRVOL": (["OBFRVOL"], "daily"),
}
# IRLTLT01JPM156N dropped from the live path: FRED search confirms it is the only
# Japan 10y series and it is monthly through 2026-06-01. No replacement found.

# Longer window for the liquidity trio so gauges can use a 4-week slope.
NLIMITS = {"WALCL": 30, "TGA": 30, "ON RRP": 30}


def load_demo():
    return json.loads(DEMO_PATH.read_text())


def _fred_obs_dated(series_id, api_key, n=8):
    """Return (values, dates) oldest-first. Raises FredError on HTTP/API failure."""
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={api_key}&file_type=json"
        f"&sort_order=desc&limit={n}"
    )
    try:
        _check_budget()
        with urllib.request.urlopen(url, timeout=CALL_TIMEOUT) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"FRED HTTP {e.code} for {series_id}: {body}")
    except TimeoutError:
        raise
    except Exception as e:
        raise RuntimeError(f"FRED request failed for {series_id}: {e}")
    obs = payload.get("observations", [])
    vals, dates = [], []
    for o in reversed(obs):
        try:
            vals.append(float(o["value"]))
            dates.append(o.get("date", "?"))
        except (ValueError, TypeError, KeyError):
            continue
    if not vals:
        raise RuntimeError(f"FRED series {series_id}: no numeric observations returned")
    return vals, dates


def env_report():
    """Which env file was found and whether the key loaded. No values, no paths."""
    app_env = Path(__file__).resolve().parent.parent / ".env"
    cwd_env = Path.cwd() / ".env"
    found = ".env" if (app_env.is_file() or cwd_env.is_file()) else None
    key = os.getenv("FRED_API_KEY", "").strip()
    if found and key:
        return key, "env: found .env (key loaded)"
    if found:
        ex = "only .env.example" if (Path(__file__).resolve().parent.parent / ".env.example").is_file() else "no .env.example"
        # .env exists (key empty) — distinguish per spec wording
        return "", "env: found .env (key missing)"
    return "", "env: no .env, only .env.example"


def connection_check(api_key):
    """Probe: SOFR observations limit=1. LIVE only on HTTP 200 + non-empty observations."""
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id=SOFR&api_key={api_key}&file_type=json&limit=1&sort_order=desc")
    try:
        _check_budget()
        with urllib.request.urlopen(url, timeout=CALL_TIMEOUT) as r:
            payload = json.loads(r.read().decode())
            status = getattr(r, "status", 200)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode(errors="replace"))
        except Exception:
            payload = {}
        msg = payload.get("error_message", f"HTTP {e.code}") if isinstance(payload, dict) else f"HTTP {e.code}"
        if e.code in (400, 401, 403):
            return False, f"FRED rejected key ({e.code}): {msg}", e.code
        return False, f"FRED probe HTTP {e.code}: {msg}", e.code
    except TimeoutError as e:
        return False, f"FRED timeout: {e}", None
    except Exception as e:
        return False, f"FRED probe failed: {e}", None
    obs = payload.get("observations", []) if isinstance(payload, dict) else []
    if status == 200 and obs:
        return True, "SOFR probe OK", status
    return False, "SOFR probe: empty observations", status


def _resolve(label, api_key):
    """Try candidate ids; return dict(ok, id_used, vals, dates, error)."""
    ids, lag = WANT[label]
    n = NLIMITS.get(label, 8)
    last_err = ""
    for sid in ids:
        try:
            _check_budget()
            vals, dates = _fred_obs_dated(sid, api_key, n=n)
            return {"ok": True, "id": sid, "vals": vals, "dates": dates, "lag": lag, "error": ""}
        except TimeoutError:
            raise
        except RuntimeError as e:
            last_err = str(e)
    return {"ok": False, "id": ids[0], "vals": [], "dates": [], "lag": lag, "error": last_err}


def fetch_live_or_demo():
    """Return dict(mode, data, updated, error, series_status, partial_flags).

    LIVE numbers are never silently replaced by demo numbers: failed series
    are None and their gauge is marked partial.
    """
    global _DEADLINE
    _ensure_env()  # env loaded here, never at import
    _DEADLINE = time.monotonic() + PAGE_BUDGET
    key = os.getenv("FRED_API_KEY", "").strip()
    _, env_msg = env_report()
    if not key:
        d = load_demo()
        return {"mode": "DEMO", "data": d, "updated": d["meta"]["as_of"] + " (demo)",
                "error": f"No FRED_API_KEY set — running demo fixtures. {env_msg}",
                "series_status": {}, "partial": {}, "checked_at": None,
                "env": env_msg, "probe_status": None}

    ok, msg, status = connection_check(key)
    if not ok:
        d = load_demo()
        return {"mode": "DEMO", "data": d, "updated": d["meta"]["as_of"] + " (demo)",
                "error": f"{msg}. {env_msg}", "series_status": {}, "partial": {},
                "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "env": env_msg, "probe_status": status}

    try:
        res = {label: _resolve(label, key) for label in WANT}
    except TimeoutError as e:
        d = load_demo()
        return {"mode": "DEMO", "data": d, "updated": d["meta"]["as_of"] + " (demo)",
                "error": f"FRED timeout: {e}. {env_msg}", "series_status": {}, "partial": {},
                "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "env": env_msg, "probe_status": status}
    finally:
        _DEADLINE = None

    # OBFRVOL: skip quietly if missing
    if not res["OBFRVOL"]["ok"]:
        res["OBFRVOL"]["error"] = "OBFRVOL unavailable — skipped quietly."

    def last(label):
        r = res[label]
        return r["vals"][-1] if r["ok"] else None

    def prev(label):
        r = res[label]
        return r["vals"][-2] if r["ok"] and len(r["vals"]) >= 2 else None

    liq_ok = all(res[k]["ok"] for k in ("WALCL", "TGA", "ON RRP"))
    dol_ok = all(res[k]["ok"] for k in ("SOFR", "IORB", "SWPT"))  # EFFR/OBFRVOL optional extras
    car_ok = res["USD/JPY"]["ok"] and res["US 2y"]["ok"]  # JGB dropped: no live FRED series

    data = {"liquidity": {}, "dollar": {}, "carry": {}, "series": {}, "meta": {},
            "hist": {}, "asof": {}}
    data["asof"] = {k: (v["dates"][-1] if v["ok"] and v["dates"] else None)
                    for k, v in res.items()}
    data["lag"] = {k: v["lag"] for k, v in res.items()}
    if liq_ok:
        # FRED money-stock levels print in $M → normalize to $B once, here.
        bn = {k: [v / 1000.0 for v in res[k]["vals"]] for k in ("WALCL", "TGA", "ON RRP")}
        walcl, walcl_p = bn["WALCL"][-1], bn["WALCL"][-2]
        tga, tga_p = bn["TGA"][-1], bn["TGA"][-2]
        data["liquidity"] = {"walcl": walcl, "walcl_prev": walcl_p, "tga": tga,
                             "tga_prev": tga_p, "onrrp": bn["ON RRP"][-1]}
        data["hist"] = {"WALCL": {"dates": res["WALCL"]["dates"], "vals": bn["WALCL"]},
                        "TGA": {"dates": res["TGA"]["dates"], "vals": bn["TGA"]},
                        "ON RRP": {"dates": res["ON RRP"]["dates"], "vals": bn["ON RRP"]}}
        data["series"]["net_liquidity"] = [
            w - t - r for w, t, r in
            zip(bn["WALCL"][-7:], bn["TGA"][-7:], bn["ON RRP"][-7:])]
    if dol_ok:
        swpt_b = last("SWPT") / 1000.0  # SWPT is $ millions -> $B
        data["dollar"] = {"sofr": last("SOFR"), "iorb": last("IORB"),
                          "iorb_id": res["IORB"]["id"],
                          "effr": last("EFFR"), "swpt": swpt_b,
                          "obfrvol": last("OBFRVOL")}
        n = min(len(res["SOFR"]["vals"]), len(res["IORB"]["vals"]), 7)
        data["series"]["sofr_iorb_bp"] = [
            (res["SOFR"]["vals"][-n + i] - res["IORB"]["vals"][-n + i]) * 100 for i in range(n)]
    if car_ok:
        uj, uj_vals = last("USD/JPY"), res["USD/JPY"]["vals"]
        u10 = last("US 10y")
        data["carry"] = {"usd_jpy": uj,
                         "usd_jpy_3d_ago": uj_vals[-4] if len(uj_vals) >= 4 else uj_vals[0],
                         "jgb10y": None, "us_jp_10y_gap": None,  # no live FRED JGB series
                         "us2y": last("US 2y"), "us10y": u10}
        data["series"]["usd_jpy"] = uj_vals[-7:]

    checked = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data["meta"] = {"as_of": checked, "mode": "LIVE", "note": "FRED live series."}
    partial = {"liquidity": not liq_ok, "dollar": not dol_ok, "carry": not car_ok}
    errs = [f"{k}: {v['error']}" for k, v in res.items() if not v["ok"] and k != "OBFRVOL"]
    return {"mode": "LIVE", "data": data, "updated": checked, "error": "; ".join(errs),
            "series_status": res, "partial": partial, "checked_at": checked,
            "env": env_report()[1], "probe_status": 200}
