"""Turn raw source rows into canonical dataset records."""
from __future__ import annotations

import re
from datetime import date

from .sources.tc_evap import RawVehicle


def slug(*parts: str) -> str:
    s = "-".join(p for p in parts if p)
    s = s.replace("+", " plus ").replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s


def vehicle_id(v: RawVehicle) -> str:
    return slug(str(v.model_year), v.make, v.model, v.trim or "base")


def normalize(v: RawVehicle, rules: dict, snapshot_date: date) -> dict:
    cap = rules["price_cap"]["max_cad"]
    return {
        "id": vehicle_id(v),
        "program_id": rules["program"]["id"],
        "model_year": v.model_year,
        "make": v.make.strip(),
        "model": v.model.strip(),
        "trim": v.trim.strip() or None,
        "fuel_type": v.fuel_type,
        "canadian_made": v.canadian_made,
        "price_cap_cad": None if v.canadian_made else cap,
        "price_cap_basis": rules["price_cap"]["basis"],
        # Amounts exactly as published by TC for the current year. The calculator derives
        # other years/terms from rules; these are kept so the dataset can be cross-checked.
        "published": {
            "year": snapshot_date.year,
            "purchase_or_48mo": v.incentive_purchase_or_48mo,
            "lease_36mo": v.incentive_36mo,
            "lease_24mo": v.incentive_24mo,
            "lease_12mo": v.incentive_12mo,
        },
        "source": {
            "name": "tc_evap_vehicle_list",
            "row_hash": v.row_hash,
            "page": v.page,
        },
    }


def consistency_issues(rec: dict, rules: dict) -> list[str]:
    """Cross-check the published amounts against the rules file. Any issue here means
    either TC changed the program or the rules file is stale, so a human must look."""
    from .rules import full_amount
    issues = []
    year = rec["published"]["year"]
    full = full_amount(rules, rec["fuel_type"], year)
    pub = rec["published"]
    if full is None:
        return [f"no schedule for year {year}"]
    if pub["purchase_or_48mo"] != full:
        issues.append(f"published full amount {pub['purchase_or_48mo']} != rules {full} for {year}")
    for months, key in ((36, "lease_36mo"), (24, "lease_24mo"), (12, "lease_12mo")):
        expect = full * months / rules["lease"]["full_incentive_term_months"]
        if abs(pub[key] - expect) > 0.5:
            issues.append(f"published {key}={pub[key]} != prorated {expect:.2f}")
    return issues
