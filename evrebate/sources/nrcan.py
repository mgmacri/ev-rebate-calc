"""Source adapter: NRCan fuel consumption ratings (open data) for BEVs and PHEVs.

Gives range, energy consumption, vehicle class and recharge time. NRCan names models
differently from Transport Canada (e.g. "Equinox EV AWD (11.5 kW Charger)"), so
matching is heuristic: same model year + make, then the NRCan model whose normalized
name shares the longest prefix with the TC model, with trim tokens (AWD, Long Range,
Extended Range, Performance) used as tie-breakers. Each match carries a confidence.
"""
from __future__ import annotations

import csv
import io
import re
import urllib.request

BEV_URL = ("https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/"
           "026e45b4-eb63-451f-b34f-d9308ea3a3d9/download/my2012-2026-battery-electric-vehicles.csv")
PHEV_URL = ("https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/"
            "8812228b-a6aa-4303-b3d0-66489225120d/download/my2012-2026-plug-in-hybrid-electric-vehicles.csv")
UA = "evrebate-pipeline/0.1"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8-sig", errors="replace")


def _rows(text: str) -> list[dict]:
    rdr = csv.DictReader(io.StringIO(text))
    out = []
    for r in rdr:
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if r.get("Model year", "").isdigit():
            out.append(r)
    return out


def parse_bev(text: str) -> list[dict]:
    out = []
    for r in _rows(text):
        out.append({
            "model_year": int(r["Model year"]), "make": r["Make"], "model": r["Model"],
            "vehicle_class": r["Vehicle class"], "motor_kw": _num(r.get("Motor (kW)")),
            "combined_kwh_100km": _num(r.get("Combined (kWh/100 km)")),
            "combined_le_100km": _num(r.get("Combined (Le/100 km)")),
            "range_km": _num(r.get("Range (km)")), "recharge_h": _num(r.get("Recharge time (h)")),
            "fuel_type": "BEV",
        })
    return out


def parse_phev(text: str) -> list[dict]:
    out = []
    for r in _rows(text):
        out.append({
            "model_year": int(r["Model year"]), "make": r["Make"], "model": r["Model"],
            "vehicle_class": r["Vehicle class"], "motor_kw": _num(r.get("Motor (kW)")),
            "combined_le_100km": _num(r.get("Combined Le/100 km")),
            "range_km": _num(r.get("Range 1 (km)")),            # electric range
            "gas_combined_l_100km": _num(r.get("Combined (L/100 km)")),
            "total_range_km": _sum(_num(r.get("Range 1 (km)")), _num(r.get("Range 2 (km)"))),
            "recharge_h": _num(r.get("Recharge time (h)")), "fuel_type": "PHEV",
        })
    return out


def _num(s):
    if s is None: return None
    s = s.replace(",", "").strip()
    try: return float(s) if "." in s else int(s)
    except ValueError: return None


def _sum(a, b):
    return None if a is None or b is None else a + b


_STOP = {"ev", "electric", "phev", "plug-in", "plug", "in", "hybrid", "bev"}
_TOKENS = {"awd", "fwd", "rwd", "4wd", "long", "extended", "standard", "range", "performance",
           "twin", "single", "motor", "gt", "sport", "plus", "premium", "limited", "touring",
           "light", "wind", "land", "core", "ultra", "select", "s", "sv", "sl", "se", "xse",
           "xle", "le", "lt", "rs", "lx", "ex", "gs", "es", "b", "cross", "country", "woodland"}
_ALIAS = {"eawd": ["awd"], "lr": ["long", "range"], "sr": ["standard", "range"], "all4": ["awd"]}


def _norm(s: str) -> list[str]:
    s = s.lower().replace("-", " ").replace("_", " ").replace("+", " plus ")
    s = re.sub(r"\([^)]*\)", " ", s)
    out = []
    for t in re.split(r"[^a-z0-9.]+", s):
        if not t or t in _STOP:
            continue
        out.extend(_ALIAS.get(t, [t]))
    return out


def _make_alias(make: str) -> str:
    return make.lower()


def match(vehicle: dict, nrcan: list[dict]) -> dict | None:
    """Return the best NRCan row for a TC vehicle plus a match confidence, or None."""
    yr, mk = vehicle["model_year"], _make_alias(vehicle["make"])
    cands = [r for r in nrcan if r["fuel_type"] == vehicle["fuel_type"] and _make_alias(r["make"]) == mk]
    if not cands:
        return None
    # NRCan lags brand-new model years; fall back to the newest available year <= yr
    years = sorted({r["model_year"] for r in cands if r["model_year"] <= yr}, reverse=True)
    if not years:
        return None
    tc_all = set(_norm(vehicle["model"])) | set(_norm(vehicle.get("trim") or ""))
    core_tc = {t for t in _norm(vehicle["model"]) if t not in _TOKENS}
    extra_tc = tc_all - core_tc
    best, best_score, best_year = None, -1e9, None
    for y in years[:2]:
        for r in (c for c in cands if c["model_year"] == y):
            nm = set(_norm(r["model"]))
            core_n = {t for t in nm if t not in _TOKENS}
            if not core_tc or not (core_tc <= core_n or core_n <= core_tc):
                continue
            extra_n = nm - core_n
            score = 10 * len(core_tc & core_n) - 2 * len(core_n ^ core_tc)
            score += 2 * len(extra_n & extra_tc) - 1 * len(extra_n - extra_tc) - 1 * len(extra_tc - extra_n)
            if score > best_score:
                best, best_score, best_year = r, score, y
        if best is not None:
            break
    if best is None:
        return None
    exact = (set(_norm(best["model"])) - {t for t in _norm(best["model"]) if t not in _TOKENS}) <= tc_all
    conf = "high" if best_year == yr and exact else "medium" if best_year == yr else "low"
    return {**best, "match_confidence": conf, "match_score": best_score}
